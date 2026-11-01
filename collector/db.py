"""SQLite store: the long-lived history behind the weekly snapshots."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id            TEXT PRIMARY KEY,          -- 'magicbricks', 'tnrera', 'broker_feed_x'
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL,             -- portal | csv | rera
    base_url      TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running'   -- running | ok | partial | failed
);

CREATE TABLE IF NOT EXISTS source_runs (
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    source_id     TEXT NOT NULL REFERENCES sources(id),
    status        TEXT NOT NULL,             -- ok | failed | blocked | skipped | suspicious
    pages_fetched INTEGER DEFAULT 0,
    records       INTEGER DEFAULT 0,
    new_listings  INTEGER DEFAULT 0,
    expired       INTEGER DEFAULT 0,
    message       TEXT,
    PRIMARY KEY (run_id, source_id)
);

-- One row per advert on one source. The same flat on 3 portals = 3 rows sharing a property_key.
CREATE TABLE IF NOT EXISTS listings (
    id                  TEXT PRIMARY KEY,    -- sha1(source_id + source_listing_id)
    source_id           TEXT NOT NULL REFERENCES sources(id),
    source_listing_id   TEXT NOT NULL,
    url                 TEXT,
    property_key        TEXT,                -- cross-source duplicate cluster

    -- what
    title               TEXT,
    description         TEXT,
    transaction_type    TEXT,                -- sale | rent | lease
    property_type       TEXT,                -- see normalize.PROPERTY_TYPES
    category            TEXT,                -- residential | commercial | industrial | agricultural
    bhk                 REAL,
    bathrooms           INTEGER,
    furnishing          TEXT,
    construction_status TEXT,                -- ready | under_construction | new_launch
    facing              TEXT,
    floor               INTEGER,
    total_floors        INTEGER,

    -- size (always normalised to sqft; original unit kept for display, e.g. '5 cent')
    built_up_sqft       REAL,
    carpet_sqft         REAL,
    plot_sqft           REAL,
    area_unit_original  TEXT,
    area_value_original REAL,

    -- money (INR)
    price_inr           INTEGER,             -- sale price, or monthly rent
    price_max_inr       INTEGER,             -- when advertised as a range
    price_per_sqft      REAL,
    deposit_inr         INTEGER,
    maintenance_inr     INTEGER,

    -- where
    locality            TEXT,                -- canonical gazetteer name when matched
    locality_raw        TEXT,
    zone                TEXT,
    address             TEXT,
    pincode             TEXT,
    latitude            REAL,
    longitude           REAL,
    geo_precision       TEXT,                -- exact | locality | none

    -- who / legal
    posted_by           TEXT,                -- owner | agent | builder
    advertiser          TEXT,
    project_name        TEXT,
    builder             TEXT,
    rera_id             TEXT,
    approvals           TEXT,                -- JSON list: DTCP, LPA, RERA...
    amenities           TEXT,                -- JSON list
    images              TEXT,                -- JSON list of URLs

    -- lifecycle
    posted_at           TEXT,
    first_seen_at       TEXT NOT NULL,
    first_seen_run      INTEGER,
    last_seen_at        TEXT NOT NULL,
    last_seen_run       INTEGER,
    status              TEXT NOT NULL DEFAULT 'active',   -- active | inactive
    inactive_since      TEXT,
    raw                 TEXT                 -- original record JSON, for re-parsing later
);
CREATE INDEX IF NOT EXISTS ix_listings_status   ON listings(status);
CREATE INDEX IF NOT EXISTS ix_listings_source   ON listings(source_id, status);
CREATE INDEX IF NOT EXISTS ix_listings_locality ON listings(locality);
CREATE INDEX IF NOT EXISTS ix_listings_property ON listings(property_key);

CREATE TABLE IF NOT EXISTS price_history (
    listing_id    TEXT NOT NULL REFERENCES listings(id),
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    observed_at   TEXT NOT NULL,
    price_inr     INTEGER NOT NULL,
    PRIMARY KEY (listing_id, run_id)
);

-- Government-registered projects (TN RERA). Not adverts, but the trust layer behind them.
CREATE TABLE IF NOT EXISTS projects (
    rera_id          TEXT PRIMARY KEY,
    name             TEXT,
    promoter         TEXT,
    project_type     TEXT,                   -- Building | Layout
    locality         TEXT,
    address          TEXT,
    latitude         REAL,
    longitude        REAL,
    geo_precision    TEXT,
    registered_on    TEXT,
    completion_date  TEXT,
    url              TEXT,
    first_seen_at    TEXT NOT NULL,
    last_seen_at     TEXT NOT NULL,
    raw              TEXT
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    query         TEXT PRIMARY KEY,
    latitude      REAL,
    longitude     REAL,
    display_name  TEXT,
    fetched_at    TEXT NOT NULL
);

-- Weekly market snapshot so trends survive listings expiring.
CREATE TABLE IF NOT EXISTS market_snapshots (
    run_id            INTEGER NOT NULL REFERENCES runs(id),
    taken_at          TEXT NOT NULL,
    transaction_type  TEXT NOT NULL,
    property_type     TEXT NOT NULL,
    locality          TEXT NOT NULL,
    active_count      INTEGER NOT NULL,
    median_price      REAL,
    median_ppsf       REAL,
    PRIMARY KEY (run_id, transaction_type, property_type, locality)
);
"""

LISTING_FIELDS = [
    "source_id", "source_listing_id", "url", "property_key", "title", "description",
    "transaction_type", "property_type", "category", "bhk", "bathrooms", "furnishing",
    "construction_status", "facing", "floor", "total_floors", "built_up_sqft", "carpet_sqft",
    "plot_sqft", "area_unit_original", "area_value_original", "price_inr", "price_max_inr",
    "price_per_sqft", "deposit_inr", "maintenance_inr", "locality", "locality_raw", "zone",
    "address", "pincode", "latitude", "longitude", "geo_precision", "posted_by", "advertiser",
    "project_name", "builder", "rera_id", "approvals", "amenities", "images", "posted_at", "raw",
]
JSON_FIELDS = {"approvals", "amenities", "images", "raw"}

# If a source suddenly returns far fewer records than last time, it was probably blocked or
# its page layout changed. Don't expire its listings on the strength of that run.
MIN_YIELD_RATIO = 0.4
# A listing whose source has been failing this long is no longer trusted as "active".
STALE_AFTER_DAYS = 21


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_source(conn, sid, name, kind, base_url, enabled=True):
    conn.execute(
        "INSERT INTO sources(id,name,kind,base_url,enabled) VALUES(?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, kind=excluded.kind, "
        "base_url=excluded.base_url, enabled=excluded.enabled",
        (sid, name, kind, base_url, int(enabled)),
    )


def start_run(conn) -> int:
    cur = conn.execute("INSERT INTO runs(started_at) VALUES(?)", (now_iso(),))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id, status):
    conn.execute("UPDATE runs SET finished_at=?, status=? WHERE id=?", (now_iso(), status, run_id))
    conn.commit()


def record_source_run(conn, run_id, source_id, **kw):
    cols = ["run_id", "source_id"] + list(kw)
    conn.execute(
        f"INSERT OR REPLACE INTO source_runs({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
        [run_id, source_id] + list(kw.values()),
    )


def previous_yield(conn, source_id, run_id) -> int | None:
    row = conn.execute(
        "SELECT records FROM source_runs WHERE source_id=? AND run_id<? AND status='ok' "
        "ORDER BY run_id DESC LIMIT 1",
        (source_id, run_id),
    ).fetchone()
    return row["records"] if row else None


def upsert_listing(conn, listing_id: str, rec: dict, run_id: int, seen_at: str) -> bool:
    """Insert or refresh a listing. Returns True when it is new."""
    vals = {f: rec.get(f) for f in LISTING_FIELDS}
    for f in JSON_FIELDS:
        if vals[f] is not None and not isinstance(vals[f], str):
            vals[f] = json.dumps(vals[f], ensure_ascii=False, default=str)
    existing = conn.execute("SELECT id, price_inr FROM listings WHERE id=?", (listing_id,)).fetchone()
    if existing is None:
        cols = ["id"] + LISTING_FIELDS + ["first_seen_at", "first_seen_run", "last_seen_at", "last_seen_run", "status"]
        conn.execute(
            f"INSERT INTO listings({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
            [listing_id] + [vals[f] for f in LISTING_FIELDS] + [seen_at, run_id, seen_at, run_id, "active"],
        )
    else:
        sets = ",".join(f"{f}=?" for f in LISTING_FIELDS)
        conn.execute(
            f"UPDATE listings SET {sets}, last_seen_at=?, last_seen_run=?, status='active', "
            "inactive_since=NULL WHERE id=?",
            [vals[f] for f in LISTING_FIELDS] + [seen_at, run_id, listing_id],
        )
    if vals["price_inr"]:
        last = conn.execute(
            "SELECT price_inr FROM price_history WHERE listing_id=? ORDER BY run_id DESC LIMIT 1",
            (listing_id,),
        ).fetchone()
        if last is None or last["price_inr"] != vals["price_inr"]:
            conn.execute(
                "INSERT OR REPLACE INTO price_history(listing_id, run_id, observed_at, price_inr) VALUES(?,?,?,?)",
                (listing_id, run_id, seen_at, vals["price_inr"]),
            )
    return existing is None


def expire_unseen(conn, source_id: str, run_id: int, at: str) -> int:
    """After a trustworthy run of a source, anything of that source not seen in it is gone."""
    cur = conn.execute(
        "UPDATE listings SET status='inactive', inactive_since=? "
        "WHERE source_id=? AND status='active' AND (last_seen_run IS NULL OR last_seen_run<>?)",
        (at, source_id, run_id),
    )
    return cur.rowcount


def expire_stale(conn, at: str) -> int:
    cutoff = (datetime.fromisoformat(at) - timedelta(days=STALE_AFTER_DAYS)).isoformat()
    cur = conn.execute(
        "UPDATE listings SET status='inactive', inactive_since=? WHERE status='active' AND last_seen_at<?",
        (at, cutoff),
    )
    return cur.rowcount


def upsert_project(conn, rec: dict, seen_at: str):
    conn.execute(
        """INSERT INTO projects(rera_id,name,promoter,project_type,locality,address,latitude,longitude,
               geo_precision,registered_on,completion_date,url,first_seen_at,last_seen_at,raw)
           VALUES(:rera_id,:name,:promoter,:project_type,:locality,:address,:latitude,:longitude,
               :geo_precision,:registered_on,:completion_date,:url,:seen,:seen,:raw)
           ON CONFLICT(rera_id) DO UPDATE SET name=excluded.name, promoter=excluded.promoter,
               project_type=excluded.project_type, locality=excluded.locality, address=excluded.address,
               latitude=excluded.latitude, longitude=excluded.longitude, geo_precision=excluded.geo_precision,
               registered_on=excluded.registered_on, completion_date=excluded.completion_date,
               url=excluded.url, last_seen_at=excluded.last_seen_at, raw=excluded.raw""",
        {**{k: rec.get(k) for k in ("rera_id", "name", "promoter", "project_type", "locality", "address",
                                     "latitude", "longitude", "geo_precision", "registered_on",
                                     "completion_date", "url")},
         "seen": seen_at, "raw": json.dumps(rec.get("raw"), ensure_ascii=False, default=str)},
    )

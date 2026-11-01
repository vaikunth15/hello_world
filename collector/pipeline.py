"""One weekly refresh: collect -> normalise -> geocode -> dedupe -> store -> expire -> export."""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from pathlib import Path

import yaml

from . import db
from .dedupe import property_key
from .export import export_all
from .geo import Geocoder
from .http import Blocked, Fetcher
from .sources import REGISTRY
from .sources.base import build_listing, listing_id

log = logging.getLogger(__name__)


def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def run(config_path="sources.yaml", db_path="data/realestate.sqlite", out_dir="docs/data",
        only: list[str] | None = None, geocode: bool = True) -> dict:
    cfg = load_config(config_path)
    settings = cfg.get("settings", {})
    conn = db.connect(db_path)
    fetcher = Fetcher(delay_seconds=settings.get("delay_seconds", 4),
                      respect_robots=settings.get("respect_robots", True))
    geocoder = Geocoder(conn, enabled=geocode and settings.get("geocode", True),
                        max_lookups=settings.get("max_geocode_lookups", 300))
    run_id = db.start_run(conn)
    started = db.now_iso()
    summary = {}

    for sid, scfg in (cfg.get("sources") or {}).items():
        kind = scfg.get("kind", "portal")
        enabled = scfg.get("enabled", True) and (not only or sid in only)
        db.upsert_source(conn, sid, scfg.get("name", sid), kind, scfg.get("base_url"), scfg.get("enabled", True))
        if not enabled:
            continue
        src = REGISTRY[kind](sid, scfg, fetcher)
        pages_before = fetcher.pages_fetched
        records = new = 0
        status, message = "ok", None
        seen_at = db.now_iso()
        try:
            for raw in src.collect():
                if kind == "rera":
                    db.upsert_project(conn, raw, seen_at)
                    records += 1
                    continue
                defaults = raw.pop("_defaults", {}) or {}
                rec = build_listing(raw, sid, {**scfg.get("defaults", {}), **defaults})
                if rec is None:
                    continue
                geocoder.fill(rec)
                rec["property_key"] = property_key(rec)
                if db.upsert_listing(conn, listing_id(sid, rec["source_listing_id"]), rec, run_id, seen_at):
                    new += 1
                records += 1
        except Blocked as e:
            status, message = "blocked", str(e)
            log.warning("%s blocked: %s", sid, e)
        except Exception as e:  # noqa: BLE001 - one broken source must not sink the run
            status, message = "failed", f"{type(e).__name__}: {e}"
            log.exception("%s failed", sid)

        expired = 0
        if kind != "rera":
            prev = db.previous_yield(conn, sid, run_id)
            trustworthy = status == "ok" and records > 0 and (not prev or records >= db.MIN_YIELD_RATIO * prev)
            if status == "ok" and not trustworthy:
                status = "suspicious"
                message = f"only {records} records (previous good run: {prev}); listings kept, not expired"
            if trustworthy:
                expired = db.expire_unseen(conn, sid, run_id, seen_at)
        db.record_source_run(conn, run_id, sid, status=status, pages_fetched=fetcher.pages_fetched - pages_before,
                             records=records, new_listings=new, expired=expired, message=message)
        conn.commit()
        summary[sid] = {"status": status, "records": records, "new": new, "expired": expired, "message": message}
        log.info("%s: %s", sid, summary[sid])

    db.expire_stale(conn, db.now_iso())
    take_snapshot(conn, run_id, started)
    oks = [s["status"] == "ok" for s in summary.values()]
    db.finish_run(conn, run_id, "ok" if oks and all(oks) else ("partial" if any(oks) else "failed"))
    export_all(conn, out_dir)
    conn.close()
    return summary


def take_snapshot(conn, run_id, taken_at):
    groups = defaultdict(lambda: ([], []))
    for r in conn.execute("SELECT transaction_type, property_type, COALESCE(locality,'(unknown)') AS loc, "
                          "price_inr, price_per_sqft FROM listings WHERE status='active'"):
        prices, ppsf = groups[(r["transaction_type"], r["property_type"], r["loc"])]
        if r["price_inr"]:
            prices.append(r["price_inr"])
        if r["price_per_sqft"]:
            ppsf.append(r["price_per_sqft"])
    counts = defaultdict(int)
    for r in conn.execute("SELECT transaction_type, property_type, COALESCE(locality,'(unknown)') AS loc, "
                          "COUNT(*) n FROM listings WHERE status='active' GROUP BY 1,2,3"):
        counts[(r["transaction_type"], r["property_type"], r["loc"])] = r["n"]
    conn.execute("DELETE FROM market_snapshots WHERE run_id=?", (run_id,))
    for key, n in counts.items():
        prices, ppsf = groups[key]
        conn.execute("INSERT INTO market_snapshots VALUES(?,?,?,?,?,?,?,?)",
                     (run_id, taken_at, *key, n,
                      statistics.median(prices) if prices else None,
                      statistics.median(ppsf) if ppsf else None))
    conn.commit()

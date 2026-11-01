"""Write the static JSON the dashboard reads (docs/data/*.json)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

EXPORT_FIELDS = [
    "id", "source_id", "url", "property_key", "title", "transaction_type", "property_type", "category",
    "bhk", "bathrooms", "furnishing", "construction_status", "facing", "built_up_sqft", "carpet_sqft",
    "plot_sqft", "area_unit_original", "area_value_original", "price_inr", "price_max_inr", "price_per_sqft",
    "deposit_inr", "locality", "locality_raw", "zone", "pincode", "latitude", "longitude", "geo_precision",
    "posted_by", "advertiser", "project_name", "builder", "rera_id", "approvals", "posted_at",
    "first_seen_at", "first_seen_run", "last_seen_at", "images", "amenities",
]


def _dump(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")


def export_all(conn, out_dir="docs/data"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    last_run = conn.execute("SELECT * FROM runs WHERE finished_at IS NOT NULL OR status='running' "
                            "ORDER BY id DESC LIMIT 1").fetchone()

    # previous price per listing, for "price dropped" flags
    prev_price = {}
    for r in conn.execute("""SELECT listing_id, price_inr FROM (
            SELECT listing_id, price_inr, ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY run_id DESC) rn
            FROM price_history) WHERE rn=2"""):
        prev_price[r["listing_id"]] = r["price_inr"]

    first_run = last_run is not None and conn.execute(
        "SELECT COUNT(*) FROM runs WHERE id<?", (last_run["id"],)).fetchone()[0] == 0
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM sources")}
    listings = []
    clusters = defaultdict(list)
    for r in conn.execute(f"SELECT {','.join(EXPORT_FIELDS)} FROM listings WHERE status='active'"):
        d = {k: r[k] for k in EXPORT_FIELDS if r[k] not in (None, "", "[]")}
        for k in ("approvals", "images", "amenities"):
            if k in d:
                d[k] = json.loads(d[k])
        d["source_name"] = names.get(d["source_id"], d["source_id"])
        if last_run and not first_run and d.get("first_seen_run") == last_run["id"]:
            d["is_new"] = True  # nothing is "new" on the very first run
        pp = prev_price.get(d["id"])
        # a >50% "cut" is almost always a re-used id or a misparse, not a real price drop
        if pp and d.get("price_inr") and pp * 0.5 <= d["price_inr"] < pp:
            d["previous_price_inr"] = pp
        listings.append(d)
        clusters[d.get("property_key")].append(d)

    for group in clusters.values():
        if len(group) > 1:
            alts = [{"id": g["id"], "source": g["source_name"], "url": g.get("url"), "price_inr": g.get("price_inr")}
                    for g in group]
            for g in group:
                g["also_listed_on"] = [a for a in alts if a["id"] != g["id"]]

    projects = [dict(r) for r in conn.execute(
        "SELECT rera_id,name,promoter,project_type,locality,address,latitude,longitude,geo_precision,"
        "registered_on,completion_date,url FROM projects")]

    source_status = []
    for s in conn.execute("SELECT * FROM sources ORDER BY id"):
        last = conn.execute("SELECT sr.*, r.started_at FROM source_runs sr JOIN runs r ON r.id=sr.run_id "
                            "WHERE source_id=? ORDER BY run_id DESC LIMIT 1", (s["id"],)).fetchone()
        active = conn.execute("SELECT COUNT(*) FROM listings WHERE source_id=? AND status='active'",
                              (s["id"],)).fetchone()[0]
        source_status.append({
            "id": s["id"], "name": s["name"], "kind": s["kind"], "enabled": bool(s["enabled"]),
            "active_listings": active,
            "last_status": last["status"] if last else None, "last_records": last["records"] if last else None,
            "last_run_at": last["started_at"] if last else None, "message": last["message"] if last else None,
        })

    trend = []
    for r in conn.execute("""SELECT run_id, taken_at, transaction_type, SUM(active_count) n
                             FROM market_snapshots GROUP BY run_id, transaction_type ORDER BY run_id"""):
        if not trend or trend[-1]["run_id"] != r["run_id"]:
            trend.append({"run_id": r["run_id"], "taken_at": r["taken_at"], "sale": 0, "rent": 0, "lease": 0})
        trend[-1][r["transaction_type"] or "sale"] = r["n"]

    expired_last_run = 0
    if last_run:
        expired_last_run = conn.execute("SELECT COALESCE(SUM(expired),0) FROM source_runs WHERE run_id=?",
                                        (last_run["id"],)).fetchone()[0]

    _dump(out / "listings.json", listings)
    _dump(out / "projects.json", projects)
    _dump(out / "meta.json", {
        "generated_at": last_run["finished_at"] or last_run["started_at"] if last_run else None,
        "run_id": last_run["id"] if last_run else None,
        "run_status": last_run["status"] if last_run else None,
        "active_listings": len(listings),
        "expired_last_run": expired_last_run,
        "sources": source_status,
        "trend": trend,
    })
    return len(listings)

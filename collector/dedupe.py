"""Cluster the same physical property advertised on several portals.

Two adverts are treated as one property when they agree on transaction, type,
locality and BHK, and their area and price fall in the same narrow log-buckets
(about +/-2.5% area, +/-4% price). Deliberately conservative: a missed merge just
shows a duplicate; a wrong merge would hide a real listing.
"""
from __future__ import annotations

import hashlib
import math


def _bucket(v, pct):
    if not v or v <= 0:
        return None
    return round(math.log(v) / math.log(1 + pct))


def property_key(rec: dict) -> str:
    area = rec.get("built_up_sqft") or rec.get("plot_sqft") or rec.get("carpet_sqft")
    parts = [
        rec.get("transaction_type"), rec.get("property_type"), rec.get("locality") or rec.get("locality_raw"),
        rec.get("bhk"), _bucket(area, 0.05), _bucket(rec.get("price_inr"), 0.08),
    ]
    if parts[2] is None or (parts[4] is None and parts[5] is None):
        # too little information to safely merge - keep it unique
        return "u:" + rec["source_id"] + ":" + rec["source_listing_id"]
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]

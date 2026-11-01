"""Geocoding fallback for listings whose locality isn't in the bundled gazetteer.

Uses OpenStreetMap Nominatim (max 1 req/s, results cached in SQLite forever),
so after the first few runs almost nothing is looked up again.
"""
from __future__ import annotations

import logging
import time

import requests

from . import normalize as N
from .db import now_iso

log = logging.getLogger(__name__)
NOMINATIM = "https://nominatim.openstreetmap.org/search"


class Geocoder:
    def __init__(self, conn, enabled: bool = True, max_lookups: int = 300, user_agent: str = ""):
        self.conn = conn
        self.enabled = enabled
        self.budget = max_lookups
        self.ua = user_agent or "CoimbatoreRealEstateIndex/1.0"
        self._last = 0.0

    def lookup(self, place: str):
        q = N.clean_text(place)
        if not q:
            return None
        q = q.lower()
        row = self.conn.execute("SELECT latitude, longitude FROM geocode_cache WHERE query=?", (q,)).fetchone()
        if row:
            return (row["latitude"], row["longitude"]) if row["latitude"] is not None else None
        if not self.enabled or self.budget <= 0:
            return None
        self.budget -= 1
        wait = 1.1 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        lat = lng = name = None
        try:
            r = requests.get(NOMINATIM, timeout=20, headers={"User-Agent": self.ua}, params={
                "q": f"{place}, Coimbatore, Tamil Nadu, India", "format": "json", "limit": 1,
                "countrycodes": "in",
                "viewbox": f"{N.CBE_BBOX[1]},{N.CBE_BBOX[2]},{N.CBE_BBOX[3]},{N.CBE_BBOX[0]}", "bounded": 1,
            })
            r.raise_for_status()
            hits = r.json()
            if hits:
                lat, lng, name = float(hits[0]["lat"]), float(hits[0]["lon"]), hits[0].get("display_name")
                if not N.in_coimbatore(lat, lng):
                    lat = lng = None
        except (requests.RequestException, ValueError) as e:
            log.warning("geocode %r failed: %s", place, e)
            return None  # don't cache transient failures
        self.conn.execute("INSERT OR REPLACE INTO geocode_cache VALUES(?,?,?,?,?)", (q, lat, lng, name, now_iso()))
        return (lat, lng) if lat is not None else None

    def fill(self, rec: dict) -> dict:
        if rec.get("latitude") is not None:
            return rec
        for place in (rec.get("locality_raw"), rec.get("address")):
            hit = self.lookup(place) if place else None
            if hit:
                rec["latitude"], rec["longitude"], rec["geo_precision"] = hit[0], hit[1], "locality"
                break
        return rec

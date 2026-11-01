"""Connector contract + the one place loose records become schema rows.

A connector yields *loose* dicts - whatever keys it could find. Recognised keys:

    id, url, title, description, price, price_max, deposit, maintenance,
    area, area_unit, carpet_area, plot_area, bhk, bathrooms, floor, total_floors,
    locality, address, pincode, lat, lng, property_type, transaction, posted_by,
    advertiser, project, builder, furnishing, status, posted_at, images, amenities, rera

`build_listing` turns that into a row matching `db.LISTING_FIELDS`.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterator
from urllib.parse import urlparse, urlunparse

from .. import normalize as N


class Source:
    kind = "base"

    def __init__(self, sid: str, cfg: dict, fetcher):
        self.id = sid
        self.cfg = cfg
        self.fetcher = fetcher
        self.name = cfg.get("name", sid)
        self.base_url = cfg.get("base_url")

    def collect(self) -> Iterator[dict]:
        raise NotImplementedError


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    p = urlparse(url)
    return urlunparse((p.scheme or "https", p.netloc.lower(), p.path.rstrip("/"), "", "", ""))


def listing_id(source_id: str, source_listing_id: str) -> str:
    return hashlib.sha1(f"{source_id}:{source_listing_id}".encode()).hexdigest()[:16]


def _first(*vals):
    for v in vals:
        if v not in (None, "", [], {}):
            return v
    return None


def build_listing(raw: dict, source_id: str, defaults: dict | None = None) -> dict | None:
    """Normalise one loose record. Returns None if it is not a usable Coimbatore listing."""
    d = defaults or {}
    title = N.clean_text(raw.get("title"))
    desc = N.clean_text(raw.get("description"))
    text = " ".join(filter(None, [title, desc, N.clean_text(raw.get("property_type")),
                                   N.clean_text(raw.get("status"))]))

    url = canonical_url(raw.get("url"))
    sl_id = _first(raw.get("id"), url)
    if not sl_id:
        basis = f"{title}|{raw.get('price')}|{raw.get('locality')}|{raw.get('area')}"
        sl_id = "h:" + hashlib.sha1(basis.encode()).hexdigest()[:12]
    sl_id = str(sl_id)

    transaction = N.detect_transaction(N.clean_text(raw.get("transaction")), default=None) \
        or N.detect_transaction(text, default=d.get("transaction"))
    ptype = N.detect_property_type(N.clean_text(raw.get("property_type")))
    if ptype == "other":
        ptype = N.detect_property_type(title, desc)
    if ptype == "other" and d.get("property_type"):
        ptype = d["property_type"]

    price, price_max = N.parse_inr(raw.get("price"))
    if raw.get("price_max") is not None:
        price_max = N.parse_inr(raw.get("price_max"))[0] or price_max
    if price is None and title:
        price, price_max = N.parse_inr(_money_fragment(title))

    # Area: built-up for buildings, plot for land
    built, unit, unit_val = N.parse_area(raw.get("area"), raw.get("area_unit"))
    plot, punit, punit_val = N.parse_area(raw.get("plot_area"), raw.get("area_unit"))
    carpet, _, _ = N.parse_area(raw.get("carpet_area"), raw.get("area_unit"))
    if built is None and plot is None:
        found = N.find_areas(" ".join(filter(None, [title, desc])))
        if found:
            built, unit, unit_val = found[0]
    land_types = {"plot", "agricultural_land", "commercial_land"}
    if ptype in land_types and plot is None and built is not None:
        plot, punit, punit_val, built = built, unit, unit_val, None
    area_for_rate = built or carpet or plot
    orig_unit, orig_val = (punit, punit_val) if plot and ptype in land_types else (unit, unit_val)

    ppsf = None
    if price and area_for_rate and transaction == "sale":
        ppsf = round(price / area_for_rate, 1)
        if not 100 <= ppsf <= 100000:  # implausible -> one of the inputs was misparsed
            ppsf = None

    loc = N.match_locality(raw.get("locality"), raw.get("address"), title, desc)
    lat, lng = _num(raw.get("lat")), _num(raw.get("lng"))
    if N.in_coimbatore(lat, lng):
        geo_precision = "exact"
    else:
        lat = lng = None
        geo_precision = None
    if lat is None and loc:
        lat, lng, geo_precision = loc.lat, loc.lng, "locality"

    # Scope guard: must be in Coimbatore by coordinates, gazetteer, or explicit mention.
    mentions_cbe = bool(re.search(r"coimbatore|kovai", " ".join(
        str(x) for x in (raw.get("address"), raw.get("locality"), raw.get("city"), title, desc) if x), re.I))
    if not (geo_precision or mentions_cbe or d.get("city_scoped")):
        return None
    if not (price or title):
        return None

    images = raw.get("images") or []
    if isinstance(images, str):
        images = [images]
    amenities = raw.get("amenities") or []
    if isinstance(amenities, str):
        amenities = [a.strip() for a in re.split(r"[,|;]", amenities) if a.strip()]

    return {
        "source_id": source_id,
        "source_listing_id": sl_id,
        "url": url or raw.get("url"),
        "title": title,
        "description": desc[:2000] if desc else None,
        "transaction_type": transaction or "sale",
        "property_type": ptype,
        "category": N.category_for(ptype),
        "bhk": N.parse_bhk(raw.get("bhk"), title, desc) if ptype not in land_types else None,
        "bathrooms": N.parse_int(raw.get("bathrooms")),
        "furnishing": N.detect_furnishing(raw.get("furnishing")) or N.detect_furnishing(text),
        "construction_status": N.detect_construction_status(raw.get("status"), text),
        "facing": N.detect_facing(raw.get("facing"), text),
        "floor": N.parse_int(raw.get("floor")),
        "total_floors": N.parse_int(raw.get("total_floors")),
        "built_up_sqft": built,
        "carpet_sqft": carpet,
        "plot_sqft": plot,
        "area_unit_original": orig_unit,
        "area_value_original": orig_val,
        "price_inr": price,
        "price_max_inr": price_max,
        "price_per_sqft": ppsf,
        "deposit_inr": N.parse_inr(raw.get("deposit"))[0],
        "maintenance_inr": N.parse_inr(raw.get("maintenance"))[0],
        "locality": loc.name if loc else None,
        "locality_raw": N.clean_text(raw.get("locality")),
        "zone": loc.zone if loc else None,
        "address": N.clean_text(raw.get("address")),
        "pincode": _pincode(raw.get("pincode"), raw.get("address"), desc),
        "latitude": lat,
        "longitude": lng,
        "geo_precision": geo_precision or "none",
        "posted_by": N.detect_posted_by(raw.get("posted_by")) or None,
        "advertiser": N.clean_text(raw.get("advertiser")),
        "project_name": N.clean_text(raw.get("project")),
        "builder": N.clean_text(raw.get("builder")),
        "rera_id": N.find_rera_id(raw.get("rera"), text),
        "approvals": N.detect_approvals(raw.get("rera"), text),
        "amenities": amenities[:40],
        "images": [i for i in images if isinstance(i, str)][:8],
        "posted_at": N.clean_text(raw.get("posted_at")),
        "raw": raw,
    }


def _money_fragment(title: str) -> str:
    m = re.search(r"(₹|rs\.?|inr)\s*[\d.,]+\s*(cr|crore|lakhs?|lacs?|l|k)?", title, re.I)
    return m.group() if m else ""


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _pincode(*texts):
    for t in texts:
        if t:
            m = re.search(r"\b64[12]\s?\d{3}\b", str(t))
            if m:
                return m.group().replace(" ", "")
    return None

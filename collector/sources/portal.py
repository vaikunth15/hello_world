"""Generic listing-portal connector.

Rather than hard-coding each portal's HTML (which changes monthly), it reads the
*structured data* most portals embed for SEO and for their own front-end:

1. schema.org JSON-LD blocks (<script type="application/ld+json">)
2. Front-end state JSON (__NEXT_DATA__, window.__INITIAL_STATE__ = {...}, etc.)
3. Optional per-source CSS selectors from sources.yaml, for sites that embed neither.

Strategy 2 walks the JSON tree and keeps any object that *looks like* a listing
(has a price-ish key plus a title/locality/url-ish key), mapping keys by synonym.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Blocked
from .base import Source

log = logging.getLogger(__name__)

# loose-record key -> lowercase key synonyms seen across portals
SYNONYMS: dict[str, tuple[str, ...]] = {
    "id": ("id", "propertyid", "propid", "listingid", "propertycode", "adid", "spid", "propertyidentifier"),
    "url": ("url", "propertyurl", "detailurl", "pdpurl", "seourl", "link", "href", "canonicalurl", "inventoryurl"),
    "title": ("title", "name", "propertytitle", "heading", "seotitle", "propname", "displayname", "listingtitle"),
    "description": ("description", "desc", "propertydescription", "summary", "about", "propdesc"),
    "price": ("price", "expectedprice", "pricevalue", "priceinr", "listingprice", "formattedprice", "pricestr",
              "rent", "monthlyrent", "rentamount", "minprice", "displayprice", "amount", "pricerange"),
    "price_max": ("maxprice", "pricemax"),
    "deposit": ("deposit", "securitydeposit"),
    "maintenance": ("maintenance", "maintenancecharges", "maintenancecharge"),
    "area": ("area", "builtuparea", "superbuiltuparea", "superarea", "covered_area", "coveredarea", "size",
             "floorsize", "sqft", "areavalue", "builtup", "displayarea"),
    "area_unit": ("areaunit", "unit", "sizeunit", "unitcode", "unittext"),
    "carpet_area": ("carpetarea",),
    "plot_area": ("plotarea", "landarea", "plotsize"),
    "bhk": ("bhk", "bedrooms", "bedroom", "numberofrooms", "numberofbedrooms", "bedroomcount", "noofbedrooms", "beds"),
    "bathrooms": ("bathrooms", "bathroom", "numberofbathroomstotal", "noofbathrooms", "baths"),
    "floor": ("floor", "floorno", "floornumber"),
    "total_floors": ("totalfloors", "totalfloor", "floorcount"),
    "locality": ("locality", "localityname", "addresslocality", "location", "area_name", "areaname",
                 "sublocality", "localitylabel", "locname"),
    "address": ("address", "streetaddress", "fulladdress", "displayaddress"),
    "city": ("city", "cityname", "addressregion"),
    "pincode": ("pincode", "postalcode", "zipcode"),
    "lat": ("lat", "latitude"),
    "lng": ("lng", "lon", "long", "longitude"),
    "property_type": ("propertytype", "proptype", "type", "category", "propertytypename", "unittype", "subtype"),
    "transaction": ("transactiontype", "listingtype", "dealtype", "purpose", "servicetype"),
    "posted_by": ("postedby", "listedby", "usertype", "sellertype", "postedbytype", "ownertype"),
    "advertiser": ("advertiser", "sellername", "agentname", "ownername", "brokername", "contactname", "companyname"),
    "project": ("project", "projectname", "society", "societyname", "buildingname"),
    "builder": ("builder", "buildername", "developer", "developername"),
    "furnishing": ("furnishing", "furnishingstatus", "furnished"),
    "status": ("possessionstatus", "constructionstatus", "availability", "status", "propertystatus"),
    "posted_at": ("posteddate", "postedon", "createdat", "datecreated", "dateposted", "updatedat", "datemodified"),
    "images": ("images", "image", "photos", "imageurl", "thumbnail", "thumbnailurl", "coverimage"),
    "amenities": ("amenities", "features", "amenitieslist"),
    "rera": ("rera", "reraid", "reranumber", "reraregistrationnumber"),
}
_KEYMAP = {syn: field for field, syns in SYNONYMS.items() for syn in syns}
_PRICE_KEYS = set(SYNONYMS["price"])
_ID_KEYS = set(SYNONYMS["title"]) | set(SYNONYMS["locality"]) | set(SYNONYMS["url"])

LD_TYPES = {"product", "offer", "residence", "apartment", "house", "singlefamilyresidence", "realestatelisting",
            "accommodation", "apartmentcomplex", "place", "landform", "suite", "room", "localbusiness"}

_STATE_RX = re.compile(r"window\.(__[A-Z0-9_]+__|[a-zA-Z_$][\w$]*State\w*)\s*=\s*", re.S)


def _k(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _scalar(v):
    """Reduce nested values ({value: 3}, {displayValue: '85 L'}, [..]) to something usable."""
    if isinstance(v, dict):
        for k in ("displayValue", "value", "formatted", "label", "text", "name", "url", "price", "amount"):
            if k in v and not isinstance(v[k], (dict, list)):
                return v[k]
        return None
    return v


def map_object(obj: dict) -> dict:
    out: dict = {}
    for key, val in obj.items():
        field = _KEYMAP.get(_k(key))
        if not field or field in out:
            continue
        if field in ("images", "amenities"):
            if isinstance(val, list):
                out[field] = [(_scalar(x) if isinstance(x, dict) else x) for x in val]
            elif val:
                out[field] = [_scalar(val)]
            continue
        if field == "address" and isinstance(val, dict):
            out["address"] = ", ".join(str(val[k]) for k in ("streetAddress", "addressLocality", "addressRegion",
                                                              "postalCode") if val.get(k))
            out.setdefault("locality", val.get("addressLocality"))
            out.setdefault("pincode", val.get("postalCode"))
            continue
        sv = _scalar(val)
        if sv not in (None, "", []) and not isinstance(sv, (dict, list)):
            out[field] = sv
    # nested geo / offers / floorSize (schema.org)
    geo = next((g for g in (obj.get("geo"), obj.get("location"), obj.get("coordinates")) if isinstance(g, dict)), None)
    if geo:
        out.setdefault("lat", geo.get("latitude") or geo.get("lat"))
        out.setdefault("lng", geo.get("longitude") or geo.get("lng") or geo.get("lon"))
    offers = obj.get("offers")
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        out.setdefault("price", offers.get("price") or offers.get("lowPrice"))
        if offers.get("highPrice"):
            out.setdefault("price_max", offers.get("highPrice"))
        out.setdefault("url", offers.get("url"))
    fs = obj.get("floorSize")
    if isinstance(fs, dict):
        out["area"] = fs.get("value")
        unit = (fs.get("unitText") or fs.get("unitCode") or "").lower()
        out["area_unit"] = {"ftk": "sqft", "sqft": "sqft", "mtk": "sqm", "sqm": "sqm"}.get(unit, out.get("area_unit"))
    if out.get("area_unit"):
        out["area_unit"] = _unit_name(str(out["area_unit"]))
    return out


def _unit_name(u: str) -> str | None:
    u = u.lower()
    for name, keys in (("sqft", ("ft", "sft")), ("sqyd", ("yd", "yard")), ("sqm", ("sqm", "meter", "metre", "mtk")),
                       ("cent", ("cent",)), ("acre", ("acre",)), ("ground", ("ground",))):
        if any(k in u for k in keys):
            return name
    return None


def looks_like_listing(obj: dict) -> bool:
    keys = {_k(k) for k in obj}
    return bool(keys & _PRICE_KEYS) and bool(keys & _ID_KEYS) and len(keys & set(_KEYMAP)) >= 3


def walk(node, depth=0) -> Iterator[dict]:
    if depth > 25:
        return
    if isinstance(node, dict):
        if looks_like_listing(node):
            yield node
            return
        for v in node.values():
            yield from walk(v, depth + 1)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v, depth + 1)


def _balanced_json(text: str, start: int):
    """Parse the JSON object/array beginning at text[start]."""
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj
    except ValueError:
        return None


def extract_jsonld(soup: BeautifulSoup) -> list[dict]:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "null")
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            if "@graph" in node:
                stack.extend(node["@graph"])
            if "itemListElement" in node:
                for el in node["itemListElement"] or []:
                    stack.append(el.get("item", el) if isinstance(el, dict) else el)
            types = node.get("@type") or []
            types = {t.lower() for t in (types if isinstance(types, list) else [types]) if isinstance(t, str)}
            if types & LD_TYPES and (node.get("offers") or node.get("price") or node.get("floorSize")):
                out.append(map_object(node))
    return out


def extract_embedded_state(html: str, soup: BeautifulSoup) -> list[dict]:
    blobs = []
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd and nd.string:
        try:
            blobs.append(json.loads(nd.string))
        except ValueError:
            pass
    for m in _STATE_RX.finditer(html):
        i = m.end()
        if i < len(html) and html[i] in "{[":
            obj = _balanced_json(html, i)
            if obj is not None:
                blobs.append(obj)
    out = []
    for b in blobs:
        out.extend(map_object(o) for o in walk(b))
    return out


def extract_css(soup: BeautifulSoup, sel: dict, page_url: str) -> list[dict]:
    out = []
    for card in soup.select(sel["card"]):
        rec = {}
        for field, css in sel.get("fields", {}).items():
            attr = None
            if "@" in css:
                css, attr = css.rsplit("@", 1)
            el = card.select_one(css) if css else card
            if el is None:
                continue
            rec[field] = el.get(attr) if attr else el.get_text(" ", strip=True)
        if rec.get("url"):
            rec["url"] = urljoin(page_url, rec["url"])
        out.append(rec)
    return out


def extract_page(html: str, page_url: str, css: dict | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    recs = extract_jsonld(soup) + extract_embedded_state(html, soup)
    if css:
        recs += extract_css(soup, css, page_url)
    for r in recs:
        if r.get("url"):
            r["url"] = urljoin(page_url, str(r["url"]))
    # merge duplicates of the same listing found by different strategies
    merged: dict[str, dict] = {}
    for r in recs:
        key = str(r.get("id") or r.get("url") or (r.get("title"), r.get("price")))
        if key in merged:
            for k, v in r.items():
                merged[key].setdefault(k, v)
        else:
            merged[key] = r
    return list(merged.values())


class PortalSource(Source):
    kind = "portal"

    def collect(self) -> Iterator[dict]:
        max_pages = int(self.cfg.get("max_pages", 30))
        for search in self.cfg.get("searches", []):
            seen_page_keys: set[str] = set()
            for page in range(1, max_pages + 1):
                url = search["url"] if page == 1 else search.get("page_url", search["url"]).format(page=page)
                try:
                    resp = self.fetcher.get(url)
                except Blocked:
                    if page == 1:
                        raise
                    break
                recs = extract_page(resp.text, url, self.cfg.get("css"))
                keys = {str(r.get("id") or r.get("url") or r.get("title")) for r in recs}
                if not recs or keys <= seen_page_keys:
                    break  # ran past the last page (or site repeats the final page)
                seen_page_keys |= keys
                log.info("%s %s page %d: %d records", self.id, search.get("label", ""), page, len(recs))
                for r in recs:
                    r.setdefault("_defaults", {k: search[k] for k in ("transaction", "property_type") if k in search})
                    yield r

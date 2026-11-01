"""Tamil Nadu RERA registered projects (Coimbatore district).

TN RERA publishes registered Building/Layout projects as HTML tables, one page per
year/type. Rather than depending on exact column order, headers are matched by
keyword and rows are kept when they mention Coimbatore. Page URLs live in
sources.yaml so they can be corrected without touching code.
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import normalize as N
from .base import Source

HEADER_KEYS = {
    "rera_id": ("registration no", "reg. no", "reg no", "registration number", "rera no", "rera number"),
    "name": ("project name", "name of the project", "project"),
    "promoter": ("promoter", "developer", "builder", "applicant"),
    "address": ("address", "location", "site", "survey no", "village"),
    "district": ("district",),
    "registered_on": ("date of registration", "registration date", "approved on", "date of approval", "reg. date"),
    "completion_date": ("completion", "valid upto", "validity", "end date"),
}


def _map_headers(headers: list[str]) -> dict[int, str]:
    out = {}
    for i, h in enumerate(headers):
        h = h.lower()
        for field, keys in HEADER_KEYS.items():
            if field not in out.values() and any(k in h for k in keys):
                out[i] = field
                break
    return out


def parse_tables(html: str, page_url: str, project_type: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        cols = _map_headers(headers)
        if not cols:
            continue
        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            texts = [c.get_text(" ", strip=True) for c in cells]
            row_text = " ".join(texts)
            if not re.search(r"coimbatore|kovai", row_text, re.I):
                continue
            rec = {field: texts[i] for i, field in cols.items() if i < len(texts)}
            rec["rera_id"] = N.find_rera_id(rec.get("rera_id"), row_text) or rec.get("rera_id")
            if not rec.get("rera_id"):
                continue
            link = tr.find("a", href=True)
            rec["url"] = urljoin(page_url, link["href"]) if link else page_url
            rec["project_type"] = project_type or ("Layout" if "/Layout/" in rec["rera_id"] else "Building")
            rec["raw"] = dict(zip(headers, texts))
            out.append(rec)
    return out


class TnReraSource(Source):
    kind = "rera"

    def collect(self) -> Iterator[dict]:
        errors, ok = [], 0
        for page in self.cfg.get("pages", []):
            try:
                resp = self.fetcher.get(page["url"])
            except Exception as e:  # noqa: BLE001 - a missing year page shouldn't stop the rest
                errors.append(f"{page['url']}: {e}")
                continue
            ok += 1
            for rec in parse_tables(resp.text, page["url"], page.get("project_type")):
                loc = N.match_locality(rec.get("address"), rec.get("name"))
                rec["locality"] = loc.name if loc else None
                rec["latitude"], rec["longitude"] = (loc.lat, loc.lng) if loc else (None, None)
                rec["geo_precision"] = "locality" if loc else "none"
                yield rec
        if not ok and errors:
            raise RuntimeError("no RERA page could be fetched; " + " | ".join(errors[:3]))

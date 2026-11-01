"""CSV / Google-Sheet feed connector.

The dependable path for data you are *allowed* to use: broker inventories,
builder price lists, a partner API export, or a shared Google Sheet
(File -> Share -> Publish to web -> CSV gives a URL).

Columns are mapped to loose-record keys via `columns:` in sources.yaml; any
column already named like a loose key (title, price, area, locality...) maps itself.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Iterator

from .base import Source


class CsvSource(Source):
    kind = "csv"

    def collect(self) -> Iterator[dict]:
        loc = self.cfg["path"]
        if loc.startswith(("http://", "https://")):
            text = self.fetcher.get(loc).text
        else:
            p = Path(loc)
            if not p.exists():
                return
            text = p.read_text(encoding="utf-8-sig")
        colmap = {v: k for k, v in (self.cfg.get("columns") or {}).items()}  # csv header -> loose key
        for row in csv.DictReader(io.StringIO(text)):
            rec = {}
            for header, value in row.items():
                if header is None:
                    continue
                key = colmap.get(header, header.strip().lower().replace(" ", "_"))
                if value not in (None, ""):
                    rec[key] = value.strip()
            if rec:
                rec["_defaults"] = {"city_scoped": True, **(self.cfg.get("defaults") or {})}
                yield rec

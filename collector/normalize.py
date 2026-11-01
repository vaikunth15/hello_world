"""Turn messy listing text into normalized values.

Everything here is pure (no I/O) so it is easy to unit-test.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# ---------------------------------------------------------------- enums

PROPERTY_TYPES = {
    # type: category
    "apartment": "residential",
    "independent_house": "residential",
    "villa": "residential",
    "plot": "residential",
    "pg_hostel": "residential",
    "farm_house": "agricultural",
    "agricultural_land": "agricultural",
    "commercial_office": "commercial",
    "commercial_shop": "commercial",
    "commercial_land": "commercial",
    "warehouse": "industrial",
    "industrial": "industrial",
    "other": "other",
}

TRANSACTION_TYPES = ("sale", "rent", "lease")

# Ordered: the first matching rule wins, so specific phrases come before generic ones.
_TYPE_RULES: list[tuple[str, str]] = [
    ("commercial_land", r"commercial (land|plot|site)"),
    ("industrial", r"industrial (land|plot|shed|building)|factory|\bshed\b|manufacturing unit"),
    ("warehouse", r"warehouse|godown|go-down|storage space|cold storage"),
    ("farm_house", r"farm ?house"),
    ("agricultural_land", r"agri(cultural)? ?land|farm ?land|agricultural|coconut (farm|grove|thope|land)|thottam|\bacres? of land\b"),
    ("pg_hostel", r"\bpg\b|paying guest|hostel|co-?living"),
    ("commercial_office", r"office space|\boffice\b|co-?working|it space|it park space|business cent(er|re)"),
    ("commercial_shop", r"\bshop\b|showroom|retail space|commercial (space|building|property|complex)|restaurant space|hotel"),
    ("villa", r"\bvillas?\b|row ?house|twin house"),
    ("apartment", r"\bflats?\b|apartment|\bstudio\b|penthouse|\bbhk flat\b|condo"),
    ("plot", r"\bplots?\b|residential land|\bland\b|\bsite\b|dtcp|layout|\bcents?\b"),
    ("independent_house", r"independent house|individual house|\bhouse\b|bungalow|duplex|builder floor|\bhome\b|kothi"),
]

_TYPE_REGEX = [(t, re.compile(p, re.I)) for t, p in _TYPE_RULES]


def detect_property_type(*texts: str | None) -> str:
    blob = " ".join(t for t in texts if t)
    for ptype, rx in _TYPE_REGEX:
        if rx.search(blob):
            return ptype
    return "other"


def category_for(ptype: str) -> str:
    return PROPERTY_TYPES.get(ptype, "other")


def detect_transaction(*texts: str | None, default: str | None = None) -> str | None:
    blob = " ".join(t for t in texts if t).lower()
    if re.search(r"\blease\b", blob) and not re.search(r"\b(for )?sale\b", blob):
        return "lease"
    if re.search(r"\bfor rent\b|\brent(al)?\b|/ ?month|per month|\bpm\b|\bto-let\b|\bto let\b", blob):
        return "rent"
    if re.search(r"\bsale\b|\bresale\b|\bbuy\b|\bsell", blob):
        return "sale"
    return default


# ---------------------------------------------------------------- money

_UNIT_MULT = {
    "cr": 1e7, "crore": 1e7, "crores": 1e7, "c": 1e7,
    "l": 1e5, "lac": 1e5, "lacs": 1e5, "lakh": 1e5, "lakhs": 1e5, "lk": 1e5,
    "k": 1e3, "thousand": 1e3,
}
_NUM = r"(\d+(?:,\d+)*(?:\.\d+)?)"
_MONEY_RX = re.compile(
    _NUM + r"\s*(crores?|cr|lakhs?|lacs?|lac|lk|l|k|thousand)?\b\.?",
    re.I,
)


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


def parse_inr(value) -> tuple[int | None, int | None]:
    """Parse an Indian price into (min, max) rupees.

    Handles: 8500000, "₹ 85 Lac", "1.2 Cr", "45 - 60 Lakhs", "Rs.45,00,000",
    "₹25,000/month", "25K". Unparseable/"on request" -> (None, None).
    """
    if value is None:
        return None, None
    if isinstance(value, (int, float)):
        return (int(value), None) if value > 0 else (None, None)
    text = str(value).replace("₹", " ").replace("Rs.", " ").replace("Rs", " ").replace("INR", " ")
    text = text.replace("\xa0", " ")
    if re.search(r"on request|call for price|price on|negotiable only", text, re.I) and not re.search(r"\d", text):
        return None, None
    found = []
    for m in _MONEY_RX.finditer(text):
        num, unit = m.group(1), (m.group(2) or "").lower()
        try:
            amount = _to_float(num)
        except ValueError:
            continue
        found.append([amount, unit])
    if not found:
        return None, None
    # "45 - 60 Lakhs": unit applies to both ends
    if len(found) >= 2 and not found[0][1] and found[1][1]:
        found[0][1] = found[1][1]
    vals = []
    for amount, unit in found[:2]:
        mult = _UNIT_MULT.get(unit, 1)
        vals.append(int(round(amount * mult)))
    vals = [v for v in vals if v >= 1000]  # ignore stray small numbers ("2 BHK")
    if not vals:
        return None, None
    lo = min(vals)
    hi = max(vals) if len(vals) > 1 and max(vals) != lo else None
    return lo, hi


# ---------------------------------------------------------------- area

SQFT_PER = {
    "sqft": 1.0,
    "sqyd": 9.0,
    "sqm": 10.7639,
    "cent": 435.6,       # Very common in Coimbatore / Kerala belt
    "acre": 43560.0,
    "ground": 2400.0,    # Tamil Nadu unit
    "hectare": 107639.0,
    "guntha": 1089.0,
}

_AREA_UNIT_RX = [
    ("sqft", r"sq\.?\s*f(ee)?t\.?|sqft|sft|square\s*f(ee|oo)t|ft2|ft²"),
    ("sqyd", r"sq\.?\s*y(ar)?ds?\.?|sqyd|square\s*yards?|gaj"),
    ("sqm", r"sq\.?\s*m(eters?|tr?s?)?\b\.?|sqm|square\s*met(er|re)s?|m2|m²"),
    ("cent", r"cents?\b"),
    ("acre", r"acres?\b"),
    ("ground", r"grounds?\b"),
    ("hectare", r"hectares?\b"),
    ("guntha", r"gunthas?\b|guntas?\b"),
]
_AREA_RX = re.compile(
    _NUM + r"\s*(" + "|".join(f"(?P<{u}>{p})" for u, p in _AREA_UNIT_RX) + ")",
    re.I,
)


def parse_area(value, default_unit: str | None = None) -> tuple[float | None, str | None, float | None]:
    """Return (sqft, unit, raw_value). "5 cents" -> (2178.0, "cent", 5.0)."""
    if value is None:
        return None, None, None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None, None, None
        unit = default_unit or "sqft"
        return round(value * SQFT_PER[unit], 1), unit, float(value)
    m = _AREA_RX.search(str(value))
    if not m:
        if default_unit:
            nm = re.search(_NUM, str(value))
            if nm:
                return parse_area(_to_float(nm.group(1)), default_unit)
        return None, None, None
    raw = _to_float(m.group(1))
    unit = next(u for u, _ in _AREA_UNIT_RX if m.group(u))
    if raw <= 0:
        return None, None, None
    return round(raw * SQFT_PER[unit], 1), unit, raw


def find_areas(text: str) -> list[tuple[float, str, float]]:
    out = []
    for m in _AREA_RX.finditer(text or ""):
        unit = next(u for u, _ in _AREA_UNIT_RX if m.group(u))
        raw = _to_float(m.group(1))
        if raw > 0:
            out.append((round(raw * SQFT_PER[unit], 1), unit, raw))
    return out


# ---------------------------------------------------------------- misc fields

def parse_bhk(*texts) -> float | None:
    for t in texts:
        if t is None:
            continue
        if isinstance(t, (int, float)) and 0 < t < 20:
            return float(t)
        m = re.search(r"(\d+(?:\.5)?)\s*(bhk|rk|bed(room)?s?|br)\b", str(t), re.I)
        if m:
            v = float(m.group(1))
            if m.group(2).lower() == "rk":
                v = 0.5 if v == 1 else v
            if 0 < v < 20:
                return v
    return None


def parse_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else None


def detect_furnishing(*texts) -> str | None:
    blob = " ".join(str(t) for t in texts if t).lower()
    if re.search(r"semi[- ]?furnished", blob):
        return "semi_furnished"
    if re.search(r"un[- ]?furnished|not furnished", blob):
        return "unfurnished"
    if re.search(r"fully[- ]?furnished|\bfurnished\b", blob):
        return "furnished"
    return None


def detect_posted_by(*texts) -> str | None:
    blob = " ".join(str(t) for t in texts if t).lower()
    if re.search(r"\bowner\b|individual", blob):
        return "owner"
    if re.search(r"builder|developer|promoter", blob):
        return "builder"
    if re.search(r"agent|broker|dealer|realtor|consultant|realty", blob):
        return "agent"
    return None


def detect_construction_status(*texts) -> str | None:
    blob = " ".join(str(t) for t in texts if t).lower()
    if re.search(r"new launch|pre[- ]?launch|upcoming", blob):
        return "new_launch"
    if re.search(r"under construction|possession (by|in|from)|ongoing", blob):
        return "under_construction"
    if re.search(r"ready to move|ready for possession|immediate possession|\bready\b|resale", blob):
        return "ready"
    return None


def detect_approvals(*texts) -> list[str]:
    blob = " ".join(str(t) for t in texts if t)
    found = []
    for tag, rx in [
        ("DTCP", r"\bDTCP\b"),
        ("LPA", r"\bLPA\b|local planning authority"),
        ("CMDA", r"\bCMDA\b"),
        ("RERA", r"\bRERA\b|TN/\d+/(Building|Layout)"),
        ("Panchayat", r"panchayat approved|panchayat approval"),
        ("Corporation", r"corporation approved|ccmc approved"),
    ]:
        if re.search(rx, blob, re.I):
            found.append(tag)
    return found


_RERA_RX = re.compile(r"TN/\d{1,3}/(?:Building|Layout)/\d{1,5}/\d{4}", re.I)


def find_rera_id(*texts) -> str | None:
    for t in texts:
        if t:
            m = _RERA_RX.search(str(t))
            if m:
                return m.group().upper().replace("BUILDING", "Building").replace("LAYOUT", "Layout")
    return None


_FACING_RX = re.compile(r"\b(north|south|east|west|north[- ]?east|north[- ]?west|south[- ]?east|south[- ]?west)[- ]facing\b", re.I)


def detect_facing(*texts) -> str | None:
    for t in texts:
        if t:
            m = _FACING_RX.search(str(t))
            if m:
                return m.group(1).lower().replace(" ", "-")
    return None


def clean_text(s) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s or None


# ---------------------------------------------------------------- localities

@dataclass(frozen=True)
class Locality:
    name: str
    lat: float
    lng: float
    zone: str


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace(".", " ")).replace("  ", " ").strip()


@lru_cache(maxsize=1)
def load_localities() -> tuple[dict[str, Locality], re.Pattern]:
    index: dict[str, Locality] = {}
    with open(DATA_DIR / "localities.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            loc = Locality(row["name"], float(row["lat"]), float(row["lng"]), row["zone"])
            names = [row["name"]] + [a for a in (row["aliases"] or "").split("|") if a]
            for n in names:
                index[_norm(n)] = loc
                index[_norm(n).replace(" ", "")] = loc
    keys = sorted(index, key=len, reverse=True)
    rx = re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b")
    return index, rx


def match_locality(*texts) -> Locality | None:
    """Find the first known Coimbatore locality mentioned in the given texts (in order)."""
    index, rx = load_localities()
    for t in texts:
        if not t:
            continue
        n = _norm(str(t))
        if n in index:
            return index[n]
        m = rx.search(n)
        if m:
            return index[m.group(1)]
    return None


# Coimbatore district bounding box (generous). Anything outside is not ours.
CBE_BBOX = (10.20, 76.60, 11.45, 77.35)  # lat_min, lng_min, lat_max, lng_max


def in_coimbatore(lat, lng) -> bool:
    if lat is None or lng is None:
        return False
    return CBE_BBOX[0] <= lat <= CBE_BBOX[2] and CBE_BBOX[1] <= lng <= CBE_BBOX[3]

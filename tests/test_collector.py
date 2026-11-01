import csv
import json
from pathlib import Path

import pytest
import yaml

from collector import db
from collector import normalize as N
from collector.pipeline import run
from collector.sources.base import build_listing
from collector.sources.portal import extract_page
from collector.sources.rera_tn import parse_tables

FIX = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------- normalize

@pytest.mark.parametrize("text,expected", [
    ("₹ 85 Lac", (8_500_000, None)),
    ("1.2 Cr", (12_000_000, None)),
    ("Rs.45,00,000", (4_500_000, None)),
    ("45 - 60 Lakhs", (4_500_000, 6_000_000)),
    ("₹18,000 / month", (18_000, None)),
    ("25K", (25_000, None)),
    ("Price on Request", (None, None)),
    (7850000, (7_850_000, None)),
])
def test_parse_inr(text, expected):
    assert N.parse_inr(text) == expected


@pytest.mark.parametrize("text,sqft,unit", [
    ("1,450 sq.ft", 1450, "sqft"),
    ("5 cents", 2178, "cent"),
    ("2 acres", 87120, "acre"),
    ("1 ground", 2400, "ground"),
    ("150 sq yd", 1350, "sqyd"),
    ("100 sqm", 1076.4, "sqm"),
])
def test_parse_area(text, sqft, unit):
    got, u, _ = N.parse_area(text)
    assert u == unit and got == pytest.approx(sqft, rel=1e-3)


def test_area_ignores_air_conditioners():
    assert N.find_areas("3 BHK with 2 AC and modular kitchen") == []


@pytest.mark.parametrize("text,ptype", [
    ("3 BHK Flat for sale", "apartment"),
    ("Independent house for sale", "independent_house"),
    ("Luxury villa in gated community", "villa"),
    ("5 cents DTCP approved plot", "plot"),
    ("Coconut farm land 4 acres", "agricultural_land"),
    ("Farm house near Thondamuthur", "farm_house"),
    ("Office space for lease", "commercial_office"),
    ("Showroom on main road", "commercial_shop"),
    ("Warehouse / godown", "warehouse"),
    ("Commercial land on Avinashi Road", "commercial_land"),
    ("PG for ladies near PSG", "pg_hostel"),
])
def test_property_type(text, ptype):
    assert N.detect_property_type(text) == ptype


def test_locality_aliases():
    assert N.match_locality("Flat in R.S. Puram, Coimbatore").name == "RS Puram"
    assert N.match_locality("near hopes college").name == "Hope College"
    assert N.match_locality("Chennai, Anna Nagar") is None


def test_rera_id():
    assert N.find_rera_id("Approved TN/11/Building/0123/2025 project") == "TN/11/Building/0123/2025"


# ---------------------------------------------------------------- extraction

def test_portal_extraction_jsonld_and_state():
    html = (FIX / "portal_page.html").read_text()
    recs = extract_page(html, "https://example-portal.in/coimbatore")
    rows = [build_listing(r, "demo", {"transaction": "sale"}) for r in recs]
    rows = {r["source_listing_id"]: r for r in rows if r}
    assert len(rows) == 4

    flat = next(r for r in rows.values() if r["property_type"] == "apartment")
    assert flat["price_inr"] == 7_850_000 and flat["built_up_sqft"] == 1450 and flat["bhk"] == 3
    assert flat["geo_precision"] == "exact" and flat["pincode"] == "641035"
    assert flat["price_per_sqft"] == pytest.approx(5413.8, rel=1e-3)
    assert flat["url"].startswith("https://example-portal.in/propertyDetails/")

    plot = rows["P-9001"]
    assert plot["property_type"] == "plot" and plot["plot_sqft"] == pytest.approx(2178)
    assert plot["area_unit_original"] == "cent" and plot["area_value_original"] == 5
    assert plot["bhk"] is None and "DTCP" in plot["approvals"] and plot["facing"] == "east"
    assert plot["locality"] == "Vadavalli" and plot["geo_precision"] == "locality"

    rent = rows["P-9002"]
    assert rent["transaction_type"] == "rent" and rent["price_inr"] == 18_000
    assert rent["furnishing"] == "semi_furnished" and rent["price_per_sqft"] is None

    office = rows["P-9003"]
    assert office["category"] == "commercial" and office["posted_by"] == "builder"


def test_rejects_listings_outside_coimbatore():
    assert build_listing({"title": "2 BHK flat in Anna Nagar, Chennai", "price": "80 L"}, "x") is None


def test_rera_table():
    recs = parse_tables((FIX / "rera_page.html").read_text(), "https://rera.tn.gov.in/x")
    assert [r["rera_id"] for r in recs] == ["TN/11/Building/0123/2025"]
    assert recs[0]["name"] == "Green Meadows" and recs[0]["promoter"] == "ABC Builders"


# ---------------------------------------------------------------- lifecycle

FIELDS = ["id", "title", "price", "area", "locality"]


def _write_feed(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS)
        w.writeheader()
        w.writerows(rows)


def _rows(n):
    return [{"id": f"L{i}", "title": f"{2 + i % 2} BHK flat for sale", "price": f"{50 + i} Lakhs",
             "area": f"{1000 + 10 * i} sqft", "locality": ["Peelamedu", "Vadavalli", "Kalapatti"][i % 3]}
            for i in range(n)]


@pytest.fixture
def env(tmp_path):
    feed = tmp_path / "feed.csv"
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(yaml.safe_dump({
        "settings": {"geocode": False},
        "sources": {"feed": {"kind": "csv", "name": "Feed", "path": str(feed)}},
    }))
    return {"feed": feed, "cfg": str(cfg), "db": str(tmp_path / "x.sqlite"), "out": str(tmp_path / "out")}


def _active(env):
    return {d["title"] + d["id"] for d in json.loads(Path(env["out"], "listings.json").read_text())}


def test_weekly_lifecycle(env):
    _write_feed(env["feed"], _rows(10))
    s1 = run(env["cfg"], env["db"], env["out"], geocode=False)
    assert s1["feed"] == {"status": "ok", "records": 10, "new": 10, "expired": 0, "message": None}

    # week 2: two listings removed, one price drop, one new listing
    rows = _rows(10)[2:] + [{"id": "L99", "title": "Villa for sale", "price": "1.5 Cr", "area": "2400 sqft",
                             "locality": "Kovaipudur"}]
    rows[0]["price"] = "40 Lakhs"
    _write_feed(env["feed"], rows)
    s2 = run(env["cfg"], env["db"], env["out"], geocode=False)
    assert s2["feed"]["expired"] == 2 and s2["feed"]["new"] == 1

    data = json.loads(Path(env["out"], "listings.json").read_text())
    assert len(data) == 9
    dropped = [d for d in data if d.get("previous_price_inr")]
    assert len(dropped) == 1 and dropped[0]["price_inr"] == 4_000_000
    assert [d for d in data if d.get("is_new")][0]["property_type"] == "villa"
    meta = json.loads(Path(env["out"], "meta.json").read_text())
    assert [t["sale"] for t in meta["trend"]] == [10, 9]

    conn = db.connect(env["db"])
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE status='inactive'").fetchone()[0] == 2


def test_partial_run_does_not_expire(env):
    _write_feed(env["feed"], _rows(20))
    run(env["cfg"], env["db"], env["out"], geocode=False)
    _write_feed(env["feed"], _rows(3))  # source mostly broken this week
    s = run(env["cfg"], env["db"], env["out"], geocode=False)
    assert s["feed"]["status"] == "suspicious" and s["feed"]["expired"] == 0
    assert len(json.loads(Path(env["out"], "listings.json").read_text())) == 20

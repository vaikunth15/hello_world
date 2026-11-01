# Coimbatore Property Index

Every **active** real-estate listing in Coimbatore in one place: flats, houses, villas, plots,
agricultural land, offices, shops, warehouses, PGs, for sale and for rent. It refreshes
**every week** and has an interactive dashboard with a map, a table, and market insights.

```
 sources.yaml ─► collector (Python) ─► data/realestate.sqlite ─► docs/data/*.json ─► docs/ dashboard
   portals          normalise              full history              active snapshot     map · table · insights
   CSV feeds        geocode                price history                                 (GitHub Pages)
   TN RERA          dedupe across sites    weekly market snapshots
                    expire delisted
        ▲
        └── GitHub Actions, every Monday 06:00 IST (.github/workflows/refresh.yml)
```

## Setup (one time)

1. **Enable the dashboard:** repo Settings → Pages → *Deploy from a branch* → `master` / `/docs`.
2. **Run the first collection:** Actions → *Weekly listings refresh* → *Run workflow*.
   After that it runs by itself every Monday and commits the new data.
3. Open the **Sources** tab on the dashboard to see what each source returned.

Local run:

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q                      # parser + lifecycle tests
python -m collector run                  # full refresh -> docs/data
python -m collector run --only manual    # just one source
python -m collector status
python -m http.server -d docs 8000       # open http://localhost:8000
```

## Where the data comes from

| Kind | Source | Notes |
|---|---|---|
| `portal` | MagicBricks, 99acres, Housing.com, Square Yards, Makaan | Reads the structured data portals embed (schema.org JSON-LD, front-end state JSON), not fragile HTML layouts. Add `css:` selectors in `sources.yaml` for sites that embed neither. |
| `csv` | `data/feeds/manual_listings.csv` or any published Google Sheet | The dependable path: broker inventories, builder price lists, partner exports. |
| `rera` | Tamil Nadu RERA registered projects, Coimbatore district | Government data; used to verify RERA numbers quoted in listings. |

**Please read:** most commercial portals' Terms of Use restrict automated collection, and many
block cloud IP ranges like GitHub's. The collector honours robots.txt, waits 5+ seconds between
requests to a site, and identifies itself, but that does not grant permission. Check each portal's
terms (or ask them for a data feed) before relying on it, and set `enabled: false` for any you
should not crawl. The portal URL patterns in `sources.yaml` have **not been verified against
the live sites yet**. Expect to adjust them after the first run, guided by the Sources tab.

## How "active" works

* A listing is **active** while its source keeps showing it. When a source's weekly run succeeds,
  its listings that were not seen in that run are marked `inactive` (delisted, sold, or expired).
* **Safety guard:** if a source is blocked, errors, or returns under 40% of its last good yield,
  its listings are *kept*, not expired, and the run is flagged `suspicious`. A broken scraper
  must not wipe the map.
* Listings whose source has failed for 21+ days are expired as stale.
* Every price change is recorded in `price_history`, so the dashboard can show price drops.

## Data model (`collector/db.py`)

| Table | Purpose |
|---|---|
| `listings` | One row per advert per source. Normalised fields (see below) plus the original `raw` JSON so records can be re-parsed when the parser improves. |
| `price_history` | `(listing_id, run_id, price_inr)`, written only when the price changes. |
| `projects` | TN RERA registered projects (RERA no., promoter, locality, dates). |
| `runs`, `source_runs` | Audit trail: per run, per source status, pages, records, new, expired, error. |
| `market_snapshots` | Weekly active count, median price and median ₹/sq ft per (deal × type × locality). Trends survive after listings expire. |
| `geocode_cache` | Cached OSM Nominatim lookups. |
| `sources` | Registry mirrored from `sources.yaml`. |

Key listing fields, and choices made for Coimbatore:

* **`transaction_type`**: `sale` · `rent` · `lease`. **`property_type`**: `apartment`, `independent_house`, `villa`, `plot`,
  `agricultural_land`, `farm_house`, `commercial_office`, `commercial_shop`, `commercial_land`,
  `warehouse`, `industrial`, `pg_hostel`, `other`, rolled up into a `category`.
* **Area is always stored in sq ft**, but the original unit is kept: land here is sold in
  **cents** (1 cent = 435.6 sq ft), acres and grounds, so the dashboard shows "5 cents (2,178 sq ft)"
  and charts plot price **per cent**.
* **Prices** are parsed from Indian formats ("₹85 Lac", "1.2 Cr", "45–60 Lakhs", "₹18,000/month")
  into rupees, with `price_max_inr` for ranges and `price_per_sqft` for sales.
* **Location:** `locality` is matched against a 72-locality gazetteer with aliases (`collector/data/localities.csv`:
  "R.S. Puram" → RS Puram, "Hopes" → Hope College), with Corporation `zone`. `geo_precision` says
  whether the pin is `exact` (from the source) or `locality` (locality centre); approximate pins are
  drawn pale on the map. Anything outside the Coimbatore district bounding box is rejected.
* **Trust signals:** `rera_id` (matched against TN RERA projects), `approvals` mentioned (DTCP, LPA,
  RERA…), `posted_by` owner/agent/builder, `facing`.
* **Duplicates across portals:** `property_key` clusters the same property advertised on several
  sites (same deal, type, locality, BHK; area within ~5%; price within ~8%). The listing drawer
  shows "Also listed on …" with each site's price.

## Dashboard (`docs/`)

Static HTML/JS with no build step and no external CDNs (Leaflet is vendored).

* **Filters** (they apply to every view and are kept in the URL, so a filtered view can be shared):
  search, buy/rent, property type, locality, BHK, budget, area, posted by, furnishing,
  construction status, source, DTCP/RERA mentioned, new this week, price dropped.
* **Map:** clustered pins coloured by deal, density heatmap, RERA project layer, and a list of listings in view.
* **Listings:** sortable table; click any row for full details, links to the original advert, and other sites carrying it.
* **Insights:** median ₹/sq ft by locality, plot ₹/cent by locality, price bands, rent by BHK,
  listings by type and source, and the week-by-week trend. Each chart can also be viewed as a table.
* **RERA projects** and **Sources** (health of each weekly run).
* Export the filtered listings to CSV. Light and dark mode.

## Extending

* **Add a portal:** add an entry under `sources:` in `sources.yaml`. If it embeds JSON-LD or front-end JSON, that is enough.
* **Add a locality:** add a row to `collector/data/localities.csv` (name, aliases, lat, lng, zone).
* **New connector type:** subclass `collector.sources.base.Source`, yield loose dicts, and register it in `collector/sources/__init__.py`.

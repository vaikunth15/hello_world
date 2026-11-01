"""CLI.

    python -m collector run                 # full weekly refresh
    python -m collector run --only tnrera   # one source
    python -m collector export              # rebuild docs/data from the DB
    python -m collector status              # last run per source
"""
from __future__ import annotations

import argparse
import json
import logging

from . import db
from .export import export_all
from .pipeline import run


def main(argv=None):
    ap = argparse.ArgumentParser(prog="collector")
    ap.add_argument("command", choices=["run", "export", "status"])
    ap.add_argument("--config", default="sources.yaml")
    ap.add_argument("--db", default="data/realestate.sqlite")
    ap.add_argument("--out", default="docs/data")
    ap.add_argument("--only", nargs="*", help="source ids to run")
    ap.add_argument("--no-geocode", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if a.command == "run":
        summary = run(a.config, a.db, a.out, only=a.only, geocode=not a.no_geocode)
        print(json.dumps(summary, indent=2))
    elif a.command == "export":
        conn = db.connect(a.db)
        print(f"exported {export_all(conn, a.out)} active listings")
    else:
        conn = db.connect(a.db)
        for r in conn.execute("""SELECT s.id, sr.status, sr.records, sr.new_listings, sr.expired, sr.message,
                                        (SELECT COUNT(*) FROM listings l WHERE l.source_id=s.id AND l.status='active') act
                                 FROM sources s LEFT JOIN source_runs sr ON sr.source_id=s.id
                                   AND sr.run_id=(SELECT MAX(run_id) FROM source_runs WHERE source_id=s.id)"""):
            print(dict(r))


if __name__ == "__main__":
    main()

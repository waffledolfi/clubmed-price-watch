#!/usr/bin/env python3
"""Build share.html -- a self-contained comparison page for the Artifact host.

Reads prices.db (tracked-week history) and scan_<PRODUCT>.json (season sweep),
and emits page content only: no doctype/html/head/body wrapper.

    python3 publish.py            # writes share.html
"""

import glob
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from clubmed import booking_url, parse_date  # noqa: E402
from watch import DB, extras_for, load_config  # noqa: E402


def collect():
    cfg = load_config()
    ex_amt, ex_note = extras_for(cfg)
    con = sqlite3.connect(DB)
    watches = []
    for w in cfg["watches"]:
        rows = con.execute(
            "SELECT ts,best_price,initial_price,currency FROM observations "
            "WHERE label=? AND error IS NULL ORDER BY id", (w["label"],)).fetchall()
        w_amt, w_note = extras_for(cfg, w)
        watches.append({
            "label": w["label"],
            "start_date": w["start_date"],
            "end_date": (parse_date(w["start_date"]) + timedelta(days=w["_nights"])).isoformat(),
            "nights": w["_nights"],
            "adults": w.get("adults", 2),
            "target": w.get("target_price"),
            "extras": w_amt,
            "url": booking_url(w["product_id"], w.get("slug", ""), w["start_date"],
                               w["_nights"], w.get("adults", 2), w.get("children", 0),
                               cfg.get("site"), w.get("season", "w")),
            "points": [{"ts": r[0], "best": r[1], "list": r[2]} for r in rows],
            "currency": rows[-1][3] if rows else "SGD",
        })
    con.close()

    season = []
    scanned_at = None
    for f in sorted(glob.glob(os.path.join(HERE, "scan_*.json"))):
        d = json.load(open(f))
        scanned_at = d.get("generated")
        for r in d["results"]:
            r["per_night"] = round(r["best_price"] / r["nights"], 2)
            season.append(r)

    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "scanned_at": scanned_at,
        "extras": ex_amt,
        "extras_note": ex_note,
        "watches": watches,
        "season": season,
    }


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%8F%82%3C/text%3E%3C/svg%3E">
</head>
<body>
__BODY__
</body>
</html>
"""


MIN_QUOTES = 10


def main():
    data = collect()

    # Refuse to overwrite a good page with a broken one. If Club Med changes
    # their API and the scan comes back empty, the last published page should
    # survive rather than being replaced by an empty table.
    n = len(data["season"])
    if n < MIN_QUOTES and os.environ.get("ALLOW_SPARSE") != "1":
        raise SystemExit(
            "Only %d season quotes (expected at least %d). Refusing to rebuild "
            "the page.\nRe-run the scan, or set ALLOW_SPARSE=1 to override:\n"
            "  python3 watch.py scan KIPC_WINTER 2026-12-01 2027-04-27 4,5,6 7"
            % (n, MIN_QUOTES))
    tpl = open(os.path.join(HERE, "share_template.html")).read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(data))

    # 1. fragment, for publishing as a Claude Artifact
    out = os.path.join(HERE, "share.html")
    with open(out, "w") as f:
        f.write(html)

    # 2. full document, for GitHub Pages
    docs = os.path.join(HERE, "docs")
    os.makedirs(docs, exist_ok=True)
    with open(os.path.join(docs, "index.html"), "w") as f:
        f.write(PAGE.replace("__BODY__", html))

    print("Wrote %s and docs/index.html  (%d tracked week(s), %d season quotes)" % (
        out, len(data["watches"]), len(data["season"])))


if __name__ == "__main__":
    main()

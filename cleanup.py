#!/usr/bin/env python3
"""
Re-apply the current classifier + BLOCKLIST to everything already stored.

Run this after tightening a rule in gem_bids_scraper.py, or after adding a
bid number to BLOCKLIST. Rewrites bids.csv and bids.json in place.

    python cleanup.py            # show what would be removed, then do it
    python cleanup.py --dry-run  # show only
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gem_bids_scraper as S

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "bids.csv")
JSON_PATH = os.path.join(HERE, "bids.json")
DRY = "--dry-run" in sys.argv

rows = list(csv.DictReader(open(CSV_PATH, newline="", encoding="utf8")))
kept, dropped = [], []

for r in rows:
    bn = r.get("bid_number", "")
    if bn in S.BLOCKLIST:
        dropped.append((bn, "blocklisted", r.get("item", "")[:60]))
        continue
    bucket, items, n = S.classify(r.get("item", ""))
    if not bucket:
        dropped.append((bn, "no longer matches", r.get("item", "")[:60]))
        continue
    r["category"] = bucket
    r["matched_items"] = " | ".join(items)
    r["n_items"] = n
    r["is_bundle"] = 1 if n > 1 else 0
    kept.append(r)

print("{:,} rows -> keep {:,}, remove {:,}".format(
    len(rows), len(kept), len(dropped)))
for bn, why, item in dropped[:40]:
    print("  - {:<22} {:<18} {}".format(bn, why, item))
if len(dropped) > 40:
    print("  ... and {} more".format(len(dropped) - 40))

if DRY:
    print("\ndry run - nothing written")
    sys.exit(0)

kept.sort(key=lambda r: r.get("bid_start_date", ""), reverse=True)
with open(CSV_PATH, "w", newline="", encoding="utf8") as f:
    w = csv.DictWriter(f, fieldnames=S.FIELDS)
    w.writeheader()
    for r in kept:
        w.writerow({k: r.get(k, "") for k in S.FIELDS})

data = json.load(open(JSON_PATH, encoding="utf8"))
data["rows"] = kept
data["total"] = len(kept)
json.dump(data, open(JSON_PATH, "w", encoding="utf8"), indent=1)
print("\nwritten. now run: python build_dashboard.py")

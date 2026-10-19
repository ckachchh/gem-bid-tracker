#!/usr/bin/env python3
"""
Move long-closed bids out of bids.csv into bids-archive.csv.

bids.csv grows forever otherwise: every bid ever seen stays in it, even
though a tender that closed months ago is never going to be useful again.
Nothing is deleted -- rows are appended to the archive file, which is also
committed, so the full history stays recoverable.

    python archive.py                 # archive bids closed >90 days ago
    python archive.py --days 30       # tighter window
    python archive.py --dry-run       # report only
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gem_bids_scraper as S

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "bids.csv")
JSON_PATH = os.path.join(HERE, "bids.json")
ARCHIVE_PATH = os.path.join(HERE, "bids-archive.csv")

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=90,
                help="archive bids whose close date is older than this")
ap.add_argument("--dry-run", action="store_true")
args = ap.parse_args()

cutoff = (datetime.now(timezone.utc).date()
          - timedelta(days=args.days)).isoformat()

rows = list(csv.DictReader(open(CSV_PATH, newline="", encoding="utf8")))
keep, stale = [], []
for r in rows:
    end = (r.get("bid_end_date") or "")[:10]
    if end and end < cutoff:
        stale.append(r)
    else:
        keep.append(r)

print("{:,} rows -> keep {:,}, archive {:,} (closed before {})".format(
    len(rows), len(keep), len(stale), cutoff))

if not stale:
    print("nothing to archive")
    sys.exit(0)

if args.dry_run:
    for r in stale[:10]:
        print("  - {:<22} closed {}".format(
            r.get("bid_number", ""), r.get("bid_end_date", "")[:10]))
    print("\ndry run - nothing written")
    sys.exit(0)

# append to the archive, de-duplicating on bid number
archived = {}
if os.path.exists(ARCHIVE_PATH):
    for r in csv.DictReader(open(ARCHIVE_PATH, newline="", encoding="utf8")):
        archived[r.get("bid_number", "")] = r
for r in stale:
    archived[r.get("bid_number", "")] = r

with open(ARCHIVE_PATH, "w", newline="", encoding="utf8") as f:
    w = csv.DictWriter(f, fieldnames=S.FIELDS)
    w.writeheader()
    for r in sorted(archived.values(),
                    key=lambda x: x.get("bid_end_date", ""), reverse=True):
        w.writerow({k: r.get(k, "") for k in S.FIELDS})

keep.sort(key=lambda r: r.get("bid_start_date", ""), reverse=True)
with open(CSV_PATH, "w", newline="", encoding="utf8") as f:
    w = csv.DictWriter(f, fieldnames=S.FIELDS)
    w.writeheader()
    for r in keep:
        w.writerow({k: r.get(k, "") for k in S.FIELDS})

data = json.load(open(JSON_PATH, encoding="utf8"))
data["rows"] = keep
data["total"] = len(keep)
json.dump(data, open(JSON_PATH, "w", encoding="utf8"), indent=1)

print("archive now holds {:,} bids -> {}".format(len(archived), ARCHIVE_PATH))
print("run: python build_dashboard.py")

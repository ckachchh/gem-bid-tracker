#!/usr/bin/env python3
"""
GeM bid scraper - Desktops / Laptops / All-in-One PCs / Servers
Source: https://bidplus.gem.gov.in/all-bids  (POST https://bidplus.gem.gov.in/all-bids-data)

Pulls live bids, keyword-filters to IT hardware categories, and appends new rows
to bids.csv (deduped on bid number). Also writes bids.json for the dashboard.

NOTE: bid_start_date is GeM's final_start_date_sort = when bidding OPENS.
It is not the document publication date, which only appears inside the bid PDF.

Usage:
    python3 gem_bids_scraper.py                 # all search terms
    python3 gem_bids_scraper.py laptop server   # subset
Env:
    GEM_MAX_PAGES (default 30)   GEM_DELAY (default 1.2 seconds between pages)
"""

import csv
import html
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import gem_state

BASE = "https://bidplus.gem.gov.in"
LIST_URL = BASE + "/all-bids"
DATA_URL = BASE + "/all-bids-data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "bids.csv")
JSON_PATH = os.path.join(HERE, "bids.json")

MAX_PAGES = int(os.environ.get("GEM_MAX_PAGES", "30"))
DELAY = float(os.environ.get("GEM_DELAY", "1.2"))

# Terms handed to GeM's own full-text search (server-side narrowing)
SEARCH_TERMS = [
    "desktop computer", "laptop", "notebook", "all in one pc",
    "server", "workstation",
]

# GeM bundles multiple products into one BOQ bid, so the item string is a
# comma-separated list. Classification runs per individual item, not on the
# whole string -- otherwise "100 Pages Notebook" matches Laptop and
# "Pneumatic Workstation" matches Desktop.

BUCKETS = [
    ("All-in-One PC", [r"all\s*[- ]?\s*in\s*[- ]?\s*one\s*(pc|desktop|computer)",
                       r"\baio\s*(pc|desktop)"]),
    # "Notebook" on its own is ambiguous -- GeM uses it for paper notebooks as
    # often as for laptops ("100 Pages Notebook", "Training notebook"). Only
    # match it with explicit laptop/computer context.
    ("Laptop",        [r"\blaptop", r"\bultrabook\b", r"\bmacbook\b",
                       r"notebook\s*(computer|pc|laptop)",
                       r"(laptop|rugged)\s*[-/]?\s*notebook",
                       r"notebook\s*[-/]\s*laptop",
                       r"device\s*/\s*notebook", r"notebook\s*and\s*similar"]),
    ("Server",        [r"\bserver\b", r"\bservers\b", r"blade\s*server",
                       r"rack\s*server", r"tower\s*server", r"gpu\s*server"]),
    ("Desktop",       [r"desktop", r"personal\s*computer", r"\bpc\b",
                       r"computer\s*workstation", r"graphics?\s*workstation",
                       r"\bworkstation\b"]),
]

# An item matching any of these is never IT hardware, even if it also matches
# a bucket above. Checked per item.
ITEM_EXCLUDE = [
    # paper / stationery ("100 Pages Notebook", "Note book 200pages")
    r"\d+\s*pages?", r"note\s*book\s*\d", r"\bpaper\b", r"\bregister\b",
    r"\bpen\b", r"\bpens\b", r"\bmop\b", r"\bbroom\b",
    r"\btraining\b", r"\bcertificate\b", r"certficate", r"answer\s*sheet",
    r"black\s*board", r"white\s*board", r"\bfile\b", r"\bfolder\b",
    r"\bdiary\b", r"\benvelope\b", r"stationery", r"\bprinted\b",
    # lab / industrial / medical equipment that uses the word "workstation"
    r"pneumatic", r"anaesthesia", r"anesthesia", r"electrochemical", r"anaerobic",
    r"tissue\s*(embedding|lyser)", r"welding", r"soldering", r"fume", r"biosafety",
    r"laminar", r"trainer", r"simulator", r"\bdof\b", r"mechatronic",
    r"induction", r"\bbrazing\b", r"ultrasonic", r"\bassay\b", r"analy[sz]er",
    # accessories / peripherals / other IT that is not the machine itself
    r"\bprinter\b", r"\bmfp\b", r"\bmfd\b", r"scanner", r"\bprojector\b",
    r"interactive\s*panel", r"visuali[sz]er", r"\bfirewall\b", r"\bswitch\b",
    r"network\s*attached", r"\bnas\b", r"\brouter\b", r"\btablet\b",
    r"smartphone", r"\biphone\b", r"mobile\s*phone", r"\btelephone\b",
    r"\bbag\b", r"\bsleeve\b", r"\bbattery\b", r"\badapter\b", r"\bcharger\b",
    r"\bstand\b", r"\btrolley\b", r"\bcover\b", r"\bskin\b", r"\bkeyboard\b",
    r"\bmouse\b", r"\bups\b", r"\bcable\b", r"\btoner\b", r"cartridge",
    r"\bgpu\s*card", r"storage\s*server",
    # services / software / furniture
    r"repair", r"\bamc\b", r"maintenance", r"hiring", r"rental", r"\brent\b",
    r"manpower", r"subscription", r"renewal", r"licen[cs]e", r"\balng\b",
    r"\bolv\b", r"perpetual", r"antivirus", r"\bsoftware\b", r"\bms office\b",
    r"windows\s*server\s*\d", r"\bsles\b", r"hosting",
    r"modular\s*work\s*station", r"combined\s*style", r"seater", r"\bchair\b",
    r"\bdesk\b", r"\btable\b", r"furniture", r"frame\s*:",
    r"air\s*condition", r"\bvrf\b", r"\bvrv\b",
]

# Whole-bid rejects: if the bid title itself is a service contract
BID_EXCLUDE = [r"custom bid for services", r"\bamc\b", r"manpower"]


FIELDS = ["bid_number", "category", "matched_items", "item", "ministry",
          "department", "state", "quantity", "n_items", "is_bundle",
          "bid_start_date", "bid_end_date", "bid_url", "captured_on"]


def get_session(attempts=3):
    """Load /all-bids to pick up cookies + the CSRF token the AJAX call needs.

    Retries with backoff: GeM sits behind bot protection that intermittently
    challenges requests, especially from datacenter IPs (CI runners).
    """
    last = None
    for i in range(attempts):
        try:
            cj = http.cookiejar.CookieJar()
            op = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(cj))
            op.addheaders = [
                ("User-Agent", UA),
                ("Accept", "text/html,application/xhtml+xml,application/xml;"
                           "q=0.9,*/*;q=0.8"),
                ("Accept-Language", "en-US,en;q=0.9"),
                ("Upgrade-Insecure-Requests", "1"),
            ]
            page = op.open(LIST_URL, timeout=40).read().decode("utf8", "ignore")
            m = re.search(r"csrf_bd_gem_nk'\s*:\s*'([a-f0-9]+)'", page)
            if m:
                return op, m.group(1)
            last = ("no CSRF token in a {} byte response. GeM either changed "
                    "its page or served a bot-protection challenge."
                    .format(len(page)))
            if "captcha" in page.lower() or "access denied" in page.lower():
                last += " Response mentions captcha/access-denied -> blocked."
        except Exception as e:                       # noqa: BLE001
            last = "{}: {}".format(type(e).__name__, e)
        if i < attempts - 1:
            wait = 5 * (i + 1)
            print("  session attempt {} failed ({}); retrying in {}s"
                  .format(i + 1, last, wait), flush=True)
            time.sleep(wait)
    raise RuntimeError("could not open a GeM session - " + str(last))


def fetch_page(op, token, term, page):
    payload = {
        "page": page,
        "param": {"searchBid": term, "searchType": "fullText"},
        "filter": {
            "bidStatusType": "ongoing_bids",
            "byType": "all",
            "highBidValue": "",
            "byEndDate": {"from": "", "to": ""},
            "sort": "Bid-Start-Date-Latest",
        },
    }
    data = urllib.parse.urlencode({
        "payload": json.dumps(payload),
        "csrf_bd_gem_nk": token,
    }).encode()
    req = urllib.request.Request(DATA_URL, data=data, headers={
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": LIST_URL,
    })
    j = json.loads(op.open(req, timeout=45).read().decode("utf8", "ignore"))
    if j.get("code") != 200:
        raise RuntimeError("GeM returned code " + str(j.get("code")))
    return j["response"]["response"]


def one(v, default=""):
    """GeM returns most fields as single-element lists."""
    if isinstance(v, list):
        return v[0] if v else default
    return v if v is not None else default


def classify(title):
    """Classify a (possibly multi-item) GeM bid title.

    Returns (bucket, matched_items, total_items) or (None, [], n).
    Splits on commas and classifies each item independently, so a bundled
    bid is only categorised on the items that are genuinely IT hardware.
    """
    low = title.lower()
    for pat in BID_EXCLUDE:
        if re.search(pat, low):
            return None, [], 0

    items = [i.strip() for i in title.split(",") if i.strip()]
    if not items:
        return None, [], 0

    matched = []
    for item in items:
        t = item.lower()
        if any(re.search(p, t) for p in ITEM_EXCLUDE):
            continue
        for bucket, pats in BUCKETS:
            if any(re.search(p, t) for p in pats):
                matched.append((bucket, item))
                break

    if not matched:
        return None, [], len(items)

    # bucket priority when a bid mixes categories: most specific first
    order = ["All-in-One PC", "Server", "Laptop", "Desktop"]
    buckets_found = {b for b, _ in matched}
    for b in order:
        if b in buckets_found:
            return b, [i for bk, i in matched], len(items)
    return matched[0][0], [i for _, i in matched], len(items)


def fmt_date(s):
    if not s:
        return ""
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(s)


def scrape(terms=None, max_pages=MAX_PAGES, delay=DELAY):
    op, token = get_session()
    found = {}
    for term in (terms or SEARCH_TERMS):
        page = 1
        while page <= max_pages:
            try:
                resp = fetch_page(op, token, term, page)
            except Exception as e:
                print("  ! {} p{}: {}".format(term, page, e), flush=True)
                break
            docs = resp.get("docs", [])
            if not docs:
                break
            for d in docs:
                title = html.unescape(str(one(d.get("b_category_name"))))
                bucket, matched_items, n_items = classify(title)
                if not bucket:
                    continue
                raw_no = str(one(d.get("b_bid_number")))
                if not raw_no:
                    continue

                # b_bid_type 2 and 5 are Reverse Auctions. Their b_bid_number
                # is an RA number (GEM/YYYY/R/...), not the tender number --
                # so resolve it back to the parent bid. We keep the tender but
                # never surface the RA number itself.
                is_ra = str(one(d.get("b_bid_type"))) in ("2", "5")
                if is_ra:
                    parent_no = str(one(d.get("b_bid_number_parent"), "") or "")
                    parent_id = str(one(d.get("b_id_parent"), "") or "")
                    if not parent_no:
                        continue          # orphan RA, no tender to point at
                    bid_no = parent_no
                    doc_id = parent_id or str(one(d.get("b_id")))
                else:
                    bid_no = raw_no
                    doc_id = str(one(d.get("b_id")))

                if "/R/" in bid_no:       # belt and braces
                    continue
                if bid_no in found:
                    continue

                dept = html.unescape(str(one(d.get("ba_official_details_deptName"))))
                minname = html.unescape(str(one(d.get("ba_official_details_minName"))))
                found[bid_no] = {
                    "bid_number": bid_no,
                    "category": bucket,
                    "item": title,
                    "ministry": minname,
                    "department": dept,
                    "state": gem_state.state_from_text(dept, minname)[0],
                    "quantity": one(d.get("b_total_quantity"), ""),
                    "matched_items": " | ".join(matched_items),
                    "n_items": n_items,
                    "is_bundle": 1 if n_items > 1 else 0,
                    "bid_start_date": fmt_date(one(d.get("final_start_date_sort"))),
                    "bid_end_date": fmt_date(one(d.get("final_end_date_sort"))),
                    "bid_url": BASE + "/showbidDocument/" + doc_id,
                    "captured_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }
            if resp.get("start", 0) + len(docs) >= resp.get("numFound", 0):
                break
            page += 1
            time.sleep(delay)
        print("  {}: running total {}".format(term, len(found)), flush=True)
    return list(found.values())


def merge(rows):
    """Append only bid numbers we have not seen before."""
    existing = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, newline="", encoding="utf8") as f:
            for r in csv.DictReader(f):
                existing[r["bid_number"]] = r
    new = [r for r in rows if r["bid_number"] not in existing]
    for r in new:
        existing[r["bid_number"]] = r

    allrows = sorted(existing.values(),
                     key=lambda r: r.get("bid_start_date", ""), reverse=True)
    with open(CSV_PATH, "w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in allrows:
            w.writerow(dict((k, r.get(k, "")) for k in FIELDS))

    with open(JSON_PATH, "w", encoding="utf8") as f:
        json.dump({
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "total": len(allrows),
            "new_today": len(new),
            "rows": allrows,
        }, f, indent=1)
    return allrows, new


if __name__ == "__main__":
    terms = sys.argv[1:] or None
    print("Scraping GeM bids ...", flush=True)
    try:
        rows = scrape(terms)
    except Exception as e:                           # noqa: BLE001
        print("SCRAPE FAILED: {}: {}".format(type(e).__name__, e), flush=True)
        # Exit 0 when we already have data so a transient GeM block does not
        # fail the whole pipeline; the dashboard just keeps yesterday's rows.
        if os.path.exists(CSV_PATH):
            print("existing {} kept; continuing".format(CSV_PATH), flush=True)
            sys.exit(0)
        sys.exit(1)
    allrows, new = merge(rows)
    print("")
    print("Matched this run   : {}".format(len(rows)))
    print("New since last run : {}".format(len(new)))
    print("Total tracked      : {}".format(len(allrows)))
    print("CSV  : " + CSV_PATH)
    print("JSON : " + JSON_PATH)
    for r in new[:10]:
        print("  {}  {:<24} {:<14} qty {:<6} {}".format(
            r.get("bid_start_date", ""), r.get("bid_number", ""),
            r.get("category", ""), r.get("quantity", ""),
            r.get("department", "")[:40]))

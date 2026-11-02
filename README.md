# GeM IT Hardware Bid Tracker

Tracks Government e-Marketplace (GeM) tenders for **desktops, laptops,
all-in-one PCs and servers**, and publishes a dashboard to GitHub Pages.

## Important: why this does not run on GitHub Actions

GeM blocks GitHub's runner IPs at the TCP level (`Errno 111 Connection
refused`) before any HTTP request is made. No amount of headers, retries or
user-agent spoofing changes this. **The scrape must run from an Indian IP**,
i.e. your own machine. GitHub only hosts the resulting static page.

    your PC (scrapes GeM)  ->  git push  ->  GitHub Pages (serves dashboard)

## Setup

1. Push this folder to a GitHub repo.
2. **Settings -> Pages -> Source: Deploy from a branch**, branch `main`,
   folder **`/docs`**.
3. Schedule `update.bat` in Windows Task Scheduler:
   - Task Scheduler -> Create Basic Task -> name it "GeM bid tracker"
   - Trigger: Daily, 09:30
   - Action: Start a program -> browse to `update.bat` in this folder
   - Tick **"Run whether user is logged on or not"** so it runs with the lid
     open but no session active.

Dashboard URL: `https://<username>.github.io/<repo>/`

## What runs each day

`update.bat` scrapes GeM, reads the PDFs of new bundled bids (`gem_items.py`),
rebuilds `docs/index.html`, and pushes. If the build
fails it does not push, so a broken run leaves the last good dashboard up.
Output is appended to `update.log`.

## Data caveats

- **Bid Start Date** is when bidding opens - *not* the document publication
  date. That appears only in the bid PDF as rendered graphics, not extractable
  text, so it is not collected.
- **Computers** (the quantity column and the Desktops / Laptops / All-in-Ones /
  Workstations / Servers cards) are exact unit counts. For a single-product bid
  this is GeM's quantity. For a bundled bid GeM only gives a bid-wide total
  across every line item, so `gem_items.py` downloads the bid PDF, reads the
  item list and caches it in `bid_items.json`. Each item is classified again on
  every build, so rule changes apply to cached bids too. A bundle whose PDF has
  not been read yet shows the bid-wide total marked `*` and is left out of the
  per-type totals.
  A cached item list is trusted only if its quantities add up to the PDF's
  "Total Quantity". If one doesn't, the bid is retried after `PARSER_VERSION` in
  `gem_items.py` is bumped.
- **Reverse auctions** resolve to their parent tender number; RA numbers are
  never shown.
- **State** comes from the buyer's department name. Central bodies (Military
  Affairs, Indian Railways) show as *central*.

## Tuning the product filter

In `gem_bids_scraper.py`:

- `BUCKETS` - patterns that assign a category
- `ITEM_EXCLUDE` - patterns that reject an item (stationery, lab equipment,
  furniture, peripherals, software)

GeM item names are inconsistent, so expect to add exclusions over time. After
each change, check what it *drops* as well as what it keeps - tightening a rule
has twice removed genuine bids here.

## Running by hand

```
python gem_bids_scraper.py          # all search terms
python gem_items.py                 # read PDFs of new bundled bids -> bid_items.json
python gem_items.py --test X.pdf    # show the items/counts found in one bid PDF
python build_dashboard.py           # writes dashboard.html
```

Standard library only - no `pip install` needed.

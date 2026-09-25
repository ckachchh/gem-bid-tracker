# GeM IT Hardware Bid Tracker

Tracks Government e-Marketplace (GeM) tenders for **desktops, laptops,
all-in-one PCs and servers**, and publishes a dashboard to GitHub Pages.

Updates itself every morning at 09:30 IST via GitHub Actions.

## What it does

1. `gem_bids_scraper.py` queries GeM's bid-search endpoint, classifies each
   line item, and appends new bids to `bids.csv` (deduplicated on bid number).
2. `build_dashboard.py` bakes that data into a single self-contained
   `dashboard.html` — no server, no database, no API calls when viewed.
3. The workflow publishes it to GitHub Pages and commits `bids.csv` back so
   bid history accumulates.

## Setup

1. Create the repo and push these files.
2. **Settings → Pages → Source: GitHub Actions**
3. **Settings → Actions → General → Workflow permissions:
   Read and write permissions**
4. **Actions tab → "Update GeM bid dashboard" → Run workflow** to test it now.

Your dashboard: `https://<username>.github.io/<repo>/`

## Notes on the data

- **Bid Start Date** is when bidding opens — *not* the document publication
  date, which exists only inside the bid PDF and is not machine-readable.
- **Quantity** on a bundled bid is GeM's bid-wide total across all line items,
  not the count of computers. Those rows are marked with `*`.
- **Reverse auctions** are resolved to their parent tender number; RA numbers
  are never shown.
- **State** is derived from the buyer's department name. Central bodies
  (Military Affairs, Indian Railways) show as *central*.

## Tuning the filter

Product matching lives in `gem_bids_scraper.py`:

- `BUCKETS` — patterns that assign a category
- `ITEM_EXCLUDE` — patterns that reject an item (stationery, lab equipment,
  furniture, peripherals, software)

GeM item names are inconsistent, so expect to add exclusions over time. After
editing, re-check what a change drops as well as what it keeps.

## Running locally

```bash
python3 gem_bids_scraper.py          # all search terms
python3 build_dashboard.py           # writes dashboard.html
```

Standard library only — no `pip install` required.

## If the scraper breaks

It fails loudly rather than publishing stale data. The usual cause is GeM
changing its page: the CSRF token regex in `get_session()` stops matching, or
`all-bids-data` returns a non-200 code. Re-check the endpoint in that case.

Requests from GitHub's datacenter IPs may be challenged by GeM's bot
protection more often than from an Indian connection. If scheduled runs fail
but local runs work, that is the likely reason.

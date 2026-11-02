#!/usr/bin/env python3
"""
Exact per-product quantities for bundled GeM bids.

GeM's search API only gives a bid-wide total quantity. For a bundled bid
("Desktop, MFP, Barcode Scanner") that total mixes computers with printers,
UPS units and so on. The real per-item quantities are only in the bid PDF
(showbidDocument/<id>), so this script downloads the PDF of every bundled bid
that is still on the dashboard, reads the item list, and caches the result in
bid_items.json. build_dashboard.py then shows exact desktop / laptop /
all-in-one / workstation / server counts.

Pure standard library: includes a small PDF text extractor that handles the
wkhtmltopdf/Qt PDFs GeM generates (Flate streams, Identity-H CID fonts with
ToUnicode maps). Not a general PDF reader.

    python gem_items.py            # fetch PDFs for bundles not yet cached
    python gem_items.py --test FILE.pdf   # print extracted text + items
Env:
    GEM_PDF_MAX (default 400)  max PDFs per run
    GEM_PDF_DELAY (default 0.6) seconds between downloads
    GEM_PDF_BUDGET (default 0 = none) stop after this many seconds
"""

import csv
import json
import os
import re
import sys
import time
import urllib.request
import zlib
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gem_bids_scraper as S  # noqa: E402
import gem_state  # noqa: E402
import gem_districts  # noqa: E402

CACHE_PATH = os.path.join(HERE, "bid_items.json")
PARSER_VERSION = 3          # bump to re-read every cached PDF after a parser change
KINDS = ["Desktop", "Laptop", "All-in-One", "Workstation", "Server"]


# --------------------------------------------------------------------------
# PDF text extraction (stdlib only)
# --------------------------------------------------------------------------

def _objects(data):
    objs = {}
    marks = [(m.start(), m.end(), int(m.group(1)))
             for m in re.finditer(rb"(\d+)\s+\d+\s+obj\b", data)]
    for k, (s, e, num) in enumerate(marks):
        end = data.find(b"endobj", e)
        if end < 0:
            end = marks[k + 1][0] if k + 1 < len(marks) else len(data)
        body = data[e:end]
        stream = None
        si = body.find(b"stream")
        if si >= 0 and body[:si].rstrip().endswith(b">>"):
            head = body[:si]
            raw = body[si + 6:]
            if raw[:2] == b"\r\n":
                raw = raw[2:]
            elif raw[:1] in (b"\n", b"\r"):
                raw = raw[1:]
            ei = raw.rfind(b"endstream")
            if ei >= 0:
                raw = raw[:ei]
            if b"/FlateDecode" in head:
                try:
                    raw = zlib.decompressobj().decompress(raw)
                except zlib.error:
                    raw = b""
            elif b"/Filter" in head:
                raw = b""          # images etc. - not needed
            body, stream = head, raw
        objs[num] = (body, stream)
    return objs


def _ref(body, key):
    m = re.search(rb"/" + key + rb"\s+(\d+)\s+\d+\s+R", body)
    return int(m.group(1)) if m else None


def _cmap(stream):
    m = {}
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", stream, re.S):
        for a, b in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            m[int(a, 16)] = bytes.fromhex(b.decode()).decode("utf-16-be", "ignore")
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", stream, re.S):
        for a, b, rest in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", blk):
            lo, hi = int(a, 16), int(b, 16)
            if rest.startswith(b"["):
                for i, h in enumerate(re.findall(rb"<([0-9A-Fa-f]+)>", rest)):
                    m[lo + i] = bytes.fromhex(h.decode()).decode("utf-16-be", "ignore")
            else:
                base = bytes.fromhex(rest[1:-1].decode())
                start = int.from_bytes(base, "big")
                for i in range(hi - lo + 1):
                    v = (start + i).to_bytes(len(base), "big")
                    m[lo + i] = v.decode("utf-16-be", "ignore")
    return m


def _mul(a, b):
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


_TOK = re.compile(rb"<([0-9A-Fa-f\s]*)>|\(((?:\\.|[^\\)])*)\)|/([^\s/\[\]()<>{}%]+)"
                  rb"|([-+]?(?:\d+\.?\d*|\.\d+))|([A-Za-z'\"*][A-Za-z0-9*]*)|(\[)|(\])", re.S)


def _page_glyphs(content, fonts):
    """Run a content stream; return glyphs as (x, y, size, adv, char)."""
    out = []
    ctm = (1, 0, 0, 1, 0, 0)
    stack = []
    tm = tlm = (1, 0, 0, 1, 0, 0)
    font, fsize = None, 12.0
    ops = []
    arr = None
    last = None                       # index of previous glyph in this run
    for m in _TOK.finditer(content):
        hx, lit, name, num, op, lb, rb = m.groups()
        if lb is not None:
            arr = []
            continue
        if rb is not None:
            ops.append(("arr", arr or []))
            arr = None
            continue
        if hx is not None:
            v = ("hex", re.sub(rb"\s", b"", hx))
        elif lit is not None:
            v = ("lit", lit)
        elif name is not None:
            v = ("name", name.decode("latin1"))
        elif num is not None:
            v = ("num", float(num))
        else:
            v = None
        if v is not None:
            (arr if arr is not None else ops).append(v)
            continue
        o = op.decode("latin1")
        nums = [x[1] for x in ops if x[0] == "num"]
        if o == "q":
            stack.append(ctm)
        elif o == "Q":
            ctm = stack.pop() if stack else (1, 0, 0, 1, 0, 0)
        elif o == "cm" and len(nums) >= 6:
            ctm = _mul(tuple(nums[-6:]), ctm)
        elif o == "BT":
            tm = tlm = (1, 0, 0, 1, 0, 0)
            last = None
        elif o == "Tf" and ops:
            nm = [x[1] for x in ops if x[0] == "name"]
            font = fonts.get(nm[-1]) if nm else None
            fsize = nums[-1] if nums else fsize
        elif o == "Tm" and len(nums) >= 6:
            tm = tlm = tuple(nums[-6:])
            last = None
        elif o in ("Td", "TD") and len(nums) >= 2:
            tlm = _mul((1, 0, 0, 1, nums[-2], nums[-1]), tlm)
            tm = tlm
        elif o == "T*":
            tlm = _mul((1, 0, 0, 1, 0, -fsize * 1.2), tlm)
            tm = tlm
            last = None
        elif o in ("Tj", "TJ", "'", '"'):
            strs = []
            for x in ops:
                if x[0] in ("hex", "lit"):
                    strs.append(x)
                elif x[0] == "arr":
                    strs += [y for y in x[1] if y[0] in ("hex", "lit")]
            full = _mul(tm, ctm)
            scale = (full[2] ** 2 + full[3] ** 2) ** 0.5 or 1.0
            size = fsize * scale
            x, y = full[4], full[5]
            for kind, s in strs:
                if kind == "hex":
                    codes = [int(s[i:i + 4], 16) for i in range(0, len(s), 4)]
                else:
                    codes = list(s)
                for c in codes:
                    ch = font.get(c, "") if font is not None else ""
                    if last is not None:
                        px, py, psz, padv, pch = out[last]
                        if padv is None and abs(py - y) < 0.3 * size and 0 < x - px < 1.5 * size:
                            out[last] = (px, py, psz, x - px, pch)
                    out.append((x, y, size, None, ch))
                    last = len(out) - 1
                    x += 0.55 * size      # only matters for multi-glyph strings
        ops = []
    return out


def pdf_text(data):
    """Plain-text rendering of a GeM bid PDF, roughly like pdftotext -layout."""
    objs = _objects(data)
    font_maps = {}

    def fonts_for(res_body):
        fm = re.search(rb"/Font\s*<<(.*?)>>", res_body, re.S)
        if not fm:
            r = _ref(res_body, b"Font")
            if r and r in objs:
                fm = re.search(rb"<<(.*)>>", objs[r][0], re.S)
        out = {}
        if fm:
            for nm, num in re.findall(rb"/([^\s/]+)\s+(\d+)\s+\d+\s+R", fm.group(1)):
                num = int(num)
                if num not in font_maps:
                    tu = _ref(objs.get(num, (b"", None))[0], b"ToUnicode")
                    st = objs.get(tu, (b"", None))[1] if tu else None
                    font_maps[num] = _cmap(st) if st else {}
                out[nm.decode("latin1")] = font_maps[num]
        return out

    # page order via the Pages tree
    trailer = data[data.rfind(b"trailer"):]
    root = _ref(trailer, b"Root")
    pages = []

    def walk(num, depth=0):
        if num not in objs or depth > 20:
            return
        body = objs[num][0]
        if re.search(rb"/Type\s*/Pages\b", body):
            km = re.search(rb"/Kids\s*\[(.*?)\]", body, re.S)
            for k in re.findall(rb"(\d+)\s+\d+\s+R", km.group(1) if km else b""):
                walk(int(k), depth + 1)
        elif re.search(rb"/Type\s*/Page\b", body):
            pages.append(num)

    if root and root in objs:
        walk(_ref(objs[root][0], b"Pages"))
    if not pages:
        pages = sorted(n for n, (b, _) in objs.items() if re.search(rb"/Type\s*/Page\b", b))

    lines_out = []
    for p in pages:
        body = objs[p][0]
        rm = re.search(rb"/Resources\s*(<<.*>>)", body, re.S)
        rr = _ref(body, b"Resources")
        res = rm.group(1) if rm else (objs.get(rr, (b"", None))[0] if rr else b"")
        fonts = fonts_for(res)
        cm = re.search(rb"/Contents\s*\[(.*?)\]", body, re.S)
        refs = ([int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", cm.group(1))] if cm
                else [_ref(body, b"Contents")])
        content = b"\n".join(objs.get(r, (b"", b""))[1] or b"" for r in refs if r)
        glyphs = [g for g in _page_glyphs(content, fonts) if g[4]]
        if not glyphs:
            continue
        left = min(g[0] for g in glyphs)
        glyphs.sort(key=lambda g: (-g[1], g[0]))
        rows, cur, cy = [], [], None
        for g in glyphs:
            if cy is not None and abs(g[1] - cy) > 0.45 * g[2]:
                rows.append(cur)
                cur = []
            if not cur:
                cy = g[1]
            cur.append(g)
        if cur:
            rows.append(cur)
        for row in rows:
            row.sort(key=lambda g: g[0])
            s = " " * max(0, int(round((row[0][0] - left) / 4.5)))
            prev = None
            for g in row:
                if prev is not None:
                    adv = prev[3] if prev[3] is not None else 0.55 * prev[2]
                    gap = g[0] - (prev[0] + adv)
                    if gap > 1.2 * g[2]:
                        s += " " * max(2, int(round(gap / (0.5 * g[2]))))
                    elif gap > 0.2 * g[2] and not s.endswith(" "):
                        s += " "
                s += g[4]
                prev = g
            lines_out.append(s.rstrip())
        lines_out.append("")
    return "\n".join(lines_out)


# --------------------------------------------------------------------------
# Item list parser
# --------------------------------------------------------------------------

_UNITS = (r"pieces?|units?|sets?|box(?:es)?|nos?\.?|numbers?|pairs?|lots?|each|kits?|"
          r"packs?|meters?|mtrs?")
_HDR = re.compile(r"^(.*?)\s*\(\s*(\d+)\s*(" + _UNITS + r")\s*\)\s*(\(\s*Under PAC\s*\))?\s*$", re.I)
_DEV = re.compile(r"[ऀ-ॿ]")
# consignee row: S.No, [officer / address], quantity, delivery days. The
# address cell can run right up to the quantity with a single space.
_ROW = re.compile(r"^\s{0,4}(\d{1,3})(?:\s{2,}.*?\S)?\s+(\d+)\s{2,}(\d+)\s*$")
# the item-section heading, e.g. "तकनीकी विशिष्टियाँ /Technical Specifications";
# NOT spec-table rows or prose that merely mention technical specifications
_TS = re.compile(r"/\s*Technical Specifications\s*$|^\s*Technical Specifications\s*$")
_ADDL = re.compile(r"Additional Specification Parameters", re.I)


def _skip(line):
    s = line.strip()
    return (not s or _DEV.search(s)
            or re.search(r"Local Content|Local Supplier|Class 1|respectively\)|^\d+\s*/\s*\d+$", s)
            or re.match(r"(Bis Required|Make|Model)\b", s)
            or re.search(r"\S\s{3,}\S", s))


def parse_items(txt):
    """Return (total_quantity or None, [(name, qty, [PIN states], [masked cities]), ...])."""
    L = txt.replace("\f", "\n").split("\n")
    total = None
    for line in L[:150]:
        m = re.search(r"Total Quantity\s+(\d+)", line)
        if m:
            total = int(m.group(1))
            break
    # a bare "Technical Specifications" line whose previous line is an indented
    # spec-table cell is wrapped table text, not a new item heading
    ts = [i for i, line in enumerate(L) if _TS.search(line)
          and ("/" in line or not (i and L[i - 1].startswith(" " * 10)))]
    items = []
    for k, t in enumerate(ts):
        lo = ts[k - 1] if k else 0
        name, hq, nj = None, None, t
        for j in range(t - 1, max(lo, t - 25), -1):
            s = L[j].strip()
            if _ADDL.search(s):
                continue    # belongs to the previous item's spec sheet
            m = _HDR.match(s)
            if not m and j - 1 > lo and len(s) < 30 and s.endswith(")"):
                # header wrapped onto two lines: "... ( 27" / "pieces )"
                m = _HDR.match(L[j - 1].strip() + " " + s)
                if m and m.group(1):
                    j -= 1
            if m and m.group(1):
                name, hq, nj = m.group(1).strip(), int(m.group(2)), j
                break
        if name is None:
            # custom/BOQ items: the name sits right above the "Local Content ...
            # Class 1 ... Local Supplier respectively)" note; other blocks (e.g.
            # Techno Commercial Criteria) can come between that note and the heading
            start = t - 1
            for j in range(t - 1, max(lo, t - 40), -1):
                if re.search(r"Local Supplier respectively\)", L[j]):
                    start = j - 1
                    break
            for j in range(start, max(lo, t - 45), -1):
                if not _skip(L[j]) and not _ADDL.search(L[j]):
                    name, nj = L[j].strip(), j
                    break
        if name is None:
            name = "?"
        p = L[nj - 1].rstrip() if nj else ""
        if (p and not p.startswith(" ") and not _skip(p) and not p.endswith(".")
                and len(p) < 100):
            name = p.strip() + " " + name
        hi = ts[k + 1] if k + 1 < len(ts) else len(L)
        cq, nrows, inc = 0, 0, False
        pins, cities = [], []
        for line in L[t:hi]:
            if "Consignees/Reporting" in line:
                inc = True
            elif inc and _END.search(line):
                inc = False     # terms & conditions after the table - no addresses
            if inc:
                m = _ROW.match(line)
                if m:
                    cq += int(m.group(2))
                    nrows += 1
                pins += _PIN.findall(line)
                cities += [c.strip() for c in _MASKED.findall(line)]
        if hq is None and nrows == 0 and re.search(r"ATC|Buyer Added", name):
            continue
        if _ADDL.search(name):
            continue        # extra spec sheet of the previous item, same quantity
        items.append((re.sub(r"\s+", " ", name), hq if hq is not None else cq,
                      sorted({pin_state(p) for p in pins} - {""}),
                      sorted({c for c in cities if c})))
    return total, items


# --------------------------------------------------------------------------
# Delivery states (from the consignee addresses)
# --------------------------------------------------------------------------

_PIN = re.compile(r"(?<![\d.])([1-8]\d{5})(?!\d)")
# masked addresses show only the city: "*****Amritsar"
_MASKED = re.compile(r"\*{5,}\s*([A-Za-z][A-Za-z .()-]*?)(?=\s*\d|\s{2,}|\s*$)")
_END = re.compile(r"Special terms and conditions|Buyer Added|Bid Specific|Disclaimer|"
                  r"Terms and Conditions", re.I)
_CITY = {"balasore": "Odisha", "ganjam": "Odisha", "gorakhpur": "Uttar Pradesh",
         "allahabad": "Uttar Pradesh", "prayagraj": "Uttar Pradesh",
         "jabalpur": "Madhya Pradesh", "amritsar": "Punjab", "faridkot": "Punjab",
         "ajmer": "Rajasthan", "thiruvallur": "Tamil Nadu", "kanchipuram": "Tamil Nadu",
         "burdwan": "West Bengal", "bardhaman": "West Bengal", "leh": "Ladakh",
         "kargil": "Ladakh", "aizawl": "Mizoram", "tawang": "Arunachal Pradesh",
         "kannur": "Kerala"}
_PIN2 = {11: "Delhi", 12: "Haryana", 13: "Haryana", 14: "Punjab", 15: "Punjab",
         16: "Punjab", 17: "Himachal Pradesh", 18: "Jammu & Kashmir",
         19: "Jammu & Kashmir", 30: "Rajasthan", 31: "Rajasthan", 32: "Rajasthan",
         33: "Rajasthan", 34: "Rajasthan", 36: "Gujarat", 37: "Gujarat", 38: "Gujarat",
         39: "Gujarat", 40: "Maharashtra", 41: "Maharashtra", 42: "Maharashtra",
         43: "Maharashtra", 44: "Maharashtra", 45: "Madhya Pradesh",
         46: "Madhya Pradesh", 47: "Madhya Pradesh", 48: "Madhya Pradesh",
         49: "Chhattisgarh", 51: "Andhra Pradesh", 52: "Andhra Pradesh",
         53: "Andhra Pradesh", 56: "Karnataka", 57: "Karnataka", 58: "Karnataka",
         59: "Karnataka", 60: "Tamil Nadu", 61: "Tamil Nadu", 62: "Tamil Nadu",
         63: "Tamil Nadu", 64: "Tamil Nadu", 67: "Kerala", 68: "Kerala", 69: "Kerala",
         70: "West Bengal", 71: "West Bengal", 72: "West Bengal", 73: "West Bengal",
         74: "West Bengal", 75: "Odisha", 76: "Odisha", 77: "Odisha", 78: "Assam",
         80: "Bihar", 81: "Bihar", 82: "Bihar", 83: "Bihar", 84: "Bihar", 85: "Bihar"}


def pin_state(p):
    """State for an Indian PIN code (first 2-3 digits = postal circle)."""
    n, a = int(p[:3]), int(p[:2])
    if n == 160:
        return "Chandigarh"
    if n in (246, 247, 248, 249, 262, 263):
        return "Uttarakhand"
    if n == 194:
        return "Ladakh"
    if n == 403:
        return "Goa"
    if n == 737:
        return "Sikkim"
    if n == 744:
        return "Andaman & Nicobar"
    if n == 605:
        return "Puducherry"
    if 790 <= n <= 792:
        return "Arunachal Pradesh"
    if n in (793, 794):
        return "Meghalaya"
    if n == 795:
        return "Manipur"
    if n == 796:
        return "Mizoram"
    if n in (797, 798):
        return "Nagaland"
    if n == 799:
        return "Tripura"
    if 813 <= n <= 816 or 825 <= n <= 835:
        return "Jharkhand"
    if 500 <= n <= 509:
        return "Telangana"
    if 20 <= a <= 28:
        return "Uttar Pradesh"
    return _PIN2.get(a, "")


def city_state(c):
    c = re.sub(r"\s+", " ", c.lower().strip(" .,-"))
    c = re.sub(r"^(district|distt?\.?)\s+|\s+(district|distt?\.?)$", "", c)
    return (_CITY.get(c) or gem_districts.DISTRICTS.get(c)
            or gem_state.state_from_text(c)[0])


def item_states(it):
    """Delivery states of one cached item [name, qty, pin_states, cities].
    Consignee PIN codes win; masked addresses only show a city/district,
    which is looked up on every build so map improvements apply to the cache."""
    if len(it) > 2 and it[2]:
        return list(it[2])
    return sorted({s for s in (city_state(c) for c in (it[3] if len(it) > 3 else [])) if s})


def bid_states(entry):
    """Sorted delivery states of a cached bid (empty if unknown)."""
    return sorted({s for it in entry.get("items", []) for s in item_states(it)})


# --------------------------------------------------------------------------
# What kind of computer is an item?
# --------------------------------------------------------------------------

_NOT_HW = re.compile(r"sql\s*server|windows\s*server|operating\s*system|licen[cs]e|software|"
                     r"virtual\s*machine|\bcloud\b|\d+\s*x\s*\d+\s*(ft|feet)\b|double\s*box")


def item_kind(name, siblings=()):
    """'Desktop' | 'Laptop' | 'All-in-One' | 'Workstation' | 'Server' | ''."""
    n = name.lower()
    if _NOT_HW.search(n):
        return ""
    if (re.search(r"work\s*station", n) and not re.search(S.COMPUTE_HINT, n)
            and any(re.search(S.FURNITURE_HINT, s.lower()) for s in siblings)):
        return ""
    b = S.classify(name)[0] or S.classify(name.replace(",", " "))[0]
    if not b and re.search(r"\bservers?\b", n) and re.search(r"\brack\s*$", n):
        b = "Server"        # "Enterprise Server Tower Or Rack" - the rack rule skips it
    if not b:
        return ""
    if b == "All-in-One PC":
        return "All-in-One"
    if b == "Desktop" and re.search(r"work\s*station", n):
        return "Workstation"
    return b


def counts_for(items):
    """{kind: qty} for a parsed item list."""
    names = [i[0] for i in items]
    out = {}
    for it in items:
        k = item_kind(it[0], names)
        if k:
            out[k] = out.get(k, 0) + it[1]
    return out


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def load_cache():
    try:
        return json.load(open(CACHE_PATH, encoding="utf8"))
    except (OSError, ValueError):
        return {"bids": {}}


def save_cache(cache):
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(cache, f, indent=0, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, CACHE_PATH)


def fetch_pdf(url, tries=3):
    err = None
    for i in range(tries):
        if i:
            time.sleep(4 * i)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": S.UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if data[:5] == b"%PDF-":
                return data
            err = "not a PDF ({} bytes)".format(len(data))
        except Exception as e:  # noqa: BLE001
            err = e
    raise RuntimeError(str(err))


def analyse(data):
    total, items = parse_items(pdf_text(data))
    s = sum(i[1] for i in items)
    ok = bool(items) and (total is None or s == total)
    return {"total": total, "items": [list(i) for i in items], "ok": ok, "v": PARSER_VERSION}


def wanted(rows, cache):
    """Bids in bids.csv (open and closed, bundled and single - the PDF gives
    the delivery states for all of them and exact item counts for bundles)
    whose PDF has not been read by the current parser version yet."""
    todo = []
    for r in rows:
        if not r.get("bid_url"):
            continue
        c = cache["bids"].get(r["bid_number"])
        if c and c.get("v", 0) >= PARSER_VERSION:
            continue
        todo.append(r)
    # still-open bids first, newest first
    today = datetime.now(timezone.utc).date().isoformat()
    todo.sort(key=lambda r: ((r.get("bid_end_date") or "9")[:10] >= today,
                             r.get("bid_start_date", "")), reverse=True)
    return todo


def main():
    try:
        sys.stdout.reconfigure(errors="replace")   # Windows console code pages
    except AttributeError:
        pass
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        data = open(sys.argv[2], "rb").read()
        txt = pdf_text(data)
        if "--text" in sys.argv:
            print(txt)
        total, items = parse_items(txt)
        print("total", total)
        for it in items:
            print("  {:>6}  {:<12} {}  [{}]".format(it[1], item_kind(it[0], [i[0] for i in items]) or "-",
                                                  it[0], ", ".join(item_states(it)) or "/".join(it[3])))
        print("counts", counts_for(items))
        return
    max_n = int(os.environ.get("GEM_PDF_MAX", "400"))
    delay = float(os.environ.get("GEM_PDF_DELAY", "0.6"))
    budget = float(os.environ.get("GEM_PDF_BUDGET", "0"))
    rows = list(csv.DictReader(open(S.CSV_PATH, newline="", encoding="utf8")))
    cache = load_cache()
    todo = wanted(rows, cache)
    print("bids needing a PDF read: {} (this run max {})".format(len(todo), max_n), flush=True)
    t0 = time.time()
    done = bad = failed = 0
    for r in todo[:max_n]:
        if budget and time.time() - t0 > budget:
            print("  time budget reached", flush=True)
            break
        bn = r["bid_number"]
        try:
            data = fetch_pdf(r["bid_url"])
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("  ! {} download failed: {}".format(bn, e), flush=True)
            time.sleep(delay)
            continue
        try:
            res = analyse(data)
        except Exception as e:  # noqa: BLE001
            res = {"total": None, "items": [], "ok": False, "v": PARSER_VERSION,
                   "err": str(e)[:200]}
        res["on"] = datetime.now(timezone.utc).date().isoformat()
        cache["bids"][bn] = res
        done += 1
        if not res["ok"]:
            bad += 1
            print("  ? {} items did not add up ({} items, total {})".format(
                bn, len(res["items"]), res["total"]), flush=True)
        if done % 25 == 0:
            save_cache(cache)
            print("  ... {} read".format(done), flush=True)
        time.sleep(delay)
    save_cache(cache)
    print("PDFs read: {}, not reconciled: {}, download failed: {}, left for next run: {}".format(
        done, bad, failed, max(0, len(todo) - done - failed)), flush=True)


if __name__ == "__main__":
    main()

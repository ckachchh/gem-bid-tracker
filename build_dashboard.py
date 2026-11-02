#!/usr/bin/env python3
"""Reads bids.json and writes a self-contained dashboard.html with data embedded."""
import json
import os
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, "bids.json"), encoding="utf8"))
ALL_ROWS = DATA["rows"]

# The page carries the whole history in bids.json (open and closed bids, every
# month) so older months can be browsed and charted. GEM_CLOSED_GRACE_DAYS > 0
# drops bids closed longer ago than that, if the page ever gets too big.
CLOSED_GRACE_DAYS = int(os.environ.get("GEM_CLOSED_GRACE_DAYS", "0"))
_today = datetime.now(timezone.utc).date()
_cutoff = (_today - timedelta(days=CLOSED_GRACE_DAYS)).isoformat()


def _still_relevant(r):
    end = (r.get("bid_end_date") or "")[:10]
    if not CLOSED_GRACE_DAYS or not end:
        return True
    return end >= _cutoff


ROWS = [r for r in ALL_ROWS if _still_relevant(r)]
DROPPED = len(ALL_ROWS) - len(ROWS)

# Exact computer counts per kind. Single-product bids: the API quantity is
# that product's quantity. Bundled bids: the API only has a bid-wide total, so
# use the per-item quantities gem_items.py read from the bid PDF
# (bid_items.json). Kinds are recomputed here on every build, so rule changes
# apply to already-cached bids too.
import re  # noqa: E402
import gem_items  # noqa: E402

KINDS = gem_items.KINDS          # Desktop, Laptop, All-in-One, Workstation, Server
_CAT2KIND = {"Desktop": "Desktop", "Laptop": "Laptop",
             "All-in-One PC": "All-in-One", "Server": "Server"}
try:
    PDF_ITEMS = json.load(open(os.path.join(HERE, "bid_items.json"), encoding="utf8"))["bids"]
except (OSError, ValueError, KeyError):
    PDF_ITEMS = {}


def kind_counts(r):
    """[desktop, laptop, aio, workstation, server] or None if not known yet."""
    if str(r.get("is_bundle")) == "1":
        c = PDF_ITEMS.get(r.get("bid_number"))
        if not c or not c.get("ok"):
            return None
        d = gem_items.counts_for(c["items"])
    else:
        k = _CAT2KIND.get(r.get("category"), "")
        if k == "Desktop" and re.search(r"work\s*station", (r.get("item") or "").lower()):
            k = "Workstation"
        try:
            q = int(float(r.get("quantity") or 0))
        except ValueError:
            q = 0
        d = {k: q} if k else {}
    return [d.get(k, 0) for k in KINDS]


# Trim the embedded payload. bid_url is a constant prefix + id, and the
# verbose "item" string is only needed as a tooltip on bundled rows.
URL_PREFIX = "https://bidplus.gem.gov.in/showbidDocument/"
_slim = []
N_PDF = N_UNREAD = N_STATES = 0
for r in ROWS:
    o = {
        "b": r.get("bid_number", ""),
        "i": (r.get("bid_url") or "").replace(URL_PREFIX, ""),
        "c": r.get("category", ""),
        "m": r.get("matched_items") or r.get("item", ""),
        "d": r.get("department", ""),
        "y": r.get("ministry", ""),
        "s": r.get("state", ""),
        "q": r.get("quantity", ""),
        "e": (r.get("bid_end_date") or "")[:10],
        "t": (r.get("bid_start_date") or "")[:10],
        "a": r.get("captured_on", ""),
        "mo": (r.get("bid_start_date") or "")[:7],
    }
    if str(r.get("is_bundle")) == "1":
        o["n"] = r.get("n_items", "")
        full = r.get("item", "")
        if full != o["m"]:
            o["f"] = full
    pc = PDF_ITEMS.get(r.get("bid_number")) or {}
    _st = gem_items.bid_states(pc) if pc else []
    if _st:
        o["ss"] = _st            # delivery states from the consignee addresses
        N_STATES += 1
    kc = kind_counts(r)
    if kc is not None:
        o["k"] = kc
        if o.get("n"):
            o["x"] = 1           # counted from the bid PDF
            N_PDF += 1
    elif o.get("n"):
        N_UNREAD += 1
    _slim.append(o)
ROWS = _slim

# Chart data: per bid-start day, [bids, desktop, laptop, aio, workstation,
# server] over the whole history, independent of the table filters. A bid is
# counted under its main kind (largest count, else its category).
_C2K_IDX = {"Desktop": 0, "Laptop": 1, "All-in-One PC": 2, "Server": 4}
CHART = {}
for r in ROWS:
    d = r.get("t") or ""
    if not d:
        continue
    a = CHART.setdefault(d, [0] * 11)    # bids by kind (0-4, 5 = none) + computers (6-10)
    k = r.get("k")
    if k and sum(k):
        main = max(range(5), key=lambda i: k[i])
    elif k:
        main = 5
    else:
        main = _C2K_IDX.get(r.get("c"), 5)
        if main == 0 and re.search(r"work\s*station", (r.get("m") or "").lower()):
            main = 3
    a[main] += 1
    for i, v in enumerate(k or []):
        a[6 + i] += v

TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GeM IT Hardware Bids</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:#f6f7f9;color:#1a1d21;
 font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:28px 24px 60px}
h1{font-size:23px;font-weight:650;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:#6b7280;font-size:13px;margin-bottom:22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.card{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px}
.card .n{font-size:26px;font-weight:650;letter-spacing:-.02em}
.card .l{font-size:11.5px;color:#6b7280;text-transform:uppercase;letter-spacing:.06em;margin-top:2px}
.panel{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:16px;margin-bottom:20px}
.chead{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:8px}
.ctitle{font-size:12.5px;font-weight:600;color:#525a63;margin-right:auto}
.seg{display:inline-flex;border:1px solid #d6dae0;border-radius:7px;overflow:hidden}
.seg button{border:0;background:#fff;padding:5px 11px;font-size:12px;cursor:pointer;color:#334155}
.seg button+button{border-left:1px solid #d6dae0}
.seg button.on{background:#1a1d21;color:#fff}
.chartbox{position:relative;height:220px}
.chartbox svg{display:block;width:100%;height:100%}
.chartbox .bar:hover{opacity:.85}
.ctip{position:absolute;pointer-events:none;background:#1a1d21;color:#fff;font-size:12px;
 line-height:1.45;padding:7px 10px;border-radius:7px;white-space:nowrap;display:none;z-index:2}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:11.5px;color:#525a63;margin-top:6px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.more td{text-align:center;color:#525a63;font-size:12.5px;padding:12px;background:#fafbfc}
.st+.st{margin-left:3px}
.st.pdf-st{background:#e8f1ec;color:#1f5133}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px}
input[type=search],select{padding:7px 11px;border:1px solid #d6dae0;border-radius:7px;
 font-size:13px;background:#fff;min-width:150px}
input[type=search]{flex:1;min-width:220px}
.chip{padding:6px 12px;border:1px solid #d6dae0;background:#fff;border-radius:99px;
 font-size:12.5px;cursor:pointer;user-select:none}
.chip.on{background:#1a1d21;color:#fff;border-color:#1a1d21}
table{width:100%;border-collapse:collapse;background:#fff;
 border:1px solid #e3e6ea;border-radius:10px;overflow:hidden}
th{background:#f0f2f4;text-align:left;font-size:11.5px;text-transform:uppercase;
 letter-spacing:.05em;color:#525a63;padding:10px 12px;cursor:pointer;white-space:nowrap}
th:hover{background:#e7eaed}
td{padding:11px 12px;border-top:1px solid #eef0f2;vertical-align:top}
tr:hover td{background:#fafbfc}
a{color:#1d4ed8;text-decoration:none}
a:hover{text-decoration:underline}
.tag{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11.5px;font-weight:500}
.t-Desktop{background:#e0edff;color:#1e429f}
.t-Laptop{background:#e3f6e8;color:#1a6c37}
.t-Server{background:#fdeade;color:#9a4a12}
.t-AIO{background:#f0e6fb;color:#5b2a91}
.t-Workstation{background:#dcf4f1;color:#0f5e57}
.t-none{background:#f1f2f4;color:#6b7280}
.tag+.tag{margin-left:4px}
.kinds{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:8px}
.kinds .card{border-left:4px solid #ccc}
.kinds .c-Desktop{border-left-color:#3b74d6}.kinds .c-Laptop{border-left-color:#2f9a55}
.kinds .c-AIO{border-left-color:#8a55c7}.kinds .c-Workstation{border-left-color:#1b8f84}
.kinds .c-Server{border-left-color:#d4732c}
.knote{color:#6b7280;font-size:12px;margin:0 2px 20px}
.brk{font-size:11.5px;color:#525a63;font-weight:400;white-space:nowrap}
.pdf{font-size:11px;color:#6b7280;font-weight:400;white-space:nowrap}
.qty{font-variant-numeric:tabular-nums;font-weight:600}
.dept{font-size:12.5px}
.min{color:#6b7280;font-size:11.5px}
.matched{font-size:12.5px;color:#1a1d21;margin-top:2px}
.bundle{display:inline-block;margin-top:4px;background:#fff8e6;border:1px solid #f0dc9a;color:#7a5c00;font-size:11px;padding:2px 7px;border-radius:5px;cursor:help}
.approx{color:#b45309;font-weight:700;margin-left:2px;cursor:help}
.st{display:inline-block;background:#eef2f6;color:#334155;padding:2px 8px;border-radius:10px;font-size:11.5px;white-space:nowrap}
.central{color:#9aa3ad;font-size:11.5px;font-style:italic;cursor:help}
.mrow td{background:#f0f2f4;cursor:pointer;padding:10px 12px;font-size:13.5px;
 border-top:1px solid #dfe3e8;user-select:none}
.mrow:hover td{background:#e7eaed}
.mrow .caret{display:inline-block;width:14px;color:#6b7280}
.mcount{color:#6b7280;font-size:12px;margin-left:10px;font-weight:400}
.empty{padding:40px;text-align:center;color:#6b7280}
.note{color:#6b7280;font-size:12px;margin:12px 2px 0;line-height:1.6}
.new{background:#fff5d6;border:1px solid #f0dc9a;color:#7a5c00;
 padding:2px 7px;border-radius:5px;font-size:11px;margin-left:6px}
</style></head><body><div class="wrap">
<h1>GeM Bids — Desktops, Laptops, All-in-One PCs &amp; Servers</h1>
<div class="sub">Source: bidplus.gem.gov.in/all-bids · Updated __UPDATED__</div>

<div class="cards">
 <div class="card"><div class="n" id="kTotal">0</div><div class="l">Bids tracked</div></div>
 <div class="card"><div class="n" id="kToday">0</div><div class="l">Starting today</div></div>
 <div class="card"><div class="n" id="kClosing">0</div><div class="l">Closing in 7 days</div></div>
 <div class="card"><div class="n" id="kQty">0</div><div class="l">Computers</div></div>
 <div class="card"><div class="n" id="kAdded">0</div><div class="l">Added today</div></div>
 <div class="card"><div class="n" id="kState">0</div><div class="l">States</div></div>
</div>
<div class="kinds">
 <div class="card c-Desktop"><div class="n" id="k0">0</div><div class="l">Desktops</div></div>
 <div class="card c-Laptop"><div class="n" id="k1">0</div><div class="l">Laptops</div></div>
 <div class="card c-AIO"><div class="n" id="k2">0</div><div class="l">All-in-Ones</div></div>
 <div class="card c-Workstation"><div class="n" id="k3">0</div><div class="l">Workstations</div></div>
 <div class="card c-Server"><div class="n" id="k4">0</div><div class="l">Servers</div></div>
</div>
<p class="knote" id="knote"></p>

<div class="panel">
 <div class="chead">
  <span class="ctitle" id="ctitle"></span>
  <span class="seg" id="cview"><button data-v="day">Daily</button><button data-v="month">Monthly</button></span>
  <span class="seg" id="cmetric"><button data-v="bids">Bids</button><button data-v="comp">Computers</button></span>
 </div>
 <div class="chartbox" id="chartbox"><svg id="chart"></svg><div class="ctip" id="ctip"></div></div>
 <div class="legend" id="legend"></div>
</div>

<div class="panel">
 <div class="controls">
  <input type="search" id="q" placeholder="Search bid number, department or item…">
  <span class="chip on" data-cat="all">All</span>
  <span class="chip" data-cat="Desktop">Desktop</span>
  <span class="chip" data-cat="Laptop">Laptop</span>
  <span class="chip" data-cat="All-in-One">All-in-One</span>
  <span class="chip" data-cat="Workstation">Workstation</span>
  <span class="chip" data-cat="Server">Server</span>
  <select id="range">
   <option value="0">Any date</option>
   <option value="added">Added today</option>
   <option value="1">Starting today</option>
   <option value="7">Started last 7 days</option>
   <option value="30">Started last 30 days</option>
  </select>
  <select id="state"><option value="all">All states</option></select>
  <select id="minq">
   <option value="0">Any quantity</option>
   <option value="5">5+ computers</option>
   <option value="20">20+ computers</option>
   <option value="50">50+ computers</option>
   <option value="100">100+ computers</option>
  </select>
  <select id="status">
   <option value="open">Open bids only</option>
   <option value="closing">Closing within 7 days</option>
   <option value="all">Include closed</option>
  </select>
  <select id="bundle">
   <option value="all">All bids</option>
   <option value="single">Single-product only</option>
   <option value="bundle">Bundled only</option>
  </select>
 </div>
 <table><thead><tr>
  <th data-k="b">Bid Number</th>
  <th data-k="c">Type</th>
  <th data-k="d">Department</th>
  <th data-k="s">State</th>
  <th data-k="q">Computers</th>
  <th data-k="t">Bid Start Date</th>
  <th data-k="e">Closes</th>
  <th data-k="a">Added</th>
 </tr></thead><tbody id="tb"></tbody></table>
 <div class="empty" id="empty" style="display:none">No bids match these filters.</div>
 <p class="note"><b>Reading this table.</b> The line under each bid number shows only the
 items that matched your categories &mdash; not the full bid contents. A <b>bundled bid</b> badge
 means GeM packaged several products into one tender; hover it to see everything included.
 <b>Computers</b> is the exact number of desktops, laptops, all-in-ones, workstations and servers in
 the bid. For single-product bids that is GeM&rsquo;s quantity. For bundled bids GeM only publishes
 a bid-wide total covering every line item (printers, UPS, furniture&hellip;), so the tracker reads
 the item list from the bid PDF and counts only the computers; the bid-wide total is shown
 underneath. A bundled bid whose PDF has not been read yet shows the bid-wide total with an
 asterisk<span class="approx">*</span> and is left out of the per-type totals. The quantity filter
 and the type chips use these computer counts, so a bundle that turns out to contain no computers
 drops out of the default 5+ view. &ldquo;Bid Start Date&rdquo; is when bidding opens, not the document
 publication date. Reverse auctions are excluded &mdash; only open tenders are listed. Bids are grouped by month &mdash; click a month to expand or collapse it. The view defaults to <b>open bids of 5+ units</b> &mdash; single-unit tenders are hidden by default. Use the quantity and status filters to widen it. The page holds the whole history
 (__ALLN__ bids, also in <a href="bids.csv">bids.csv</a>): choose <b>Include closed</b> to see closed bids and
 earlier months, or click a month in the monthly chart.
 <b>State</b> (green) is where the goods are delivered &mdash; read from the consignee addresses in the bid PDF, so
 one bid can list several states. Where the PDF has not been read yet the state (grey) is guessed from the buyer&rsquo;s
 department name, and <i>central</i> means a national body such as Military Affairs or Indian Railways.</p>
</div>
</div>
<script>
const ROWS = __ROWS__;
const URLP='https://bidplus.gem.gov.in/showbidDocument/';
const CHART = __CHART__;   // day -> [bids by kind x6, computers by kind x5]
const TODAY = new Date().toISOString().slice(0,10);
const KN=['Desktop','Laptop','All-in-One','Workstation','Server'];
const C2K={'Desktop':'Desktop','Laptop':'Laptop','All-in-One PC':'All-in-One','Server':'Server'};
// computers in the bid: exact when known, else the bid-wide total (unread bundle)
function cq(r){return r.k? r.k.reduce((a,b)=>a+b,0) : (+r.q||0);}
// delivery states from the bid PDF, else the state guessed from the department
function sts(r){return r.ss || (r.s?[r.s]:[]);}
let cat = localStorage.getItem('gem_cat') || 'all';
if(cat==='All-in-One PC') cat='All-in-One';
let sortK = 't', sortDir = -1;

document.querySelectorAll('.chip').forEach(c=>{
  c.classList.toggle('on', c.dataset.cat===cat);
  c.onclick=()=>{cat=c.dataset.cat;localStorage.setItem('gem_cat',cat);
    document.querySelectorAll('.chip').forEach(x=>x.classList.toggle('on',x.dataset.cat===cat));render();};
});
document.getElementById('q').oninput=render;
document.getElementById('range').onchange=render;
document.getElementById('bundle').onchange=render;
document.getElementById('status').onchange=()=>{openMonths=null;render();};
const mq=document.getElementById('minq');
mq.value=localStorage.getItem('gem_minq')||'5';
mq.onchange=()=>{localStorage.setItem('gem_minq',mq.value);render();};
const stSel=document.getElementById('state');
[...new Set(ROWS.flatMap(sts))].sort().forEach(st=>{
  const o=document.createElement('option');o.value=st;o.textContent=st;stSel.appendChild(o);});
{const o=document.createElement('option');o.value='__central';o.textContent='Central bodies';stSel.appendChild(o);}
stSel.onchange=render;
document.querySelectorAll('th').forEach(th=>th.onclick=()=>{
  const k=th.dataset.k; sortDir = (k===sortK)? -sortDir : -1; sortK=k; render();});

function filtered(ignoreStatus){
  const q=document.getElementById('q').value.toLowerCase().trim();
  const rangeVal=document.getElementById('range').value;
  const addedOnly = rangeVal==='added';
  const bundleVal=document.getElementById('bundle').value;
  const stat=document.getElementById('status').value;
  const minq=+document.getElementById('minq').value||0;
  const soon=new Date(Date.now()+7*864e5).toISOString().slice(0,10);
  const stVal=document.getElementById('state').value;
  const days = addedOnly ? 0 : +rangeVal;
  let cut=null;
  if(days){const d=new Date();d.setDate(d.getDate()-(days-1));cut=d.toISOString().slice(0,10);}
  return ROWS.filter(r=>{
    if(cat!=='all'){
      if(r.k){ if(!(r.k[KN.indexOf(cat)]>0)) return false; }
      else if(C2K[r.c]!==cat) return false;
    }
    if(stVal==='__central' && sts(r).length) return false;
    if(stVal!=='all' && stVal!=='__central' && !sts(r).includes(stVal)) return false;
    if(minq && cq(r) < minq) return false;
    if(!ignoreStatus && stat==='open'    && (r.e||'') < TODAY) return false;
    if(!ignoreStatus && stat==='closing' && !((r.e||'') >= TODAY && (r.e||'') <= soon)) return false;
    if(bundleVal==='single' && r.n) return false;
    if(bundleVal==='bundle' && !r.n) return false;
    if(addedOnly && (r.a||'')!==TODAY) return false;
    if(cut && (r.t||'') < cut) return false;
    if(q && !((r.b+' '+r.d+' '+r.y+' '+r.m+' '+sts(r).join(' ')).toLowerCase().includes(q))) return false;
    return true;
  }).sort((a,b)=>{
    let x=a[sortK]??'', y=b[sortK]??'';
    if(sortK==='q'){return (cq(a)-cq(b))*sortDir;}
    return String(x).localeCompare(String(y))*sortDir;
  });
}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
const MONTHNAMES=['January','February','March','April','May','June','July',
  'August','September','October','November','December'];
function monthLabel(mo){
  if(!mo) return 'Undated';
  const [y,m]=mo.split('-');
  return MONTHNAMES[(+m)-1]+' '+y;
}
let openMonths=JSON.parse(localStorage.getItem('gem_openmo')||'null');

function stateHtml(r){
  if(r.ss){
    const t='Delivery state'+(r.ss.length>1?'s':'')+' of the consignees in the bid PDF';
    const shown=r.ss.slice(0,3).map(x=>`<span class="st pdf-st" title="${t}">${esc(x)}</span>`).join('');
    return shown+(r.ss.length>3?`<span class="st pdf-st" title="${esc(r.ss.join(', '))}">+${r.ss.length-3}</span>`:'');
  }
  return r.s?`<span class="st" title="Guessed from the buyer&rsquo;s department name (bid PDF not read yet)">${esc(r.s)}</span>`
            :'<span class="central" title="Central / national body and the bid PDF has not been read yet">central</span>';
}

function rowHtml(r){
    const isNew=(r.t||'')===TODAY;
    const isNewToday=(r.a||'')===TODAY;
    const kcls=k=>'t-'+(k==='All-in-One'?'AIO':k);
    let typeHtml, qtyHtml;
    if(r.k){
      const parts=KN.map((k,i)=>[k,r.k[i]]).filter(p=>p[1]>0);
      const tot=cq(r);
      typeHtml = parts.length ? parts.map(p=>`<span class="tag ${kcls(p[0])}">${p[0]}</span>`).join('')
                              : '<span class="tag t-none" title="The bid PDF lists no desktop, laptop, all-in-one, workstation or server">no computers</span>';
      const brk = (parts.length>1 || r.n) && parts.length
        ? `<div class="brk">${parts.map(p=>p[1].toLocaleString()+' '+p[0]).join(' &middot; ')}</div>` : '';
      const pdf = r.n ? `<div class="pdf" title="Counted from the item list in the bid PDF">of ${esc(r.q)} in bid (PDF)</div>` : '';
      qtyHtml = `${tot.toLocaleString()}${brk}${pdf}`;
    } else {
      typeHtml = `<span class="tag ${kcls(C2K[r.c]||r.c)}">${esc(C2K[r.c]||r.c)}</span>`;
      qtyHtml = `${esc(r.q)}<span class="approx" title="Bid-wide total across all line items - the bid PDF has not been read yet, so the computer count is not known">*</span>`;
    }
    return `<tr>
      <td><a href="${URLP}${esc(r.i)}" target="_blank" rel="noopener">${esc(r.b)}</a>${isNew?'<span class="new">new</span>':''}
<div class="matched">${esc(r.m)}</div>
          ${r.n?`<div class="bundle" title="Full bid contents: ${esc(r.f||r.m)}">bundled bid &middot; ${esc(r.n)} line items</div>`:''}</td>
      <td>${typeHtml}</td>
      <td><div class="dept">${esc(r.d)}</div><div class="min">${esc(r.y)}</div></td>
      <td>${stateHtml(r)}</td>
      <td class="qty">${qtyHtml}</td>
      <td>${esc(r.t)}</td>
      <td>${esc(r.e)}</td>
      <td>${esc(r.a)}${isNewToday?'<span class="new">new</span>':''}</td></tr>`;
}

// how many bids the status filter hides (closed bids / earlier months)
function moreHtml(shown){
  if(document.getElementById('status').value==='all') return '';
  const all=filtered(true), n=all.length-shown;
  if(n<=0) return '';
  const mos=new Set(all.filter(r=>(r.e||'')<TODAY).map(r=>r.mo)).size;
  return `<tr class="more"><td colspan="8">${n.toLocaleString()} closed bid${n>1?'s':''} matching the other filters
    (${mos} month${mos>1?'s':''}) ${n>1?'are':'is'} hidden &mdash; <a href="#" id="showClosed">include closed bids</a></td></tr>`;
}

function render(){
  const rows=filtered();
  // group by month, newest first
  const groups=new Map();
  rows.forEach(r=>{const k=r.mo||'';if(!groups.has(k))groups.set(k,[]);groups.get(k).push(r);});
  const keys=[...groups.keys()].sort().reverse();
  if(openMonths===null) openMonths=[];   // all collapsed: page opens as a month summary
  document.getElementById('tb').innerHTML = keys.map(k=>{
    const g=groups.get(k);
    const isOpen=openMonths.includes(k);
    const qty=g.reduce((s,r)=>s+(r.k?cq(r):0),0);
    const unread=g.filter(r=>!r.k).length;
    const head=`<tr class="mrow" data-mo="${esc(k)}"><td colspan="8">
        <span class="caret">${isOpen?'&#9662;':'&#9656;'}</span>
        <b>${esc(monthLabel(k))}</b>
        <span class="mcount">${g.length} bid${g.length>1?'s':''} &middot; ${qty.toLocaleString()} computers${unread?` + ${unread} unread bundle${unread>1?'s':''}`:''}</span>
      </td></tr>`;
    return head + (isOpen ? g.map(rowHtml).join('') : '');
  }).join('') + moreHtml(rows.length);
  const sc=document.getElementById('showClosed');
  if(sc) sc.onclick=e=>{e.preventDefault();const st=document.getElementById('status');st.value='all';st.onchange();};
  document.querySelectorAll('.mrow').forEach(tr=>{
    tr.onclick=()=>{
      const k=tr.dataset.mo;
      openMonths = openMonths.includes(k) ? openMonths.filter(x=>x!==k) : openMonths.concat([k]);
      localStorage.setItem('gem_openmo',JSON.stringify(openMonths));
      render();
    };
  });
  document.getElementById('empty').style.display = rows.length?'none':'block';
  const soon2=new Date(Date.now()+7*864e5).toISOString().slice(0,10);
  document.getElementById('kTotal').textContent=rows.length;
  document.getElementById('kToday').textContent=rows.filter(r=>(r.t||'')===TODAY).length;
  document.getElementById('kClosing').textContent=rows.filter(r=>(r.e||'')>=TODAY&&(r.e||'')<=soon2).length;
  const kt=[0,0,0,0,0];
  rows.forEach(r=>{if(r.k) r.k.forEach((v,i)=>kt[i]+=v);});
  kt.forEach((v,i)=>document.getElementById('k'+i).textContent=v.toLocaleString());
  document.getElementById('kQty').textContent=kt.reduce((a,b)=>a+b,0).toLocaleString();
  const ur=rows.filter(r=>!r.k), pdfN=rows.filter(r=>r.x).length;
  document.getElementById('knote').innerHTML =
    'Exact unit counts for the bids shown below'
    + (pdfN?` &mdash; ${pdfN} bundled bid${pdfN>1?'s':''} counted from the bid PDF`:'')
    + (ur.length?`. <b>${ur.length}</b> bundled bid${ur.length>1?'s are':' is'} not read yet (bid-wide total ${ur.reduce((s,r)=>s+(+r.q||0),0).toLocaleString()} units, marked <span class="approx">*</span>) and not included.`:'.');
  document.getElementById('kAdded').textContent=rows.filter(r=>(r.a||'')===TODAY).length;
  document.getElementById('kState').textContent=new Set(rows.flatMap(sts)).size;
}
render();
// ---- bar chart (plain SVG, no library) ----
const KCOL=['#3b74d6','#2f9a55','#8a55c7','#1b8f84','#d4732c','#b8bfc8'];
const KLAB=['Desktop','Laptop','All-in-One','Workstation','Server','No computers / PDF not read'];
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
let cview=localStorage.getItem('gem_cview')||'day', cmetric=localStorage.getItem('gem_cmetric')||'bids';
let CD=null;
function isoAdd(d,n){const x=new Date(d+'T00:00:00Z');x.setUTCDate(x.getUTCDate()+n);return x.toISOString().slice(0,10);}
function chartData(){
  const keys=Object.keys(CHART).sort();
  const pick=a=>cmetric==='bids'? a.slice(0,6) : a.slice(6,11).concat([0]);
  const labels=[], vals=[], ids=[];
  if(!keys.length) return {labels,vals,ids};
  if(cview==='day'){
    const end=keys[keys.length-1]>TODAY? keys[keys.length-1] : TODAY;
    let start=isoAdd(end,-59);
    if(keys[0]>start) start=keys[0]<isoAdd(end,-29)? keys[0] : isoAdd(end,-29);
    for(let d=start; d<=end; d=isoAdd(d,1)){
      ids.push(d); vals.push(CHART[d]?pick(CHART[d]):[0,0,0,0,0,0]);
      const [y,m,dd]=d.split('-'); labels.push((+dd)+' '+MON[m-1]);
    }
  } else {
    const agg={};
    keys.forEach(d=>{const mo=d.slice(0,7);const p=pick(CHART[d]);
      agg[mo]=agg[mo]?agg[mo].map((v,i)=>v+p[i]):p;});
    const last=keys[keys.length-1].slice(0,7);
    let [y,m]=keys[0].slice(0,7).split('-').map(Number);
    const [ly,lm]=last.split('-').map(Number);
    if((ly-y)*12+(lm-m)>23){y=ly-2;m=lm+1;if(m>12){m-=12;y++;}}   // cap at 24 months
    while(y<ly||(y===ly&&m<=lm)){
      const mo=y+'-'+String(m).padStart(2,'0');
      ids.push(mo); vals.push(agg[mo]||[0,0,0,0,0,0]); labels.push(MON[m-1]+' '+String(y).slice(2));
      m++; if(m>12){m=1;y++;}
    }
  }
  return {labels,vals,ids};
}
function niceStep(mx){
  const raw=Math.max(1,mx)/4, p=Math.pow(10,Math.floor(Math.log10(raw)));
  for(const f of [1,2,2.5,5,10]) if(f*p>=raw) return Math.max(1,f*p);
  return 10*p;
}
function drawChart(){
  const box=document.getElementById('chartbox'), svg=document.getElementById('chart');
  document.querySelectorAll('#cview button').forEach(b=>b.classList.toggle('on',b.dataset.v===cview));
  document.querySelectorAll('#cmetric button').forEach(b=>b.classList.toggle('on',b.dataset.v===cmetric));
  CD=chartData();
  const W=box.clientWidth||900, H=box.clientHeight||220, L=46, R=8, T=10, B=24;
  const n=CD.vals.length, tot=CD.vals.map(v=>v.reduce((a,b)=>a+b,0));
  const step=niceStep(Math.max(0,...tot)), ymax=step*Math.max(1,Math.ceil(Math.max(0,...tot)/step));
  const pw=W-L-R, ph=H-T-B, band=pw/Math.max(1,n), bw=Math.max(2,Math.min(46,band*0.72));
  const y=v=>T+ph-v/ymax*ph;
  let h='';
  for(let v=0; v<=ymax+1e-9; v+=step){
    h+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="${v?'#eef0f2':'#d6dae0'}"/>`
      +`<text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="10.5" fill="#6b7280">${v.toLocaleString()}</text>`;
  }
  const every=Math.max(1,Math.ceil(n/(pw/52)));
  CD.vals.forEach((v,i)=>{
    const x=L+band*i+(band-bw)/2;
    let acc=0;
    v.forEach((q,k)=>{ if(!q) return;
      h+=`<rect class="bar" x="${x}" y="${y(acc+q)}" width="${bw}" height="${Math.max(0,y(acc)-y(acc+q))}" fill="${KCOL[k]}"/>`;
      acc+=q;});
    const isT=CD.ids[i]===TODAY||CD.ids[i]===TODAY.slice(0,7);
    if(i%every===0||isT&&cview==='month')
      h+=`<text x="${L+band*i+band/2}" y="${H-7}" text-anchor="middle" font-size="10.5" fill="${isT?'#1a1d21':'#6b7280'}"${isT?' font-weight="600"':''}>${CD.labels[i]}</text>`;
    h+=`<rect class="hit" data-i="${i}" x="${L+band*i}" y="${T}" width="${band}" height="${ph}" fill="transparent"${cview==='month'?' style="cursor:pointer"':''}/>`;
  });
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  svg.innerHTML=h;
  const span = cview==='day' ? `per day, ${CD.ids[0]?CD.labels[0]:''} – ${CD.labels[n-1]||''}` : 'per month';
  document.getElementById('ctitle').textContent=(cmetric==='bids'?'Bids':'Computers in bids')
    +' by bid start date, '+span+' · all tracked bids (not affected by the filters below)';
  const ks=cmetric==='bids'?[0,1,2,3,4,5]:[0,1,2,3,4];
  document.getElementById('legend').innerHTML=ks.map(k=>`<span><i style="background:${KCOL[k]}"></i>${KLAB[k]}</span>`).join('')
    +(cmetric==='bids'?'<span>· a bid is counted under its main computer type</span>':'<span>· unread bundles not included</span>')
    +(cview==='month'?'<span>· click a month to open it below</span>':'');
  svg.querySelectorAll('.hit').forEach(r=>{
    r.onmousemove=e=>showTip(+r.dataset.i,e);
    r.onmouseleave=()=>{document.getElementById('ctip').style.display='none';};
    if(cview==='month') r.onclick=()=>openMonth(CD.ids[+r.dataset.i]);
  });
}
function showTip(i,e){
  const tip=document.getElementById('ctip'), box=document.getElementById('chartbox');
  const v=CD.vals[i], t=v.reduce((a,b)=>a+b,0);
  const unit=cmetric==='bids'?'bids':'computers';
  tip.innerHTML=`<b>${cview==='day'?CD.ids[i]:CD.labels[i]}</b> &middot; ${t.toLocaleString()} ${unit}`
    + v.map((q,k)=>q?`<br><i style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${KCOL[k]};margin-right:5px"></i>${KLAB[k]}: ${q.toLocaleString()}`:'').join('');
  tip.style.display='block';
  const rc=box.getBoundingClientRect();
  let x=e.clientX-rc.left+12, yy=e.clientY-rc.top-10;
  if(x+tip.offsetWidth>rc.width) x=e.clientX-rc.left-tip.offsetWidth-12;
  tip.style.left=Math.max(0,x)+'px'; tip.style.top=Math.max(0,yy)+'px';
}
function openMonth(mo){
  const st=document.getElementById('status');
  if(st.value!=='all'){st.value='all';}
  openMonths=(openMonths||[]).filter(x=>x!==mo).concat([mo]);
  localStorage.setItem('gem_openmo',JSON.stringify(openMonths));
  render();
  const tr=document.querySelector(`.mrow[data-mo="${mo}"]`);
  if(tr) tr.scrollIntoView({behavior:'smooth',block:'start'});
}
document.querySelectorAll('#cview button').forEach(b=>b.onclick=()=>{cview=b.dataset.v;localStorage.setItem('gem_cview',cview);drawChart();});
document.querySelectorAll('#cmetric button').forEach(b=>b.onclick=()=>{cmetric=b.dataset.v;localStorage.setItem('gem_cmetric',cmetric);drawChart();});
let _rt=null;
window.addEventListener('resize',()=>{clearTimeout(_rt);_rt=setTimeout(drawChart,120);});
drawChart();
</script></body></html>"""

out = (TEMPLATE
       .replace("__ROWS__", json.dumps(ROWS, separators=(",",":")))
       .replace("__CHART__", json.dumps(CHART, separators=(",", ":"), sort_keys=True))
       .replace("__UPDATED__", DATA["updated"])
       .replace("__ALLN__", "{:,}".format(len(ALL_ROWS))))

path = os.path.join(HERE, "dashboard.html")
open(path, "w", encoding="utf8").write(out)
print("Wrote {} ({:,} of {:,} bids{}; {:,} KB)".format(
    path, len(ROWS), len(ALL_ROWS),
    "; {:,} closed >{}d ago omitted".format(DROPPED, CLOSED_GRACE_DAYS) if CLOSED_GRACE_DAYS else "",
    len(out.encode("utf8")) // 1024))
print("Bundled bids counted from PDF: {:,}; not read yet: {:,}".format(N_PDF, N_UNREAD))
print("Bids with delivery states from PDF: {:,} of {:,}".format(N_STATES, len(ROWS)))

#!/usr/bin/env python3
"""Reads bids.json and writes a self-contained dashboard.html with data embedded."""
import json
import os
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, "bids.json"), encoding="utf8"))
ALL_ROWS = DATA["rows"]

# The CSV keeps every bid ever seen; the page only needs what is still
# actionable, otherwise index.html grows without limit. Keep bids that are
# still open, plus a short tail of recently-closed ones for reference.
CLOSED_GRACE_DAYS = int(os.environ.get("GEM_CLOSED_GRACE_DAYS", "7"))
_today = datetime.now(timezone.utc).date()
_cutoff = (_today - timedelta(days=CLOSED_GRACE_DAYS)).isoformat()


def _still_relevant(r):
    end = (r.get("bid_end_date") or "")[:10]
    if not end:
        return True              # unknown close date: keep rather than hide
    return end >= _cutoff


ROWS = [r for r in ALL_ROWS if _still_relevant(r)]
DROPPED = len(ALL_ROWS) - len(ROWS)

# Trim the embedded payload. bid_url is a constant prefix + id, and the
# verbose "item" string is only needed as a tooltip on bundled rows.
URL_PREFIX = "https://bidplus.gem.gov.in/showbidDocument/"
_slim = []
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
    }
    if str(r.get("is_bundle")) == "1":
        o["n"] = r.get("n_items", "")
        full = r.get("item", "")
        if full != o["m"]:
            o["f"] = full
    _slim.append(o)
ROWS = _slim

# daily bid-start counts, last 21 days
counts = {}
for r in ROWS:
    d = (r.get("bid_start_date") or "")[:10]
    if d:
        counts[d] = counts.get(d, 0) + 1
today = datetime.now(timezone.utc).date()
days = [(today - timedelta(days=i)).isoformat() for i in range(20, -1, -1)]
series = [counts.get(d, 0) for d in days]

TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GeM IT Hardware Bids</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js" integrity="sha384-iU8HYtnGQ8Cy4zl7gbNMOhsDTTKX02BTXptVP/vqAWIaTfM7isw76iyZCsjL2eVi" crossorigin="anonymous"></script>
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
.chartbox{height:190px}
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
.t\\.All-in-One\\ PC,.t-AIO{background:#f0e6fb;color:#5b2a91}
.qty{font-variant-numeric:tabular-nums;font-weight:600}
.dept{font-size:12.5px}
.min{color:#6b7280;font-size:11.5px}
.matched{font-size:12.5px;color:#1a1d21;margin-top:2px}
.bundle{display:inline-block;margin-top:4px;background:#fff8e6;border:1px solid #f0dc9a;color:#7a5c00;font-size:11px;padding:2px 7px;border-radius:5px;cursor:help}
.approx{color:#b45309;font-weight:700;margin-left:2px;cursor:help}
.st{display:inline-block;background:#eef2f6;color:#334155;padding:2px 8px;border-radius:10px;font-size:11.5px;white-space:nowrap}
.central{color:#9aa3ad;font-size:11.5px;font-style:italic;cursor:help}
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
 <div class="card"><div class="n" id="kWeek">0</div><div class="l">Last 7 days</div></div>
 <div class="card"><div class="n" id="kQty">0</div><div class="l">Total quantity</div></div>
 <div class="card"><div class="n" id="kAdded">0</div><div class="l">Added today</div></div>
 <div class="card"><div class="n" id="kState">0</div><div class="l">States</div></div>
</div>

<div class="panel"><div class="chartbox"><canvas id="chart"></canvas></div></div>

<div class="panel">
 <div class="controls">
  <input type="search" id="q" placeholder="Search bid number, department or item…">
  <span class="chip on" data-cat="all">All</span>
  <span class="chip" data-cat="Desktop">Desktop</span>
  <span class="chip" data-cat="Laptop">Laptop</span>
  <span class="chip" data-cat="All-in-One PC">All-in-One</span>
  <span class="chip" data-cat="Server">Server</span>
  <select id="range">
   <option value="0">Any date</option>
   <option value="added">Added today</option>
   <option value="1">Starting today</option>
   <option value="7">Started last 7 days</option>
   <option value="30">Started last 30 days</option>
  </select>
  <select id="state"><option value="all">All states</option></select>
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
  <th data-k="q">Qty</th>
  <th data-k="t">Bid Start Date</th>
  <th data-k="e">Closes</th>
  <th data-k="a">Added</th>
 </tr></thead><tbody id="tb"></tbody></table>
 <div class="empty" id="empty" style="display:none">No bids match these filters.</div>
 <p class="note"><b>Reading this table.</b> The line under each bid number shows only the
 items that matched your categories &mdash; not the full bid contents. A <b>bundled bid</b> badge
 means GeM packaged several products into one tender; hover it to see everything included. In that
 case the quantity carries an asterisk<span class="approx">*</span> because GeM publishes only a
 bid-wide total covering every line item, not just the computers. Per-product quantities exist
 only inside the bid PDF. &ldquo;Bid Start Date&rdquo; is when bidding opens, not the document
 publication date. Reverse auctions are excluded &mdash; only open tenders are listed. Bids that closed more than __GRACE__ days ago are not shown here &mdash; the full
 history (__ALLN__ bids) is in <a href="bids.csv">bids.csv</a>.
 <b>State</b> is read from the buyer&rsquo;s department name; bids marked <i>central</i> are national bodies such as Military Affairs or Indian Railways that are not tied to one state.</p>
</div>
</div>
<script>
const ROWS = __ROWS__;
const URLP='https://bidplus.gem.gov.in/showbidDocument/';
const DAYS = __DAYS__, SERIES = __SERIES__;
const TODAY = new Date().toISOString().slice(0,10);
let cat = localStorage.getItem('gem_cat') || 'all';
let sortK = 't', sortDir = -1;

document.querySelectorAll('.chip').forEach(c=>{
  c.classList.toggle('on', c.dataset.cat===cat);
  c.onclick=()=>{cat=c.dataset.cat;localStorage.setItem('gem_cat',cat);
    document.querySelectorAll('.chip').forEach(x=>x.classList.toggle('on',x.dataset.cat===cat));render();};
});
document.getElementById('q').oninput=render;
document.getElementById('range').onchange=render;
document.getElementById('bundle').onchange=render;
const stSel=document.getElementById('state');
[...new Set(ROWS.map(r=>r.s).filter(Boolean))].sort().forEach(st=>{
  const o=document.createElement('option');o.value=st;o.textContent=st;stSel.appendChild(o);});
{const o=document.createElement('option');o.value='__central';o.textContent='Central bodies';stSel.appendChild(o);}
stSel.onchange=render;
document.querySelectorAll('th').forEach(th=>th.onclick=()=>{
  const k=th.dataset.k; sortDir = (k===sortK)? -sortDir : -1; sortK=k; render();});

function filtered(){
  const q=document.getElementById('q').value.toLowerCase().trim();
  const rangeVal=document.getElementById('range').value;
  const addedOnly = rangeVal==='added';
  const bundleVal=document.getElementById('bundle').value;
  const stVal=document.getElementById('state').value;
  const days = addedOnly ? 0 : +rangeVal;
  let cut=null;
  if(days){const d=new Date();d.setDate(d.getDate()-(days-1));cut=d.toISOString().slice(0,10);}
  return ROWS.filter(r=>{
    if(cat!=='all' && r.c!==cat) return false;
    if(stVal==='__central' && r.s) return false;
    if(stVal!=='all' && stVal!=='__central' && r.s!==stVal) return false;
    if(bundleVal==='single' && r.n) return false;
    if(bundleVal==='bundle' && !r.n) return false;
    if(addedOnly && (r.a||'')!==TODAY) return false;
    if(cut && (r.t||'') < cut) return false;
    if(q && !((r.b+' '+r.d+' '+r.y+' '+r.m+' '+(r.s||'')).toLowerCase().includes(q))) return false;
    return true;
  }).sort((a,b)=>{
    let x=a[sortK]??'', y=b[sortK]??'';
    if(sortK==='q'){x=+x||0;y=+y||0;return (x-y)*sortDir;}
    return String(x).localeCompare(String(y))*sortDir;
  });
}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function render(){
  const rows=filtered();
  document.getElementById('tb').innerHTML = rows.map(r=>{
    const isNew=(r.t||'')===TODAY;
    const isNewToday=(r.a||'')===TODAY;
    const cls='t-'+(r.c==='All-in-One PC'?'AIO':r.c);
    return `<tr>
      <td><a href="${URLP}${esc(r.i)}" target="_blank" rel="noopener">${esc(r.b)}</a>${isNew?'<span class="new">new</span>':''}
<div class="matched">${esc(r.m)}</div>
          ${r.n?`<div class="bundle" title="Full bid contents: ${esc(r.f||r.m)}">bundled bid &middot; ${esc(r.n)} line items</div>`:''}</td>
      <td><span class="tag ${cls}">${esc(r.c)}</span></td>
      <td><div class="dept">${esc(r.d)}</div><div class="min">${esc(r.y)}</div></td>
      <td>${r.s?`<span class="st">${esc(r.s)}</span>`:'<span class="central" title="Central / national body &mdash; no single state">central</span>'}</td>
      <td class="qty">${esc(r.q)}${r.n?'<span class="approx" title="Bid total across all line items, not just this category">*</span>':''}</td>
      <td>${esc(r.t)}</td>
      <td>${esc(r.e)}</td>
      <td>${esc(r.a)}${isNewToday?'<span class="new">new</span>':''}</td></tr>`;
  }).join('');
  document.getElementById('empty').style.display = rows.length?'none':'block';
  const wk=new Date();wk.setDate(wk.getDate()-6);const wkS=wk.toISOString().slice(0,10);
  document.getElementById('kTotal').textContent=rows.length;
  document.getElementById('kToday').textContent=rows.filter(r=>(r.t||'')===TODAY).length;
  document.getElementById('kWeek').textContent=rows.filter(r=>(r.t||'')>=wkS).length;
  document.getElementById('kQty').textContent=rows.reduce((s,r)=>s+(+r.q||0),0).toLocaleString();
  document.getElementById('kAdded').textContent=rows.filter(r=>(r.a||'')===TODAY).length;
  document.getElementById('kState').textContent=new Set(rows.map(r=>r.s).filter(Boolean)).size;
}
render();
new Chart(document.getElementById('chart'),{type:'bar',
 data:{labels:DAYS.map(d=>d.slice(5)),datasets:[{label:'Bids',data:SERIES,
   backgroundColor:'#2563eb',borderRadius:4}]},
 options:{responsive:true,maintainAspectRatio:false,
  plugins:{legend:{display:false},title:{display:true,text:'Bids by start date per day (last 21 days)',
    align:'start',color:'#525a63',font:{size:12,weight:'500'}}},
  scales:{y:{beginAtZero:true,ticks:{precision:0},grid:{color:'#eef0f2'}},
          x:{grid:{display:false},ticks:{font:{size:10}}}}}});
</script></body></html>"""

out = (TEMPLATE
       .replace("__ROWS__", json.dumps(ROWS, separators=(",",":")))
       .replace("__DAYS__", json.dumps(days))
       .replace("__SERIES__", json.dumps(series))
       .replace("__UPDATED__", DATA["updated"])
       .replace("__GRACE__", str(CLOSED_GRACE_DAYS))
       .replace("__ALLN__", "{:,}".format(len(ALL_ROWS))))

path = os.path.join(HERE, "dashboard.html")
open(path, "w", encoding="utf8").write(out)
print("Wrote {} ({:,} of {:,} bids; {:,} closed >{}d ago omitted)".format(
    path, len(ROWS), len(ALL_ROWS), DROPPED, CLOSED_GRACE_DAYS))

#!/usr/bin/env python3
"""Club Med price watcher.

Usage:
  python3 watch.py check                 fetch current prices, record, alert on drops
  python3 watch.py scan KIPC_WINTER 2027-01-01 2027-04-30 [nights] [step]
                                         price every start date in a range.
                                         nights may be a list: 5,6,7
                                         step skips days: 7 = same weekday only
  python3 watch.py history [label]       print recorded price history
  python3 watch.py resolve <clubmed-url> turn a resort URL into a watches.json entry
  python3 watch.py dashboard             regenerate dashboard.html
  python3 watch.py install [hours]       install a launchd timer (default every 6h)
  python3 watch.py uninstall             remove the launchd timer
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from clubmed import PriceError, booking_url, fetch_price, nights_between, parse_date

DB = os.path.join(HERE, "prices.db")
CONFIG = os.path.join(HERE, "watches.json")
LABEL_ID = "com.suenli.clubmed-price-watch"


# ---------------------------------------------------------------- storage

def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        label TEXT NOT NULL,
        product_id TEXT,
        start_date TEXT,
        nights INTEGER,
        adults INTEGER,
        children INTEGER,
        currency TEXT,
        best_price REAL,
        initial_price REAL,
        discount_pct REAL,
        error TEXT
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_label_ts ON observations(label, ts)")
    con.commit()
    return con


def last_good(con, label):
    row = con.execute(
        "SELECT best_price, ts FROM observations "
        "WHERE label=? AND error IS NULL ORDER BY id DESC LIMIT 1", (label,)).fetchone()
    return row if row else (None, None)


def record(con, label, w, res=None, err=None):
    con.execute(
        "INSERT INTO observations (ts,label,product_id,start_date,nights,adults,children,"
        "currency,best_price,initial_price,discount_pct,error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), label, w["product_id"],
         w["start_date"], w["_nights"], w.get("adults", 2), w.get("children", 0),
         res["currency"] if res else None,
         res["best_price"] if res else None,
         res["initial_price"] if res else None,
         res["discount_pct"] if res else None,
         err))
    con.commit()


# ---------------------------------------------------------------- alerting

def notify_macos(title, message, url=None):
    body = message.replace('"', "'")
    script = 'display notification "%s" with title "%s" sound name "Glass"' % (
        body[:230], title.replace('"', "'")[:60])
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=10)
    except Exception:
        pass


def notify_webhook(url, title, message, link):
    if not url:
        return
    payload = json.dumps({"title": title, "message": message, "url": link}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print("  webhook failed: %s" % e)


def alert(cfg, title, message, link):
    print("\n  *** %s\n      %s\n      %s" % (title, message, link))
    n = cfg.get("notify", {})
    if n.get("macos", True):
        notify_macos(title, message, link)
    notify_webhook(n.get("webhook_url"), title, message, link)


# ---------------------------------------------------------------- config

def load_config():
    with open(CONFIG) as f:
        cfg = json.load(f)
    for w in cfg["watches"]:
        if "nights" in w and w["nights"]:
            w["_nights"] = int(w["nights"])
        else:
            w["_nights"] = nights_between(w["start_date"], w["end_date"])
    return cfg


def extras_for(cfg, w=None):
    """Out-of-pocket costs Club Med doesn't charge (gear hire, transfers...).

    Set globally under "extras" in watches.json; a watch may override it.
    """
    e = dict(cfg.get("extras") or {})
    if w:
        e.update(w.get("extras") or {})
    return float(e.get("amount") or 0), e.get("note") or ""


def money(cur, v):
    return "%s%s" % ("S$" if cur == "SGD" else cur + " ", format(int(round(v)), ","))


# ---------------------------------------------------------------- commands

def cmd_check(cfg):
    con = db()
    print("Club Med price check  --  %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    for i, w in enumerate(cfg["watches"]):
        label = w["label"]
        prev, prev_ts = last_good(con, label)
        link = booking_url(w["product_id"], w.get("slug", ""), w["start_date"],
                           w["_nights"], w.get("adults", 2), w.get("children", 0),
                           cfg.get("site", "https://www.clubmed.com.sg"),
                           w.get("season", "w"))
        try:
            res = fetch_price(w["product_id"], w["start_date"], w["_nights"],
                              w.get("adults", 2), w.get("children", 0),
                              w.get("departure_option_id"),
                              cfg.get("locale", "en-SG"))
        except PriceError as e:
            record(con, label, w, err=str(e))
            print("\n%-45s  UNAVAILABLE (%s)" % (label, e))
            continue

        record(con, label, w, res=res)
        cur, best = res["currency"], res["best_price"]
        delta = "" if prev is None else " (was %s)" % money(cur, prev)
        print("\n%s\n  %s -> %s, %d nights, %d adult(s)" % (
            label, w["start_date"],
            (parse_date(w["start_date"]) + timedelta(days=w["_nights"])).isoformat(),
            w["_nights"], w.get("adults", 2)))
        print("  now %s%s   was-listed %s  (-%.0f%%)   target %s" % (
            money(cur, best), delta, money(cur, res["initial_price"]),
            res["discount_pct"],
            money(cur, w["target_price"]) if w.get("target_price") else "none"))
        ex_amt, ex_note = extras_for(cfg, w)
        if ex_amt:
            print("  budget %s all-in  (+%s you pay separately: %s)" % (
                money(cur, best + ex_amt), money(cur, ex_amt), ex_note))

        target = w.get("target_price")
        allin = (" | ~%s all-in" % money(cur, best + ex_amt)) if ex_amt else ""
        if target and best <= target:
            alert(cfg, "Club Med target hit!",
                  "%s is %s (target %s)%s" % (
                      label, money(cur, best), money(cur, target), allin),
                  link)
        elif prev is not None and best < prev:
            alert(cfg, "Club Med price drop",
                  "%s fell %s to %s%s" % (
                      label, money(cur, prev - best), money(cur, best), allin),
                  link)
        elif prev is not None and best > prev:
            print("  (price rose %s)" % money(cur, best - prev))

        if i < len(cfg["watches"]) - 1:
            time.sleep(1.5)

    write_dashboard(cfg, con)
    con.close()


def cmd_scan(cfg, product_id, start, end, nights_arg="7", step=1):
    """Price every start date in a range, across one or more stay lengths."""
    nights_list = sorted({int(n) for n in str(nights_arg).split(",") if n.strip()})
    d, last = parse_date(start), parse_date(end)
    ex_amt, ex_note = extras_for(cfg)
    target = cfg.get("scan_target") or None
    for w in cfg.get("watches", []):
        if w.get("product_id") == product_id and w.get("target_price") and not target:
            target = w["target_price"]

    print("Scanning %s | %s stays | %s .. %s | every %d day(s)" % (
        product_id, "/".join("%dn" % n for n in nights_list), start, end, step))
    if target:
        print("Flagging anything at or under %s  (*)" % money("SGD", target))
    if ex_amt:
        print("All-in adds %s: %s" % (money("SGD", ex_amt), ex_note))
    print()

    rows = []
    while d <= last:
        ds = d.isoformat()
        cells = []
        for n in nights_list:
            try:
                r = fetch_price(product_id, ds, n, locale=cfg.get("locale", "en-SG"))
                rows.append((r["best_price"], ds, n, r))
                mark = "*" if target and r["best_price"] <= target else " "
                cells.append("%2dn %8s%s" % (n, money(r["currency"], r["best_price"]), mark))
            except PriceError:
                cells.append("%2dn %8s " % (n, "-"))
            time.sleep(1.0)
        print("  %s  %s  %s" % (ds, d.strftime("%a"), "   ".join(cells)))
        d += timedelta(days=step)

    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "product_id": product_id, "range": [start, end],
        "nights": nights_list, "step": step,
        "extras": ex_amt, "extras_note": ex_note, "target": target,
        "results": [{"start_date": ds, "nights": n, "best_price": r["best_price"],
                     "initial_price": r["initial_price"], "currency": r["currency"],
                     "discount_pct": r["discount_pct"],
                     "weekday": parse_date(ds).strftime("%a")}
                    for best, ds, n, r in rows],
    }
    out = os.path.join(HERE, "scan_%s.json" % product_id)
    with open(out, "w") as f:
        json.dump(payload, f, indent=2)
    print("\nSaved %d result(s) -> %s" % (len(rows), out))

    if not rows:
        print("\nNothing available in that range.")
        return

    rows.sort(key=lambda x: x[0])
    print("\nCheapest stays found:")
    print("  %-12s %-4s %10s %10s   %s" % ("start", "len", "clubmed", "all-in", "list"))
    for best, ds, n, r in rows[:15]:
        cur = r["currency"]
        print("  %-12s %-4s %10s %10s   %s (-%.0f%%)%s" % (
            ds, "%dn" % n, money(cur, best),
            money(cur, best + ex_amt) if ex_amt else "-",
            money(cur, r["initial_price"]), r["discount_pct"],
            "  <- under target" if target and best <= target else ""))

    if target:
        hits = [r for r in rows if r[0] <= target]
        print("\n%d of %d priced stays are at or under %s." % (
            len(hits), len(rows), money("SGD", target)))


def cmd_history(cfg, label=None):
    con = db()
    q = ("SELECT ts,label,best_price,initial_price,currency,error FROM observations "
         "%s ORDER BY id" % ("WHERE label LIKE ?" if label else ""))
    rows = con.execute(q, ("%" + label + "%",) if label else ()).fetchall()
    for ts, lab, best, init, cur, err in rows:
        print("%s  %-40s  %s" % (ts, lab[:40],
                                 err if err else "%s (list %s)" % (money(cur, best), money(cur, init))))
    print("\n%d observation(s)" % len(rows))
    con.close()



def cmd_resolve(cfg, url):
    """Turn a clubmed.com URL into a ready-to-paste watches.json entry."""
    import urllib.parse as up
    req = urllib.request.Request(url, headers={"User-Agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Accept-Language": cfg.get("locale", "en-SG")})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    m = re.search(r'productId\\?"?\s*:\s*\\?"([A-Z0-9_]+)', html)
    if not m:
        print("Could not find a productId on that page."); return
    pid = m.group(1)
    u = up.urlparse(url)
    q = up.parse_qs(u.query)
    parts = [x for x in u.path.split("/") if x]
    slug = parts[parts.index("r") + 1] if "r" in parts else ""
    season = parts[parts.index("r") + 2] if "r" in parts and len(parts) > parts.index("r") + 2 else "w"
    sd = (q.get("start_date") or [""])[0]
    ed = (q.get("end_date") or [""])[0]
    entry = {
        "label": "%s %s" % (slug.replace("-", " ").title(), sd),
        "product_id": pid, "slug": slug, "season": season,
        "start_date": sd, "end_date": ed,
        "adults": int((q.get("adults") or ["2"])[0]),
        "children": int((q.get("children") or ["0"])[0]),
        "departure_option_id": None,
        "target_price": None,
    }
    if sd and ed:
        try:
            r = fetch_price(pid, sd, nights_between(sd, ed), entry["adults"],
                            entry["children"], None, cfg.get("locale", "en-SG"))
            print("Current price: %s (list %s)\n" % (
                money(r["currency"], r["best_price"]), money(r["currency"], r["initial_price"])))
        except PriceError as e:
            print("Price lookup failed: %s\n" % e)
    print("Add this to the \"watches\" list in watches.json:\n")
    print(json.dumps(entry, indent=6))


# ---------------------------------------------------------------- dashboard

def write_dashboard(cfg, con=None):
    close = con is None
    con = con or db()
    series = {}
    ex_amt, ex_note = extras_for(cfg)
    for w in cfg["watches"]:
        w_amt, w_note = extras_for(cfg, w)
        rows = con.execute(
            "SELECT ts,best_price,initial_price,currency FROM observations "
            "WHERE label=? AND error IS NULL ORDER BY id", (w["label"],)).fetchall()
        series[w["label"]] = {
            "points": [{"ts": r[0], "best": r[1], "list": r[2]} for r in rows],
            "currency": rows[-1][3] if rows else "SGD",
            "target": w.get("target_price"),
            "extras": w_amt,
            "extras_note": w_note,
            "start_date": w["start_date"],
            "nights": w["_nights"],
            "adults": w.get("adults", 2),
            "url": booking_url(w["product_id"], w.get("slug", ""), w["start_date"],
                               w["_nights"], w.get("adults", 2), w.get("children", 0),
                               cfg.get("site", "https://www.clubmed.com.sg"),
                               w.get("season", "w")),
        }
    html = DASHBOARD.replace("__DATA__", json.dumps(series)).replace(
        "__UPDATED__", datetime.now().strftime("%d %b %Y, %H:%M"))
    path = os.path.join(HERE, "dashboard.html")
    with open(path, "w") as f:
        f.write(html)
    print("\nDashboard: %s" % path)
    if close:
        con.close()
    return path


# ---------------------------------------------------------------- launchd

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>{script}</string><string>check</string></array>
  <key>StartInterval</key><integer>{interval}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{here}/watch.log</string>
  <key>StandardErrorPath</key><string>{here}/watch.log</string>
</dict></plist>
"""


def plist_path():
    return os.path.expanduser("~/Library/LaunchAgents/%s.plist" % LABEL_ID)


def cmd_install(hours):
    p = plist_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(PLIST.format(label=LABEL_ID, script=os.path.join(HERE, "watch.py"),
                             interval=int(hours * 3600), here=HERE))
    subprocess.run(["launchctl", "unload", p], capture_output=True)
    r = subprocess.run(["launchctl", "load", p], capture_output=True, text=True)
    if r.returncode:
        print("launchctl load failed: %s" % r.stderr.strip())
    else:
        print("Installed. Checking every %g hour(s) while this Mac is awake." % hours)
        print("Log: %s/watch.log" % HERE)


def cmd_uninstall():
    p = plist_path()
    subprocess.run(["launchctl", "unload", p], capture_output=True)
    if os.path.exists(p):
        os.remove(p)
    print("Removed.")


DASHBOARD = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Club Med price watch</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#f6f6f4;--card:#fff;--ink:#1c1c1a;--mut:#6b6b66;--line:#e3e3df;--good:#0f7b4f;--bad:#a8321f;--acc:#1a5fb4;--note:#fdf4e3;--noteline:#eadcbe}
@media(prefers-color-scheme:dark){:root{--bg:#131316;--card:#1c1c20;--ink:#eceae5;--mut:#9d9d97;--line:#31313a;--good:#54c996;--bad:#f08a72;--acc:#79b0f5;--note:#2b2618;--noteline:#4a4028}}
*{box-sizing:border-box}
body{margin:0;padding:32px 20px;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.wrap{max-width:880px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:28px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:18px}
.card h2{font-size:16px;margin:0 0 2px}
.meta{color:var(--mut);font-size:13px;margin-bottom:16px}
.row{display:flex;flex-wrap:wrap;gap:28px;align-items:baseline;margin-bottom:16px}
.big{font-size:30px;font-weight:600;letter-spacing:-.5px}
.lab{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.strike{text-decoration:line-through;color:var(--mut)}
.big2{font-size:22px;font-weight:600;letter-spacing:-.3px;color:var(--mut)}
.foot{background:var(--note);border:1px solid var(--noteline);border-radius:8px;
padding:10px 12px;font-size:13px;margin-bottom:16px;color:var(--ink)}
.foot strong{color:var(--bad)}
.chg{font-size:14px;font-weight:600}
.dn{color:var(--good)}.up{color:var(--bad)}
svg{width:100%;height:120px;display:block;overflow:visible}
a{color:var(--acc)}
.empty{color:var(--mut);font-style:italic}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:14px}
td,th{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:500}
.scroll{overflow-x:auto}
</style></head><body><div class="wrap">
<h1>Club Med price watch</h1>
<div class="sub">Last checked __UPDATED__</div>
<div id="out"></div>
</div>
<script>
const DATA = __DATA__;
const fmt = (c,v) => (c==='SGD'?'S$':c+' ')+Math.round(v).toLocaleString();
const out = document.getElementById('out');

function spark(pts, target){
  if(pts.length<2) return '';
  const w=800,h=120,pad=8;
  const vals=pts.map(p=>p.best).concat(target?[target]:[]);
  let lo=Math.min(...vals), hi=Math.max(...vals);
  if(hi===lo){hi=lo+1;}
  const x=i=>pad+i*(w-2*pad)/(pts.length-1);
  const y=v=>pad+(h-2*pad)*(1-(v-lo)/(hi-lo));
  const line=pts.map((p,i)=>(i?'L':'M')+x(i).toFixed(1)+' '+y(p.best).toFixed(1)).join(' ');
  const area=line+` L${x(pts.length-1).toFixed(1)} ${h-pad} L${pad} ${h-pad} Z`;
  const tl = target? `<line x1="${pad}" x2="${w-pad}" y1="${y(target).toFixed(1)}" y2="${y(target).toFixed(1)}"
      stroke="var(--good)" stroke-dasharray="4 4" stroke-width="1.5"/>`:'';
  const dots = pts.map((p,i)=>`<circle cx="${x(i).toFixed(1)}" cy="${y(p.best).toFixed(1)}" r="2.5" fill="var(--acc)"/>`).join('');
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="price history">
    <path d="${area}" fill="var(--acc)" opacity=".10"/>
    ${tl}<path d="${line}" fill="none" stroke="var(--acc)" stroke-width="2"
      stroke-linejoin="round" stroke-linecap="round"/>${dots}</svg>`;
}

const keys = Object.keys(DATA);
if(!keys.length){ out.innerHTML='<div class="card empty">No watches configured.</div>'; }
keys.forEach(label=>{
  const d=DATA[label], p=d.points, c=d.currency;
  if(!p.length){
    out.insertAdjacentHTML('beforeend',
      `<div class="card"><h2>${label}</h2><div class="empty">No successful reading yet.</div></div>`);
    return;
  }
  const cur=p[p.length-1], first=p[0];
  const diff=cur.best-first.best;
  const chg = p.length>1 ? `<div><div class="lab">Since ${first.ts.slice(0,10)}</div>
      <div class="chg ${diff<0?'dn':diff>0?'up':''}">${diff===0?'no change':(diff<0?'▼ ':'▲ ')+fmt(c,Math.abs(diff))}</div></div>`:'';
  const tgt = d.target ? `<div><div class="lab">Target</div><div class="chg ${cur.best<=d.target?'dn':''}">${fmt(c,d.target)}${cur.best<=d.target?' — hit':''}</div></div>`:'';
  const allin = d.extras ? `<div><div class="lab">Budget all-in</div><div class="big2">${fmt(c,cur.best+d.extras)}</div></div>`:'';
  const foot = d.extras ? `<div class="foot"><strong>+ ${fmt(c,d.extras)} you pay separately.</strong>
      ${d.extras_note}. The prices above are the Club Med booking cost only.</div>`:'';
  const rows = p.slice().reverse().slice(0,12).map(r=>
     `<tr><td>${r.ts.replace('T',' ').slice(0,16)}</td><td>${fmt(c,r.best)}</td><td class="strike">${fmt(c,r.list)}</td></tr>`).join('');
  out.insertAdjacentHTML('beforeend', `<div class="card">
    <h2>${label}</h2>
    <div class="meta">${d.start_date} · ${d.nights} nights · ${d.adults} adults ·
      <a href="${d.url}" target="_blank" rel="noopener">open on clubmed.com.sg</a></div>
    <div class="row">
      <div><div class="lab">Current</div><div class="big">${fmt(c,cur.best)}</div></div>
      ${allin}
      <div><div class="lab">List price</div><div class="chg strike">${fmt(c,cur.list)}</div></div>
      ${chg}${tgt}
    </div>
    ${foot}
    ${spark(p, d.target)}
    <div class="scroll"><table><tr><th>Checked</th><th>Best</th><th>List</th></tr>${rows}</table></div>
  </div>`);
});
</script></body></html>
"""


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "check"
    cfg = load_config()
    if cmd == "check":
        cmd_check(cfg)
    elif cmd == "scan":
        nights = args[4] if len(args) > 4 else "7"
        step = int(args[5]) if len(args) > 5 else 1
        cmd_scan(cfg, args[1], args[2], args[3], nights, step)
    elif cmd == "history":
        cmd_history(cfg, args[1] if len(args) > 1 else None)
    elif cmd == "resolve":
        cmd_resolve(cfg, args[1])
    elif cmd == "dashboard":
        write_dashboard(cfg)
    elif cmd == "install":
        cmd_install(float(args[1]) if len(args) > 1 else 6)
    elif cmd == "uninstall":
        cmd_uninstall()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

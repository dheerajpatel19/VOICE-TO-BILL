"""VOICE TO BILL - Python backend (no extra install needed)
Run:  python app.py      -> opens http://localhost:8000 in the browser
Frontend (index.html) records the voice; this server understands the order
(names / aliases / spelling variations), keeps stock, saves bills, prints invoices."""
import difflib, html, json, os, re, sys, threading, webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DB, BILLS, LOCK = os.path.join(HERE, "data.json"), os.path.join(HERE, "bills"), threading.Lock()
DEFAULT = {"meta": {"shop": "My Grocery Store", "no": 1}, "items": {
 "sugar": {"unit": "kg", "rate": 45, "gst": 0, "stock": 50, "aliases": ["chini", "cheeni", "shakkar", "चीनी", "சர்க்கரை", "சீனி", "చక్కెర", "పంచదార"]},
 "rice": {"unit": "kg", "rate": 60, "gst": 0, "stock": 100, "aliases": ["chawal", "chaawal", "चावल", "அரிசி", "బియ్యం"]},
 "oil": {"unit": "l", "rate": 150, "gst": 5, "stock": 30, "aliases": ["tel", "तेल", "எண்ணெய்", "నూనె"]},
 "milk": {"unit": "l", "rate": 56, "gst": 0, "stock": 20, "aliases": ["doodh", "dudh", "दूध", "பால்", "పాలు"]},
 "tea": {"unit": "kg", "rate": 400, "gst": 5, "stock": 10, "aliases": ["chai", "chaay", "चाय", "தேநீர்", "టీ"]},
 "potato": {"unit": "kg", "rate": 30, "gst": 0, "stock": 40, "aliases": ["aloo", "alu", "आलू", "உருளைக்கிழங்கு", "బంగాళదుంప"]},
 "maggi": {"unit": "pc", "rate": 14, "gst": 12, "stock": 60, "aliases": ["noodles", "maggie", "मैगी"]}}}

def load():
    if os.path.exists(DB):
        return json.load(open(DB, encoding="utf-8"))
    return json.loads(json.dumps(DEFAULT))
def save(d): json.dump(d, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---------- understanding names: any spelling (chini / cheeni / cheni / chinee) ----------
def skel(w):
    """Sound-alike key: ee->i, aa->a, oo->u, ph->f, w->v, h dropped, e->i, o->u, double letters merged."""
    w = w.lower()
    for a, b in (("ee", "i"), ("ii", "i"), ("aa", "a"), ("oo", "u"), ("uu", "u"), ("ph", "f"), ("sh", "s"),
                 ("kh", "k"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("gh", "g"), ("ch", "c"), ("w", "v"), ("z", "j"), ("h", "")):
        w = w.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", w.translate(str.maketrans("eoy", "iui")))

def find_item(items, text):
    text = text.strip().lower()
    if not text: return None
    names = [(n.lower(), k) for k, v in items.items() for n in [k] + v.get("aliases", [])]
    for n, k in sorted(names, key=lambda x: -len(x[0])):      # 1) exact name inside the phrase
        if n in text: return k
    best, score = None, 0
    for w in text.split():                                      # 2) sound-alike / fuzzy match
        for n, k in names:
            a, b = skel(w), skel(n)
            r = 1 if a == b else difflib.SequenceMatcher(None, a, b).ratio()
            if len(a) >= 3 and r >= 0.8 and r > score: best, score = k, r
    return best

UNITS = {}
for base, f, ws in (("kg", 1, "kg kgs kilo kilos kilogram kilograms किलो கிலோ కిలో"), ("kg", .001, "g gm gms gram grams ग्राम கிராம் గ్రాము గ్రాములు"),
                    ("l", 1, "l lt ltr litre litres liter liters लीटर லிட்டர் లీటరు లీటర్"), ("l", .001, "ml millilitre"),
                    ("pc", 1, "pc pcs piece pieces packet packets pkt पैकेट"), ("pc", 12, "dozen दर्जन")):
    for w in ws.split(): UNITS[w] = (base, f)
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "ek": 1, "एक": 1, "do": 2, "दो": 2,
       "teen": 3, "तीन": 3, "char": 4, "चार": 4, "paanch": 5, "panch": 5, "पाँच": 5, "पांच": 5, "das": 10, "दस": 10}

def unit_of(w):
    if not w: return None
    if w in UNITS: return UNITS[w]
    m = difflib.get_close_matches(w, [u for u in UNITS if u.isascii() and len(u) > 2], 1, 0.8)
    return UNITS[m[0]] if m else None

def normalise(t):
    t = " ".join(str(NUM.get(w, w)) for w in t.lower().replace(",", " , ").replace("।", " , ").split())
    t = re.sub(r"\b(half|aadha|adha)\b|आधा", "0.5", t)
    t = re.sub(r"\b(dedh|derh)\b|डेढ़", "1.5", t)
    return re.sub(r"\b(quarter|paav|pav)\b|पाव", "0.25", t)

def parse(items, text):
    out = []
    for ph in [p.strip() for p in re.split(r",|\band\b|\baur\b|और|\bthen\b|\bplus\b", normalise(text)) if p.strip()]:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(\S+)?", ph)
        if not m: out.append({"error": "nq", "ph": ph}); continue
        qty, u = float(m.group(1)), unit_of(m.group(2))
        item = find_item(items, (ph.replace(m.group(0), " ") if u else ph.replace(m.group(1), " ")))
        if not item: out.append({"error": "ni", "ph": ph}); continue
        base = items[item]["unit"]
        if u and u[0] != base: out.append({"error": "sold", "item": item, "unit": base}); continue
        out.append({"item": item, "qty": round(qty * (u[1] if u else 1), 3)})
    return out

def aliases(s):
    return [a.strip().lower() for a in re.split(r"[,،，;]", s) if a.strip()] if isinstance(s, str) else s

# ---------- invoice page (print) ----------
def invoice_html(b, auto):
    e = html.escape
    rows = "".join(f"<tr><td>{n}</td><td><b>{e(l['item'])}</b></td><td class=r>{l['qty']:g} {l['unit']}</td><td class=r>₹{l['rate']}</td><td class=r>{l['gst']}%</td><td class=r>{l['amount']:.2f}</td></tr>"
                   for n, l in enumerate(b["lines"], 1))
    return f"""<!DOCTYPE html><meta charset=utf-8><title>Invoice {b['no']:04d}</title><style>
body{{font:15px Segoe UI,Nirmala UI,Arial;max-width:680px;margin:20px auto;color:#1e293b}}.h{{background:linear-gradient(90deg,#4f46e5,#db2777);color:#fff;padding:14px;border-radius:8px 8px 0 0;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.h b{{font-size:24px}}.h div{{display:flex;justify-content:space-between}}table{{width:100%;border-collapse:collapse}}th{{background:#e0e7ff;padding:7px;text-align:left}}td{{padding:7px;border-bottom:1px solid #eef2ff}}.r{{text-align:right}}
.g td{{background:#dcfce7;color:#166534;font-size:20px;font-weight:800}}*{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}</style>
<div class=h><b>{e(b['shop'])}</b><div><span>Invoice / बिल #{b['no']:04d}</span><span>{b['date']}</span></div></div>
<table><tr><th>#</th><th>Item</th><th class=r>Qty</th><th class=r>Rate</th><th class=r>GST</th><th class=r>Amount</th></tr>{rows}
<tr><td colspan=5 class=r>Sub Total</td><td class=r>{b['sub']:.2f}</td></tr><tr><td colspan=5 class=r>GST</td><td class=r>{b['gst']:.2f}</td></tr>
<tr class=g><td colspan=4>Amount Payable / देय राशि</td><td colspan=2 class=r>₹ {b['total']:.2f}</td></tr></table>
<p style=text-align:center;color:#64748b>Thank you! Visit again 🙏</p>{"<script>print()</script>" if auto else ""}"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)).encode("utf-8")
        self.send_response(200); self.send_header("Content-Type", ctype + "; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p, d = self.path.split("?")[0], load()
        if p in ("/", "/index.html"): return self.send(open(os.path.join(HERE, "index.html"), "rb").read(), "text/html")
        if p == "/api/items": return self.send(d["items"])
        if p == "/api/meta": return self.send(d["meta"])
        if p == "/api/bills":
            out = []
            for f in sorted(os.listdir(BILLS) if os.path.isdir(BILLS) else [], reverse=True):
                b = json.load(open(os.path.join(BILLS, f), encoding="utf-8")); out.append({k: b[k] for k in ("no", "date", "shop", "total")})
            return self.send(out)
        m = re.match(r"/bill/(\d+)", p)
        if m:
            f = os.path.join(BILLS, f"bill_{int(m.group(1)):04d}.json")
            if os.path.exists(f): return self.send(invoice_html(json.load(open(f, encoding="utf-8")), "print=1" in self.path), "text/html")
        self.send("not found", "text/plain")
    def do_POST(self):
        r = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 2) or b"{}")
        with LOCK:
            d, I, p = load(), None, self.path
            I = d["items"]
            if p == "/api/parse": return self.send(parse(I, r.get("text", "")))
            if p == "/api/item":                                   # add new item OR add stock to existing
                n = r["name"].strip().lower(); o = I.get(n, {})
                I[n] = {"unit": r.get("unit", o.get("unit", "kg")), "rate": float(r["rate"]), "gst": float(r.get("gst", 0)),
                        "stock": round(o.get("stock", 0) + float(r.get("stock", 0)), 3),
                        "aliases": sorted(set(o.get("aliases", []) + aliases(r.get("aliases", ""))))}
            elif p == "/api/restock": I[r["name"]]["stock"] = round(I[r["name"]]["stock"] + float(r["qty"]), 3)
            elif p == "/api/rate": I[r["name"]]["rate"] = float(r["rate"])
            elif p == "/api/aliases": I[r["name"]]["aliases"] = aliases(r["aliases"])
            elif p == "/api/delete": I.pop(r["name"], None)
            elif p == "/api/meta": d["meta"]["shop"] = r.get("shop", d["meta"]["shop"])
            elif p == "/api/bill":                                 # finish bill: check stock, reduce stock, save invoice
                lines, sub, gst = [], 0, 0
                for k, q in r["lines"].items():
                    if k not in I or q > I[k]["stock"] + 1e-9: return self.send({"error": f"{k}: stock kam hai"})
                    a = round(q * I[k]["rate"], 2); sub += a; gst += a * I[k]["gst"] / 100
                    lines.append({"item": k, "qty": q, "unit": I[k]["unit"], "rate": I[k]["rate"], "gst": I[k]["gst"], "amount": a})
                    I[k]["stock"] = round(I[k]["stock"] - q, 3)
                if r.get("shop"): d["meta"]["shop"] = r["shop"]
                no = d["meta"]["no"]; d["meta"]["no"] += 1
                b = {"no": no, "date": datetime.now().strftime("%d-%m-%Y %H:%M"), "shop": d["meta"]["shop"], "lines": lines,
                     "sub": round(sub, 2), "gst": round(gst, 2), "total": round(sub + gst, 2)}
                os.makedirs(BILLS, exist_ok=True); json.dump(b, open(os.path.join(BILLS, f"bill_{no:04d}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                save(d); return self.send({"no": no, "total": b["total"]})
            save(d); self.send({"ok": 1})

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"Voice to Bill running: http://localhost:{port}   (Ctrl+C to stop)")
    threading.Timer(1, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

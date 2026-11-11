"""Paydesk: a small, fictional accounts-payable app that procedures are recorded against.

It has screens (index.html, Spanish or English with ?lang=es|en) and a JSON API that plays the
part of the real system's API: tooling/procedure_run.py creates fixtures through it before a run,
checks the saved data after it and deletes what it created. Data lives in memory only, and every
supplier is fictional.

Usage: python examples/procedure-demo/app/server.py [--port 8765] [--drift]

--drift renames the "Approve" button, as a vendor release might. The procedure that uses it then
fails at that step, and its guide is marked as no longer matching the system.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.0.0"
HERE = Path(__file__).resolve().parent
COST_CENTRES = [("CC-100", "Operations"), ("CC-200", "Marketing"), ("CC-300", "IT services"), ("CC-400", "Facilities")]
STATE: dict = {}
DRIFT = {'approve:"Aprobar"': 'approve:"Autorizar"', 'approve:"Approve"': 'approve:"Authorise"'}


def reset() -> None:
    STATE.clear()
    STATE.update(invoices={}, seq=7000)
    # background invoices so lists and searches are not empty
    for s, a in [("Demo Supplier Alpha", 840.0), ("Demo Supplier Beta", 2310.5), ("Demo Supplier Gamma", 6120.0)]:
        create({"supplier": s, "amount": a, "due": "+30d"})


def create(body: dict) -> dict:
    STATE["seq"] += 1
    num = f"INV-{STATE['seq']}"
    due = str(body.get("due") or "+30d")
    m = re.fullmatch(r"\+(\d+)d", due)
    if m:
        due = (date.today() + timedelta(days=int(m[1]))).isoformat()
    inv = {"number": num, "supplier": body.get("supplier", "Demo Supplier"), "amount": float(body.get("amount", 100)),
           "currency": "EUR", "due": due, "status": "received", "cost_centre": None, "notes": [], "approved_by": None}
    STATE["invoices"][num] = inv
    return inv


def view(i: dict) -> dict:
    last = i["notes"][-1] if i["notes"] else None
    return {**i, "notes_count": len(i["notes"]), "last_note_type": last and last["type"], "last_note_text": last and last["text"]}


class Handler(BaseHTTPRequestHandler):
    server_version = f"Paydesk/{VERSION}"

    def log_message(self, *a):  # quiet
        pass

    def send(self, code: int, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("X-App-Version", VERSION)
        self.end_headers()
        self.wfile.write(data)

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def inv(self, num: str):
        i = STATE["invoices"].get(num)
        if not i:
            self.send(404, {"error": f"invoice {num} not found"})
        return i

    def do_GET(self):
        path, _, query = self.path.partition("?")
        q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        if path in ("/", "/index.html"):
            page = (HERE / "index.html").read_bytes()
            if self.server.drift:
                for old, new in DRIFT.items():
                    page = page.replace(old.encode(), new.encode())
            return self.send(200, page, "text/html")
        if path == "/api/version":
            return self.send(200, {"app": "Paydesk", "version": VERSION})
        if path == "/api/cost-centres":
            text = q.get("q", "").lower().replace("+", " ")
            return self.send(200, [{"code": c, "name": n} for c, n in COST_CENTRES if text in (c + " " + n).lower()])
        if path == "/api/invoices":
            num = q.get("number", "").strip().upper()
            return self.send(200, [view(i) for i in STATE["invoices"].values() if not num or i["number"] == num])
        m = re.fullmatch(r"/api/invoices/([\w-]+)", path)
        if m and (i := self.inv(m[1])):
            return self.send(200, view(i))
        if not m:
            self.send(404, {"error": "not found"})

    def do_POST(self):
        b = self.body()
        if self.path == "/api/reset":
            reset()
            return self.send(200, {"ok": True})
        if self.path == "/api/invoices":
            return self.send(201, view(create(b)))
        m = re.fullmatch(r"/api/invoices/([\w-]+)/(notes|cost-centre|approval)", self.path)
        if not m:
            return self.send(404, {"error": "not found"})
        i = self.inv(m[1])
        if not i:
            return
        if m[2] == "notes":
            if b.get("type") not in ("internal", "supplier") or not b.get("text", "").strip():
                return self.send(400, {"error": "type and text are required"})
            i["notes"].append({"type": b["type"], "text": b["text"].strip(), "user": "demo.clerk", "at": datetime.now().strftime("%Y-%m-%d %H:%M")})
        elif m[2] == "cost-centre":
            if b.get("code") not in {c for c, _ in COST_CENTRES}:
                return self.send(400, {"error": "unknown cost centre"})
            i["cost_centre"] = b["code"]
        else:
            if i["status"] != "received":
                return self.send(409, {"error": f"invoice is {i['status']}"})
            i.update(status="approved", approved_by="demo.manager")
        self.send(200, view(i))

    def do_DELETE(self):
        m = re.fullmatch(r"/api/invoices/([\w-]+)", self.path)
        if m and STATE["invoices"].pop(m[1], None):
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--drift", action="store_true", help="rename the Approve button")
    a = ap.parse_args()
    reset()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.drift = a.drift
    print(f"Paydesk {VERSION} on http://127.0.0.1:{a.port}{' (drift: Approve renamed)' if a.drift else ''}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

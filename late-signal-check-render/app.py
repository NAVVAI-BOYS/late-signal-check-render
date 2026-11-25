"""The Late Signal Check: Render web service.

Serves the app, stores every lead, and gives the team a private leads sheet.
Storage is a convenience, never a startup dependency: if no disk can be
written, the app still runs, logs every lead to stdout and emails it.
"""
import csv
import io
import json
import os
import threading
import urllib.request
from datetime import datetime, timezone

from flask import Flask, Response, abort, jsonify, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)
LOCK = threading.Lock()

ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
NOTIFY_TO = os.environ.get("NOTIFY_TO", "")
NOTIFY_FROM = os.environ.get("NOTIFY_FROM", "Late Signal Check <onboarding@resend.dev>")
REQUESTED_DIR = os.environ.get("DATA_DIR", "/var/data")


def pick_data_dir():
    """Try the requested dir, then /var/data, then beside app.py, then /tmp."""
    for d in [REQUESTED_DIR, "/var/data", os.path.join(BASE, "data"), "/tmp/lsc-data"]:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".write-test")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            if d != REQUESTED_DIR:
                print(f"STORAGE fallback: {REQUESTED_DIR} not writable, using {d}", flush=True)
            return d
        except Exception as e:  # noqa: BLE001
            print(f"STORAGE skip {d}: {e}", flush=True)
    print("STORAGE none: leads go to logs and email only", flush=True)
    return None


DATA_DIR = pick_data_dir()
LEADS = os.path.join(DATA_DIR, "leads.json") if DATA_DIR else None
EPHEMERAL = DATA_DIR is not None and DATA_DIR != REQUESTED_DIR


def read_leads():
    if not LEADS or not os.path.exists(LEADS):
        return []
    try:
        with open(LEADS) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return []


def write_lead(lead):
    if not LEADS:
        raise RuntimeError("no writable storage")
    with LOCK:
        leads = read_leads()
        leads.append(lead)
        tmp = LEADS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(leads, f)
        os.replace(tmp, LEADS)


def send_email(lead):
    if not (RESEND_API_KEY and NOTIFY_TO):
        return False
    lines = [
        f"Name: {lead.get('name')}", f"Firm: {lead.get('org')}", f"Email: {lead.get('email')}",
        f"Role: {lead.get('seat')}", f"Result: {lead.get('band')} ({lead.get('overall')} / 10)",
        f"Weakest area: {lead.get('weakest')} ({lead.get('weakest_score')})", f"Goal: {lead.get('goal')}", "", "Gaps:",
    ]
    lines += [f"  {g.get('area')}: {g.get('answer')} ({g.get('score')})" for g in lead.get("gaps", [])]
    lines += ["", "Answers:"]
    for a in lead.get("answers", []):
        own = f' | own words: "{a.get("own_words")}"' if a.get("own_words") else ""
        lines.append(f"  {a.get('question')} -> {a.get('answer')}{own}")
    body = json.dumps({
        "from": NOTIFY_FROM, "to": [x.strip() for x in NOTIFY_TO.split(",") if x.strip()],
        "subject": f"New Late Signal Check lead: {lead.get('name')}, {lead.get('org')} ({lead.get('band')})",
        "text": "\n".join(lines),
    }).encode()
    req = urllib.request.Request("https://api.resend.com/emails", data=body, method="POST", headers={
        "Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001
        print(f"EMAIL failed: {e}", flush=True)
        return False


def clean(v, n=2000):
    return str(v)[:n] if v is not None else ""


@app.get("/")
def index():
    return send_from_directory(os.path.join(BASE, "static"), "index.html")


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


@app.get("/api/config")
def config():
    return jsonify(ok=True, email_enabled=bool(RESEND_API_KEY and NOTIFY_TO),
                   storage="none" if not DATA_DIR else ("ephemeral" if EPHEMERAL else "disk"))


@app.post("/api/lead")
def lead():
    d = request.get_json(silent=True) or {}
    if not (d.get("name") and d.get("org") and "@" in str(d.get("email", ""))):
        return jsonify(ok=False, error="name, org and email are required"), 400
    rec = {
        "received": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": clean(d.get("name"), 200), "org": clean(d.get("org"), 200), "email": clean(d.get("email"), 200),
        "seat": clean(d.get("seat"), 100), "band": clean(d.get("band"), 100),
        "overall": d.get("overall"), "weakest": clean(d.get("weakest"), 100), "weakest_score": d.get("weakest_score"),
        "goal": clean(d.get("goal"), 500),
        "gaps": [{k: clean(g.get(k), 500) for k in ("area", "question", "answer", "score")} for g in (d.get("gaps") or [])[:20]],
        "answers": [{k: clean(a.get(k), 1000) for k in ("question", "answer", "own_words")} for a in (d.get("answers") or [])[:30]],
    }
    print("LEAD " + json.dumps({k: rec[k] for k in ("name", "org", "email", "seat", "band", "overall")}), flush=True)
    stored = False
    try:
        write_lead(rec)
        stored = True
    except Exception as e:  # noqa: BLE001
        print(f"STORE failed: {e}", flush=True)
    emailed = send_email(rec)
    return jsonify(ok=True, stored=stored, emailed=emailed)


def check_key():
    if not ADMIN_KEY or request.args.get("key") != ADMIN_KEY:
        abort(401)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


@app.get("/admin/sheet")
def sheet():
    check_key()
    leads = sorted(read_leads(), key=lambda x: x.get("received", ""), reverse=True)
    banner = ""
    if not DATA_DIR:
        banner = '<p class="warn">No writable storage. Leads are only in the logs and email.</p>'
    elif EPHEMERAL:
        banner = '<p class="warn">Storage is temporary: the disk at ' + esc(REQUESTED_DIR) + ' is missing, so a redeploy wipes these leads.</p>'
    rows = "".join(
        "<tr><td>" + esc(l.get("received", "")) + "</td><td>" + esc(l.get("name", "")) + "</td><td>" + esc(l.get("org", ""))
        + "</td><td>" + esc(l.get("email", "")) + "</td><td>" + esc(l.get("seat", "")) + "</td><td>" + esc(l.get("band", ""))
        + "</td><td>" + esc(l.get("overall", "")) + "</td><td>" + esc(l.get("weakest", "")) + "</td><td>" + str(len(l.get("gaps", [])))
        + "</td><td>" + esc(l.get("goal", "")) + "</td></tr>" for l in leads)
    html = ("<!DOCTYPE html><html><head><meta charset='utf-8'><title>Leads</title><style>"
            "body{font-family:Inter,Arial,sans-serif;background:#000;color:#fff;padding:24px}"
            "table{border-collapse:collapse;width:100" + "%;font-size:14px}td,th{border-bottom:1px solid #333;padding:8px;text-align:left}"
            "th{color:#3890F8}.warn{color:#F2B544}a{color:#5EA6FF}</style></head><body>"
            "<h1>Late Signal Check leads (" + str(len(leads)) + ")</h1>" + banner
            + "<p><a href='/admin/leads.csv?key=" + esc(request.args.get("key")) + "'>Download CSV</a></p>"
            "<table><tr><th>Received</th><th>Name</th><th>Firm</th><th>Email</th><th>Role</th><th>Result</th><th>Score</th><th>Weakest</th><th>Gaps</th><th>Goal</th></tr>"
            + rows + "</table></body></html>")
    return Response(html, mimetype="text/html")


@app.get("/admin/leads.csv")
def leads_csv():
    check_key()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["received", "name", "org", "email", "seat", "band", "overall", "weakest", "weakest_score", "goal", "gaps", "answers"])
    for l in read_leads():
        w.writerow([l.get("received"), l.get("name"), l.get("org"), l.get("email"), l.get("seat"), l.get("band"), l.get("overall"),
                    l.get("weakest"), l.get("weakest_score"), l.get("goal"),
                    " | ".join(f"{g.get('area')}: {g.get('answer')}" for g in l.get("gaps", [])),
                    " | ".join(f"{a.get('question')} -> {a.get('answer')}" + (f" ({a.get('own_words')})" if a.get("own_words") else "") for a in l.get("answers", []))])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=leads.csv"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

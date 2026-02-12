# app.py
import sqlite3
import subprocess
import sys
import re
import io
import csv
import atexit
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, g, render_template, request, redirect, url_for, jsonify, Response
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Config
DB_PATH = "ip_monitor.db"
INIT_SQL = "init_db.sql"
CHECK_INTERVAL_SECONDS = 60  # background check every 60s
PING_TIMEOUT_SEC = 2  # seconds

app = Flask(__name__)

# ----------------------------
# Database helpers
# ----------------------------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    if Path(INIT_SQL).exists():
        with open(INIT_SQL, "r", encoding="utf-8") as f:
            db.executescript(f.read())
    else:
        # fallback schema
        db.executescript("""
        CREATE TABLE IF NOT EXISTS ips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL UNIQUE,
            name TEXT,
            device_type TEXT,
            importance TEXT,
            remark TEXT,
            last_status TEXT,
            last_ping_ms REAL,
            last_checked TEXT
        );
        CREATE TABLE IF NOT EXISTS ping_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            status TEXT NOT NULL,
            ping_ms REAL,
            FOREIGN KEY(ip_id) REFERENCES ips(id) ON DELETE CASCADE
        );
        """)
    db.commit()

@app.teardown_appcontext
def close_connection(exc):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# ----------------------------
# Ping helper (system ping)
# ----------------------------
def ping_host(ip):
    """
    Ping once and return (status, ms) where status is 'up' or 'down',
    ms is float ping in ms or None.
    Uses system ping command; works on Windows/Linux/macOS in most environments.
    """
    try:
        if sys.platform.startswith("win"):
            cmd = ["ping", "-n", "1", "-w", str(PING_TIMEOUT_SEC * 1000), ip]
        else:
            # Linux/macOS: -c 1 sends one packet
            cmd = ["ping", "-c", "1", ip]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=PING_TIMEOUT_SEC + 2)
        out = proc.stdout.lower()
        if proc.returncode == 0 and ("ttl=" in out or "bytes from" in out):
            ms = None
            m = re.search(r"time[=<]\s*([0-9]+(?:\.[0-9]+)?)\s*ms", out)
            if m:
                try:
                    ms = float(m.group(1))
                except:
                    ms = None
            return "up", ms
        else:
            return "down", None
    except Exception:
        return "down", None

# ----------------------------
# Store ping + uptime helpers
# ----------------------------
def store_ping(ip_id, status, ping_ms, ts=None):
    db = get_db()
    now = (ts or datetime.now(timezone.utc)).isoformat()
    db.execute("INSERT INTO ping_history (ip_id, ts, status, ping_ms) VALUES (?,?,?,?)",
               (ip_id, now, status, ping_ms))
    db.execute("UPDATE ips SET last_status=?, last_ping_ms=?, last_checked=? WHERE id=?",
               (status, ping_ms, now, ip_id))
    db.commit()

def uptime_percent(ip_id, minutes):
    db = get_db()
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    row = db.execute("SELECT COUNT(*) as total, SUM(CASE WHEN status='up' THEN 1 ELSE 0 END) as upcount FROM ping_history WHERE ip_id=? AND ts>=?",
                     (ip_id, since)).fetchone()
    total = row["total"] or 0
    upcount = row["upcount"] or 0
    if total == 0:
        # no data → treat as 100% to avoid false alarm, change to 0 if you want strict
        return 100.0
    return (upcount / total) * 100.0

# ----------------------------
# Background job: check all IPs
# ----------------------------
def check_all_and_store():
    with app.app_context():
        init_db()
        db = get_db()
        rows = db.execute("SELECT id, ip FROM ips").fetchall()
        for r in rows:
            ip_id = r["id"]
            ip_addr = r["ip"]
            status, ms = ping_host(ip_addr)
            store_ping(ip_id, status, ms)

# Scheduler
scheduler = BackgroundScheduler()
scheduler.start()
scheduler.add_job(
    func=check_all_and_store,
    trigger=IntervalTrigger(seconds=CHECK_INTERVAL_SECONDS),
    id="periodic-ip-check",
    name="Periodic IP check every {}s".format(CHECK_INTERVAL_SECONDS),
    replace_existing=True,
)
atexit.register(lambda: scheduler.shutdown(wait=False))

# ----------------------------
# Routes
# ----------------------------
@app.route("/")
def index():
    init_db()
    db = get_db()
    rows = db.execute("SELECT * FROM ips").fetchall()
    data = []
    for r in rows:
        ip_id = r["id"]
        last5 = round(uptime_percent(ip_id, 5), 2)
        last60 = round(uptime_percent(ip_id, 60), 2)
        data.append({
            "id": ip_id,
            "ip": r["ip"],
            "name": r["name"],
            "device_type": r["device_type"],
            "importance": r["importance"],
            "remark": r["remark"],
            "last_status": r["last_status"] or "unknown",
            "last_ping_ms": r["last_ping_ms"],
            "last_checked": r["last_checked"],
            "last5": last5,
            "last60": last60
        })
    # sort: down first
    data_sorted = sorted(data, key=lambda x: (0 if x["last_status"]=="down" else 1, x["ip"]))
    return render_template("index.html", ips=data_sorted)

@app.route("/add", methods=["GET","POST"])
def add_ip():
    init_db()
    if request.method == "POST":
        ip = request.form.get("ip","").strip()
        name = request.form.get("name","").strip()
        device_type = request.form.get("device_type","other")
        importance = request.form.get("importance","normal")
        remark = request.form.get("remark","").strip()
        if not ip:
            return "IP is required", 400
        db = get_db()
        try:
            cur = db.execute("INSERT INTO ips (ip, name, device_type, importance, remark) VALUES (?,?,?,?,?)",
                       (ip, name, device_type, importance, remark))
            db.commit()
            ip_id = cur.lastrowid
        except sqlite3.IntegrityError:
            # update existing
            db.execute("UPDATE ips SET name=?, device_type=?, importance=?, remark=? WHERE ip=?",
                       (name, device_type, importance, remark, ip))
            db.commit()
            ip_id = db.execute("SELECT id FROM ips WHERE ip=?", (ip,)).fetchone()["id"]
        # Do an immediate ping and store it
        status, ms = ping_host(ip)
        store_ping(ip_id, status, ms)
        return redirect(url_for("index"))
    # GET -> render form
    return render_template("add_ip.html")

@app.route("/ip/<int:ip_id>")
def ip_detail(ip_id):
    init_db()
    db = get_db()
    ip_row = db.execute("SELECT * FROM ips WHERE id=?", (ip_id,)).fetchone()
    if not ip_row:
        return "IP not found", 404
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    rows = db.execute("SELECT ts, status, ping_ms FROM ping_history WHERE ip_id=? AND ts>=? ORDER BY ts ASC",
                      (ip_id, since)).fetchall()
    history = [{"ts": r["ts"], "status": r["status"], "ping_ms": r["ping_ms"]} for r in rows]
    return render_template("ip_detail.html", ip=ip_row, history=history)

@app.route("/search")
def search_page():
    init_db()
    q = request.args.get("q","").strip()
    rows = []
    if q:
        db = get_db()
        rows = db.execute("SELECT * FROM ips WHERE ip LIKE ? OR name LIKE ? OR remark LIKE ? LIMIT 200",
                          (f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
    return render_template("search_results.html", results=rows, q=q)

@app.route("/api/check_all", methods=["POST"])
def api_check_all():
    init_db()
    db = get_db()
    ips = db.execute("SELECT * FROM ips").fetchall()
    results = []
    for ip in ips:
        ip_id = ip["id"]
        status, ms = ping_host(ip["ip"])
        store_ping(ip_id, status, ms)
        last5 = round(uptime_percent(ip_id, 5), 2)
        last60 = round(uptime_percent(ip_id, 60), 2)
        results.append({
            "id": ip_id,
            "ip": ip["ip"],
            "last_status": status,
            "last_ping_ms": ms,
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "last5": last5,
            "last60": last60
        })
    results_sorted = sorted(results, key=lambda r: (0 if r["last_status"]=="down" else 1, r["ip"]))
    return jsonify({"ips": results_sorted})

@app.route("/export_csv")
def export_csv():
    init_db()
    db = get_db()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["--- ips ---"])
    writer.writerow(["id","ip","name","device_type","importance","remark","last_status","last_ping_ms","last_checked"])
    for r in db.execute("SELECT * FROM ips ORDER BY id"):
        writer.writerow([r["id"], r["ip"], r["name"], r["device_type"], r["importance"], r["remark"], r["last_status"], r["last_ping_ms"], r["last_checked"]])
    writer.writerow([])
    writer.writerow(["--- ping_history ---"])
    writer.writerow(["id","ip_id","ts","status","ping_ms"])
    for r in db.execute("SELECT * FROM ping_history ORDER BY ts DESC LIMIT 10000"):
        writer.writerow([r["id"], r["ip_id"], r["ts"], r["status"], r["ping_ms"]])
    out.seek(0)
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=ip_monitor_export.csv"})

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)

#!/usr/bin/env python3
"""
Syslog server + Real-time web dashboard with SQLite persistence
Usage: sudo python3 server.py
"""

import json
import os
import re
import socket
import socketserver
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from collections import deque
from datetime import datetime, date
from pathlib import Path

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
import uvicorn

# ── Config ────────────────────────────────────────────────────────────────────
SYSLOG_HOST = "0.0.0.0"
WEB_PORT    = 8080
MEM_LOGS    = 2000          # logs kept in memory (latest)
DB_PATH     = Path(__file__).parent / "syslog.db"

SYSLOG_PORT = 514 if os.geteuid() == 0 else 5140

# ── SQLite ────────────────────────────────────────────────────────────────────
def db_connect():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_full  TEXT NOT NULL,
                src      TEXT,
                facility TEXT,
                severity TEXT,
                msg      TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON logs(ts_full)")
        conn.commit()

def db_insert(entry: dict):
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO logs (ts_full,src,facility,severity,msg) VALUES (?,?,?,?,?)",
            (entry["ts_full"], entry["src"], entry["facility"], entry["severity"], entry["msg"])
        )
        conn.commit()

def db_query(date_from: str, date_to: str, severity: str = "", src: str = "", keyword: str = "") -> list:
    sql = "SELECT * FROM logs WHERE ts_full >= ? AND ts_full < ?"
    params: list = [date_from, date_to + "T23:59:59"]
    if severity:
        sql += " AND severity = ?"; params.append(severity)
    if src:
        sql += " AND src = ?"; params.append(src)
    if keyword:
        sql += " AND msg LIKE ?"; params.append(f"%{keyword}%")
    sql += " ORDER BY ts_full DESC LIMIT 5000"
    with db_connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]

def db_dates() -> list[str]:
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT substr(ts_full,1,10) AS d FROM logs ORDER BY d DESC LIMIT 90"
        ).fetchall()
    return [r["d"] for r in rows]

def db_stats_by_day(days: int = 30) -> list:
    with db_connect() as conn:
        rows = conn.execute("""
            SELECT substr(ts_full,1,10) as day, severity, count(*) as cnt
            FROM logs
            WHERE ts_full >= date('now',?)
            GROUP BY day, severity
            ORDER BY day
        """, (f"-{days} days",)).fetchall()
    return [dict(r) for r in rows]

# ── Shared in-memory state ────────────────────────────────────────────────────
logs: deque = deque(maxlen=MEM_LOGS)
clients: list = []
lock = threading.Lock()

FACILITY = ["kern","user","mail","daemon","auth","syslog","lpr","news",
            "uucp","cron","authpriv","ftp","ntp","audit","alert","clock",
            "local0","local1","local2","local3","local4","local5","local6","local7"]
SEVERITY = ["emerg","alert","crit","err","warning","notice","info","debug"]

def parse_syslog(data: bytes, addr: tuple) -> dict:
    msg = data.decode("utf-8", errors="replace").strip()
    pri = 13; body = msg
    m = re.match(r"^<(\d+)>(.*)", msg)
    if m:
        pri = int(m.group(1)); body = m.group(2).strip()
    facility = FACILITY[pri >> 3] if (pri >> 3) < len(FACILITY) else str(pri >> 3)
    severity = SEVERITY[pri & 7]
    return {
        "ts":       datetime.now().strftime("%H:%M:%S"),
        "ts_full":  datetime.now().isoformat(timespec="seconds"),
        "src":      addr[0],
        "facility": facility,
        "severity": severity,
        "msg":      body[:512],
    }

def broadcast(entry: dict):
    payload = json.dumps(entry)
    dead = []
    for q in clients:
        try: q.put_nowait(payload)
        except Exception: dead.append(q)
    for q in dead:
        if q in clients: clients.remove(q)

# ── UDP syslog ────────────────────────────────────────────────────────────────
class SyslogHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data, _ = self.request
        entry = parse_syslog(data, self.client_address)
        with lock:
            logs.appendleft(entry)
        db_insert(entry)          # persist
        broadcast(entry)

class SyslogServer(socketserver.UDPServer):
    allow_reuse_address = True

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse((Path(__file__).parent / "templates" / "index.html").read_text())

@app.get("/api/logs")
async def get_logs():
    with lock:
        return list(logs)

@app.get("/api/history")
async def history(
    date_from: str = Query(default=""),
    date_to:   str = Query(default=""),
    severity:  str = Query(default=""),
    src:       str = Query(default=""),
    keyword:   str = Query(default=""),
):
    today = date.today().isoformat()
    if not date_from: date_from = today
    if not date_to:   date_to   = today
    rows = db_query(date_from + "T00:00:00", date_to, severity, src, keyword)
    return rows

@app.get("/api/history/dates")
async def history_dates():
    return db_dates()

@app.get("/api/history/chart")
async def history_chart(days: int = 30):
    return db_stats_by_day(days)

@app.get("/api/stream")
async def stream(request: Request):
    import queue
    q: queue.Queue = queue.Queue(maxsize=500)
    clients.append(q)
    async def event_gen():
        try:
            while True:
                if await request.is_disconnected(): break
                try:
                    data = q.get(timeout=1)
                    yield f"data: {data}\n\n"
                except Exception:
                    yield ": keepalive\n\n"
        finally:
            if q in clients: clients.remove(q)
    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# ── Startup: load recent logs into memory ─────────────────────────────────────
def preload_memory():
    today = date.today().isoformat()
    rows = db_query(today + "T00:00:00", today)
    with lock:
        for r in reversed(rows[:MEM_LOGS]):
            logs.appendleft(r)

# ── UDP threads ───────────────────────────────────────────────────────────────
def try_relay_514():
    try:
        raw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        raw.bind(("0.0.0.0", 514))
        print("[relay] UDP 514 listening")
        while True:
            data, addr = raw.recvfrom(4096)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(data, ("127.0.0.1", SYSLOG_PORT)); s.close()
    except PermissionError:
        pass
    except Exception as e:
        print(f"[relay] {e}")

def start_syslog():
    try:
        srv = SyslogServer((SYSLOG_HOST, SYSLOG_PORT), SyslogHandler)
        print(f"[syslog] UDP {SYSLOG_HOST}:{SYSLOG_PORT}")
        srv.serve_forever()
    except Exception as e:
        print(f"[syslog] {e}")

if __name__ == "__main__":
    db_init()
    preload_memory()
    print(f"[db] {DB_PATH}  ({sum(1 for _ in db_connect().execute('SELECT 1 FROM logs'))} rows)")

    if os.geteuid() != 0:
        threading.Thread(target=try_relay_514, daemon=True).start()
    threading.Thread(target=start_syslog, daemon=True).start()

    subprocess.run(["bash","-c","lsof -ti:8080 | xargs kill -9 2>/dev/null"], capture_output=True)
    time.sleep(0.5)
    print(f"[web] http://localhost:{WEB_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT, log_level="warning")

import os
import re
import json
import sqlite3
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HA_URL = os.getenv("HA_URL", "http://homeassistant.local:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
SNAPSHOT_DIR = os.getenv("SNAPSHOT_DIR", "/config/www/snapshots")
CAMERA_ENTITY = os.getenv("CAMERA_ENTITY", "camera.doorbell")
PERSON_SENSOR = os.getenv("PERSON_SENSOR", "binary_sensor.doorbell_person")
DB_PATH = os.getenv("DB_PATH", "babysitter.db")
TZ_NAME = os.getenv("TIMEZONE", "America/New_York")

# Pay rates
PEAK_START_HOUR = 9   # 9:00 AM inclusive
PEAK_END_HOUR = 15    # 3:00 PM exclusive (i.e. up to 14:59)
PEAK_RATE = 16.0      # $/hr
OFF_PEAK_RATE = 10.0  # $/hr

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                session_date       TEXT NOT NULL,
                arrival_time       TEXT,
                departure_time     TEXT,
                arrival_snapshot   TEXT,
                departure_snapshot TEXT,
                notes              TEXT,
                -- stored computed values so weekly totals need no recalculation
                total_hours        REAL DEFAULT 0,
                peak_hours         REAL DEFAULT 0,
                off_peak_hours     REAL DEFAULT 0,
                peak_pay           REAL DEFAULT 0,
                off_peak_pay       REAL DEFAULT 0,
                total_pay          REAL DEFAULT 0,
                created_at         TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                filename  TEXT UNIQUE NOT NULL,
                ts        TEXT NOT NULL,
                source    TEXT DEFAULT 'file'
            );
        """)

        # Migrate existing DBs that predate the pay columns
        existing = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
        for col, typ in [
            ("total_hours",    "REAL DEFAULT 0"),
            ("peak_hours",     "REAL DEFAULT 0"),
            ("off_peak_hours", "REAL DEFAULT 0"),
            ("peak_pay",       "REAL DEFAULT 0"),
            ("off_peak_pay",   "REAL DEFAULT 0"),
            ("total_pay",      "REAL DEFAULT 0"),
        ]:
            if col not in existing:
                db.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typ}")

        # Back-fill any rows that have times but zero pay (from before migration)
        db.execute("""
            UPDATE sessions SET total_hours = 0, peak_hours = 0, off_peak_hours = 0,
                peak_pay = 0, off_peak_pay = 0, total_pay = 0
            WHERE total_hours IS NULL
        """)


init_db()

# ---------------------------------------------------------------------------
# Helpers: timezone
# ---------------------------------------------------------------------------
def local_tz():
    try:
        return ZoneInfo(TZ_NAME)
    except Exception:
        return ZoneInfo("UTC")


def now_local():
    return datetime.now(tz=local_tz())


# ---------------------------------------------------------------------------
# Helpers: snapshot discovery
# ---------------------------------------------------------------------------
TIMESTAMP_PATTERNS = [
    # snapshot_2024-01-15_14-30-00.jpg  or  snapshot_2024-01-15T14:30:00.jpg
    re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})[T_](\d{2})[-:](\d{2})[-:](\d{2})"),
    # doorbell_20240115_143000
    re.compile(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})"),
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def parse_ts_from_filename(name: str):
    for pat in TIMESTAMP_PATTERNS:
        m = pat.search(name)
        if m:
            g = m.groups()
            try:
                return datetime(
                    int(g[0]), int(g[1]), int(g[2]),
                    int(g[3]), int(g[4]), int(g[5]),
                    tzinfo=local_tz(),
                )
            except ValueError:
                pass
    return None


def scan_snapshots():
    """Scan SNAPSHOT_DIR and upsert new files into the DB."""
    snap_path = Path(SNAPSHOT_DIR)
    if not snap_path.exists():
        return

    with get_db() as db:
        for f in snap_path.iterdir():
            if f.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            ts = parse_ts_from_filename(f.name)
            if ts is None:
                mtime = f.stat().st_mtime
                ts = datetime.fromtimestamp(mtime, tz=local_tz())
            ts_str = ts.isoformat()
            db.execute(
                "INSERT OR IGNORE INTO snapshots (filename, ts, source) VALUES (?, ?, 'file')",
                (f.name, ts_str),
            )


def ha_headers():
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


def fetch_ha_person_events(days_back: int = 14):
    """
    Query HA history API for person-detection state changes and cache them as
    synthetic snapshots (source='ha_event').
    """
    if not HA_TOKEN:
        return
    start = now_local() - timedelta(days=days_back)
    start_str = start.isoformat()
    url = f"{HA_URL}/api/history/period/{start_str}"
    params = {"filter_entity_id": PERSON_SENSOR, "minimal_response": "true"}
    try:
        resp = requests.get(url, headers=ha_headers(), params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return

    if not data or not data[0]:
        return

    with get_db() as db:
        for entry in data[0]:
            if entry.get("state") != "on":
                continue
            last_changed = entry.get("last_changed") or entry.get("last_updated")
            if not last_changed:
                continue
            try:
                ts = datetime.fromisoformat(last_changed.replace("Z", "+00:00"))
                ts = ts.astimezone(local_tz())
            except ValueError:
                continue
            # Use a synthetic filename so we can proxy the camera snapshot
            fake_filename = f"ha_event_{ts.strftime('%Y%m%d_%H%M%S')}.jpg"
            db.execute(
                "INSERT OR IGNORE INTO snapshots (filename, ts, source) VALUES (?, ?, 'ha_event')",
                (fake_filename, ts.isoformat()),
            )


# ---------------------------------------------------------------------------
# Helpers: pay calculation
# ---------------------------------------------------------------------------
def calculate_pay(arrival: datetime, departure: datetime) -> dict:
    if departure <= arrival:
        return {
            "total_hours": 0, "peak_hours": 0, "off_peak_hours": 0,
            "peak_pay": 0, "off_peak_pay": 0, "total_pay": 0,
        }

    # Build peak window for the same day as arrival
    peak_start = arrival.replace(hour=PEAK_START_HOUR, minute=0, second=0, microsecond=0)
    peak_end = arrival.replace(hour=PEAK_END_HOUR, minute=0, second=0, microsecond=0)

    def secs(a, b) -> float:
        delta = b - a
        return max(0.0, delta.total_seconds())

    # Segment 1: arrival → peak_start  (off-peak)
    seg1 = secs(arrival, min(peak_start, departure))
    # Segment 2: peak_start → peak_end  (peak)
    seg2 = secs(max(arrival, peak_start), min(departure, peak_end))
    # Segment 3: peak_end → departure  (off-peak)
    seg3 = secs(max(arrival, peak_end), departure)

    off_peak_hours = (seg1 + seg3) / 3600.0
    peak_hours = seg2 / 3600.0
    total_hours = off_peak_hours + peak_hours

    return {
        "total_hours": round(total_hours, 4),
        "peak_hours": round(peak_hours, 4),
        "off_peak_hours": round(off_peak_hours, 4),
        "peak_pay": round(peak_hours * PEAK_RATE, 2),
        "off_peak_pay": round(off_peak_hours * OFF_PEAK_RATE, 2),
        "total_pay": round(peak_hours * PEAK_RATE + off_peak_hours * OFF_PEAK_RATE, 2),
    }


def _persist_pay(session_id: int, pay: dict):
    """Write computed pay columns back to a session row."""
    with get_db() as db:
        db.execute(
            """UPDATE sessions SET
                total_hours    = ?,
                peak_hours     = ?,
                off_peak_hours = ?,
                peak_pay       = ?,
                off_peak_pay   = ?,
                total_pay      = ?
               WHERE id = ?""",
            (
                pay["total_hours"],
                pay["peak_hours"],
                pay["off_peak_hours"],
                pay["peak_pay"],
                pay["off_peak_pay"],
                pay["total_pay"],
                session_id,
            ),
        )


def week_bounds(iso_week_str: str):
    """Return (monday, sunday) date objects for a given 'YYYY-Www' string."""
    year, week = iso_week_str.split("-W")
    monday = date.fromisocalendar(int(year), int(week), 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


# ---------------------------------------------------------------------------
# Routes: pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html",
                           camera_entity=CAMERA_ENTITY,
                           ha_url=HA_URL)


# ---------------------------------------------------------------------------
# Routes: snapshots API
# ---------------------------------------------------------------------------
@app.route("/api/snapshots/refresh", methods=["POST"])
def refresh_snapshots():
    scan_snapshots()
    fetch_ha_person_events()
    return jsonify({"ok": True})


@app.route("/api/snapshots")
def list_snapshots():
    scan_snapshots()
    date_filter = request.args.get("date")   # YYYY-MM-DD
    week_filter = request.args.get("week")   # YYYY-Www

    query = "SELECT id, filename, ts, source FROM snapshots"
    params = []

    conditions = []
    if date_filter:
        conditions.append("date(ts) = ?")
        params.append(date_filter)
    elif week_filter:
        try:
            monday, sunday = week_bounds(week_filter)
            conditions.append("date(ts) BETWEEN ? AND ?")
            params += [monday.isoformat(), sunday.isoformat()]
        except (ValueError, AttributeError):
            pass

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY ts DESC"

    with get_db() as db:
        rows = db.execute(query, params).fetchall()

    return jsonify([dict(r) for r in rows])


@app.route("/api/snapshots/<int:snap_id>/image")
def snapshot_image(snap_id: int):
    with get_db() as db:
        row = db.execute(
            "SELECT filename, source FROM snapshots WHERE id = ?", (snap_id,)
        ).fetchone()

    if not row:
        return ("Not found", 404)

    filename, source = row["filename"], row["source"]

    if source == "file":
        return send_from_directory(SNAPSHOT_DIR, filename)

    # ha_event: proxy the live camera snapshot (best-effort)
    if not HA_TOKEN:
        return ("No HA token configured", 503)
    try:
        url = f"{HA_URL}/api/camera_proxy/{CAMERA_ENTITY}"
        r = requests.get(url, headers=ha_headers(), timeout=10, stream=True)
        r.raise_for_status()
        return Response(r.content, content_type=r.headers.get("Content-Type", "image/jpeg"))
    except Exception as exc:
        return (f"Could not fetch camera snapshot: {exc}", 502)


# ---------------------------------------------------------------------------
# Routes: sessions API
# ---------------------------------------------------------------------------
@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    week_filter = request.args.get("week")
    query = "SELECT * FROM sessions"
    params = []
    if week_filter:
        try:
            monday, sunday = week_bounds(week_filter)
            query += " WHERE session_date BETWEEN ? AND ?"
            params = [monday.isoformat(), sunday.isoformat()]
        except (ValueError, AttributeError):
            pass
    query += " ORDER BY session_date ASC, arrival_time ASC"

    with get_db() as db:
        rows = db.execute(query, params).fetchall()

    sessions = []
    for r in rows:
        s = dict(r)
        # Return stored pay values; embed as nested dict for frontend compatibility
        if s.get("arrival_time") and s.get("departure_time") and s.get("total_pay", 0):
            s["pay"] = {
                "total_hours":    s["total_hours"],
                "peak_hours":     s["peak_hours"],
                "off_peak_hours": s["off_peak_hours"],
                "peak_pay":       s["peak_pay"],
                "off_peak_pay":   s["off_peak_pay"],
                "total_pay":      s["total_pay"],
            }
        elif s.get("arrival_time") and s.get("departure_time"):
            # Row exists but pay cols are 0 (e.g. migrated row) — compute & patch
            arr = datetime.fromisoformat(s["arrival_time"]).replace(tzinfo=local_tz())
            dep = datetime.fromisoformat(s["departure_time"]).replace(tzinfo=local_tz())
            pay = calculate_pay(arr, dep)
            _persist_pay(s["id"], pay)
            s.update(pay)
            s["pay"] = pay
        else:
            s["pay"] = None
        sessions.append(s)
    return jsonify(sessions)


@app.route("/api/sessions", methods=["POST"])
def create_session():
    body = request.get_json(force=True)
    required = ("session_date", "arrival_time", "departure_time")
    if not all(body.get(k) for k in required):
        return jsonify({"error": "session_date, arrival_time, departure_time are required"}), 400

    arr = datetime.fromisoformat(body["arrival_time"]).replace(tzinfo=local_tz())
    dep = datetime.fromisoformat(body["departure_time"]).replace(tzinfo=local_tz())
    pay = calculate_pay(arr, dep)

    with get_db() as db:
        cur = db.execute(
            """INSERT INTO sessions
               (session_date, arrival_time, departure_time,
                arrival_snapshot, departure_snapshot, notes,
                total_hours, peak_hours, off_peak_hours,
                peak_pay, off_peak_pay, total_pay)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                body["session_date"],
                body["arrival_time"],
                body["departure_time"],
                body.get("arrival_snapshot"),
                body.get("departure_snapshot"),
                body.get("notes", ""),
                pay["total_hours"],
                pay["peak_hours"],
                pay["off_peak_hours"],
                pay["peak_pay"],
                pay["off_peak_pay"],
                pay["total_pay"],
            ),
        )
        session_id = cur.lastrowid

    return jsonify({"ok": True, "id": session_id, "pay": pay}), 201


@app.route("/api/sessions/<int:session_id>", methods=["PUT"])
def update_session(session_id: int):
    body = request.get_json(force=True)
    fields = ["session_date", "arrival_time", "departure_time",
              "arrival_snapshot", "departure_snapshot", "notes"]
    updates = {k: body[k] for k in fields if k in body}
    if not updates:
        return jsonify({"error": "Nothing to update"}), 400

    # If times changed, recalculate and store pay
    if "arrival_time" in updates or "departure_time" in updates:
        with get_db() as db:
            row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row:
            arr_str = updates.get("arrival_time")   or row["arrival_time"]
            dep_str = updates.get("departure_time") or row["departure_time"]
            if arr_str and dep_str:
                arr = datetime.fromisoformat(arr_str).replace(tzinfo=local_tz())
                dep = datetime.fromisoformat(dep_str).replace(tzinfo=local_tz())
                pay = calculate_pay(arr, dep)
                updates.update({
                    "total_hours":    pay["total_hours"],
                    "peak_hours":     pay["peak_hours"],
                    "off_peak_hours": pay["off_peak_hours"],
                    "peak_pay":       pay["peak_pay"],
                    "off_peak_pay":   pay["off_peak_pay"],
                    "total_pay":      pay["total_pay"],
                })

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [session_id]

    with get_db() as db:
        db.execute(f"UPDATE sessions SET {set_clause} WHERE id = ?", params)

    return jsonify({"ok": True})


@app.route("/api/sessions/<int:session_id>", methods=["DELETE"])
def delete_session(session_id: int):
    with get_db() as db:
        db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes: weekly summary
# ---------------------------------------------------------------------------
@app.route("/api/summary/week/<week>")
def weekly_summary(week: str):
    try:
        monday, sunday = week_bounds(week)
    except (ValueError, AttributeError):
        return jsonify({"error": "Invalid week format, use YYYY-Www"}), 400

    with get_db() as db:
        # Per-session rows (for the day breakdown)
        rows = db.execute(
            """SELECT * FROM sessions
               WHERE session_date BETWEEN ? AND ?
               ORDER BY session_date ASC, arrival_time ASC""",
            (monday.isoformat(), sunday.isoformat()),
        ).fetchall()

        # Per-day aggregates — stored values, pure SQL sum
        day_rows = db.execute(
            """SELECT
                 session_date,
                 COUNT(*)                    AS session_count,
                 ROUND(SUM(total_hours),    4) AS total_hours,
                 ROUND(SUM(peak_hours),     4) AS peak_hours,
                 ROUND(SUM(off_peak_hours), 4) AS off_peak_hours,
                 ROUND(SUM(peak_pay),       2) AS peak_pay,
                 ROUND(SUM(off_peak_pay),   2) AS off_peak_pay,
                 ROUND(SUM(total_pay),      2) AS total_pay
               FROM sessions
               WHERE session_date BETWEEN ? AND ?
               GROUP BY session_date
               ORDER BY session_date ASC""",
            (monday.isoformat(), sunday.isoformat()),
        ).fetchall()

        # Weekly totals — pure SQL, no Python arithmetic
        week_row = db.execute(
            """SELECT
                 ROUND(SUM(total_hours),    4) AS total_hours,
                 ROUND(SUM(peak_hours),     4) AS peak_hours,
                 ROUND(SUM(off_peak_hours), 4) AS off_peak_hours,
                 ROUND(SUM(peak_pay),       2) AS peak_pay,
                 ROUND(SUM(off_peak_pay),   2) AS off_peak_pay,
                 ROUND(SUM(total_pay),      2) AS total_pay
               FROM sessions
               WHERE session_date BETWEEN ? AND ?""",
            (monday.isoformat(), sunday.isoformat()),
        ).fetchone()

    # Shape sessions into per-day buckets
    days = {}
    for r in rows:
        s = dict(r)
        s["pay"] = {
            "total_hours":    s["total_hours"],
            "peak_hours":     s["peak_hours"],
            "off_peak_hours": s["off_peak_hours"],
            "peak_pay":       s["peak_pay"],
            "off_peak_pay":   s["off_peak_pay"],
            "total_pay":      s["total_pay"],
        } if s.get("total_pay") else None
        days.setdefault(s["session_date"], []).append(s)

    day_totals = [dict(d) for d in day_rows]

    totals = dict(week_row) if week_row else {
        "total_hours": 0, "peak_hours": 0, "off_peak_hours": 0,
        "peak_pay": 0, "off_peak_pay": 0, "total_pay": 0,
    }
    # Replace None (empty week) with zeros
    totals = {k: (v or 0) for k, v in totals.items()}

    return jsonify({
        "week":       week,
        "monday":     monday.isoformat(),
        "sunday":     sunday.isoformat(),
        "days":       days,
        "day_totals": day_totals,   # list of per-day aggregate rows
        "totals":     totals,       # single week aggregate
    })


# ---------------------------------------------------------------------------
# Routes: current week helper
# ---------------------------------------------------------------------------
@app.route("/api/current_week")
def current_week():
    today = now_local().date()
    iso = today.isocalendar()
    return jsonify({"week": f"{iso.year}-W{iso.week:02d}", "today": today.isoformat()})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1")

import json
import os
import sqlite3
import subprocess
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_file,
    abort,
)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OPTIONS_FILE = "/data/options.json"
DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "sessions.db"
THUMBS_DIR = DATA_DIR / "thumbs"
THUMBS_DIR.mkdir(parents=True, exist_ok=True)

RATE_PEAK = 10.0
RATE_OFFPEAK = 16.0
PEAK_START = 9   # 9 AM (inclusive)
PEAK_END = 15    # 3 PM (exclusive)


def get_config() -> dict:
    if OPTIONS_FILE and Path(OPTIONS_FILE).exists():
        with open(OPTIONS_FILE) as f:
            return json.load(f)
    return {
        "camera_entity": os.getenv("CAMERA_ENTITY", "camera.front_door"),
        "person_sensor": os.getenv("PERSON_SENSOR", "event.front_door_bell_motion"),
        "snapshot_subdir": os.getenv("SNAPSHOT_DIR", ".cache/nest/event_media"),
        "timezone": os.getenv("TIMEZONE", "America/New_York"),
    }


def get_tz():
    return ZoneInfo(get_config().get("timezone", "America/New_York"))


def clips_dir() -> Path:
    subdir = get_config().get("snapshot_subdir", ".cache/nest/event_media")
    return Path("/config") / subdir


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         TEXT    NOT NULL,
            arrived      TEXT    NOT NULL,
            departed     TEXT    NOT NULL,
            arrived_clip TEXT,
            departed_clip TEXT,
            hours_total  REAL    NOT NULL,
            hours_peak   REAL    NOT NULL,
            hours_offpeak REAL   NOT NULL,
            pay_peak     REAL    NOT NULL,
            pay_offpeak  REAL    NOT NULL,
            pay_total    REAL    NOT NULL,
            created_at   TEXT    NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Pay calculation
# ---------------------------------------------------------------------------

def calculate_pay(arrived_dt: datetime, departed_dt: datetime) -> dict:
    """Split a session at 9 AM and 3 PM boundaries and compute pay."""
    def same_day_boundary(dt, hour):
        return dt.replace(hour=hour, minute=0, second=0, microsecond=0)

    boundaries = [
        same_day_boundary(arrived_dt, PEAK_START),
        same_day_boundary(arrived_dt, PEAK_END),
    ]
    points = sorted(
        {arrived_dt, departed_dt} | {b for b in boundaries if arrived_dt < b < departed_dt}
    )

    hours_peak = 0.0
    hours_offpeak = 0.0

    for start, end in zip(points, points[1:]):
        seg_hours = (end - start).total_seconds() / 3600
        hour_frac = start.hour + start.minute / 60
        if PEAK_START <= hour_frac < PEAK_END:
            hours_peak += seg_hours
        else:
            hours_offpeak += seg_hours

    return {
        "hours_total": round(hours_peak + hours_offpeak, 4),
        "hours_peak": round(hours_peak, 4),
        "hours_offpeak": round(hours_offpeak, 4),
        "pay_peak": round(hours_peak * RATE_PEAK, 2),
        "pay_offpeak": round(hours_offpeak * RATE_OFFPEAK, 2),
        "pay_total": round(hours_peak * RATE_PEAK + hours_offpeak * RATE_OFFPEAK, 2),
    }


# ---------------------------------------------------------------------------
# Clip scanning
# ---------------------------------------------------------------------------

def week_bounds(week_str: str | None, tz) -> tuple[datetime, datetime]:
    """Return (Monday 00:00, Sunday 23:59:59) for the given ISO week string."""
    if week_str:
        year, week = map(int, week_str.split("-W"))
        monday = datetime.fromisocalendar(year, week, 1)
    else:
        today = datetime.now(tz).date()
        monday = today - timedelta(days=today.weekday())
    start = datetime(monday.year, monday.month, monday.day, tzinfo=tz)
    end = start + timedelta(days=7) - timedelta(seconds=1)
    return start, end


def scan_clips(week_str: str | None = None, date_str: str | None = None) -> list[dict]:
    tz = get_tz()
    base = clips_dir()
    if not base.exists():
        return []

    start, end = week_bounds(week_str, tz)
    results = []

    for path in sorted(base.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        mtime = path.stat().st_mtime
        clip_dt = datetime.fromtimestamp(mtime, tz=tz)

        if not (start <= clip_dt <= end):
            continue
        if date_str and clip_dt.strftime("%Y-%m-%d") != date_str:
            continue

        rel = str(path.relative_to(base))
        results.append({
            "path": rel,
            "datetime": clip_dt.isoformat(),
            "date": clip_dt.strftime("%Y-%m-%d"),
            "time": clip_dt.strftime("%I:%M %p"),
            "time24": clip_dt.strftime("%H:%M"),
            "ts": int(mtime),
        })

    return results


def thumb_path_for(rel: str) -> Path:
    key = hashlib.md5(rel.encode()).hexdigest()
    return THUMBS_DIR / f"{key}.jpg"


def ensure_thumb(rel: str) -> Path | None:
    tp = thumb_path_for(rel)
    if tp.exists():
        return tp
    src = clips_dir() / rel
    if not src.exists():
        return None
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(src),
                "-frames:v", "1",
                "-q:v", "3",
                "-vf", "scale=320:-1",
                str(tp),
            ],
            capture_output=True,
            timeout=15,
        )
        return tp if tp.exists() else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — clips
# ---------------------------------------------------------------------------

@app.route("/api/clips")
def api_clips():
    week = request.args.get("week")
    date = request.args.get("date")
    return jsonify(scan_clips(week, date))


@app.route("/api/clips/weeks")
def api_clips_weeks():
    """Return list of ISO week strings that have clips."""
    tz = get_tz()
    base = clips_dir()
    weeks = set()
    if base.exists():
        for path in base.rglob("*.mp4"):
            dt = datetime.fromtimestamp(path.stat().st_mtime, tz=tz)
            weeks.add(dt.strftime("%Y-W%V"))
    return jsonify(sorted(weeks, reverse=True))


@app.route("/video/<path:rel>")
def serve_video(rel):
    src = clips_dir() / rel
    if not src.exists() or not src.is_file():
        abort(404)
    # Prevent path traversal
    try:
        src.relative_to(clips_dir())
    except ValueError:
        abort(403)
    return send_file(src, mimetype="video/mp4", conditional=True)


@app.route("/thumb/<path:rel>")
def serve_thumb(rel):
    tp = ensure_thumb(rel)
    if tp is None:
        abort(404)
    return send_file(tp, mimetype="image/jpeg")


# ---------------------------------------------------------------------------
# Routes — pay preview
# ---------------------------------------------------------------------------

@app.route("/api/preview")
def api_preview():
    tz = get_tz()
    arrived = request.args.get("arrived")   # ISO datetime string
    departed = request.args.get("departed")
    if not arrived or not departed:
        return jsonify({"error": "arrived and departed required"}), 400
    try:
        a = datetime.fromisoformat(arrived).replace(tzinfo=tz)
        d = datetime.fromisoformat(departed).replace(tzinfo=tz)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if d <= a:
        return jsonify({"error": "departed must be after arrived"}), 400
    return jsonify(calculate_pay(a, d))


# ---------------------------------------------------------------------------
# Routes — sessions
# ---------------------------------------------------------------------------

@app.route("/api/sessions", methods=["GET"])
def api_sessions_list():
    week = request.args.get("week")
    tz = get_tz()
    start, end = week_bounds(week, tz)

    conn = db()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE date >= ? AND date <= ? ORDER BY arrived DESC",
        (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/sessions", methods=["POST"])
def api_sessions_create():
    data = request.json
    tz = get_tz()
    required = ("arrived", "departed")
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    try:
        a = datetime.fromisoformat(data["arrived"]).replace(tzinfo=tz)
        d = datetime.fromisoformat(data["departed"]).replace(tzinfo=tz)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if d <= a:
        return jsonify({"error": "departed must be after arrived"}), 400

    session_date = a.strftime("%Y-%m-%d")
    pay = calculate_pay(a, d)
    conn = db()

    # Delete any existing session for the same date (enforce one session per date)
    existing = conn.execute(
        "SELECT id FROM sessions WHERE date=?", (session_date,)
    ).fetchone()
    replaced = existing is not None
    if replaced:
        conn.execute("DELETE FROM sessions WHERE date=?", (session_date,))

    cur = conn.execute(
        """INSERT INTO sessions
           (date, arrived, departed, arrived_clip, departed_clip,
            hours_total, hours_peak, hours_offpeak,
            pay_peak, pay_offpeak, pay_total, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            a.strftime("%Y-%m-%d"),
            a.isoformat(),
            d.isoformat(),
            data.get("arrived_clip"),
            data.get("departed_clip"),
            pay["hours_total"],
            pay["hours_peak"],
            pay["hours_offpeak"],
            pay["pay_peak"],
            pay["pay_offpeak"],
            pay["pay_total"],
            datetime.now(tz).isoformat(),
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    result = dict(row)
    result["replaced"] = replaced
    return jsonify(result), 201


@app.route("/api/sessions/check-date")
def api_sessions_check_date():
    date = request.args.get("date")
    if not date:
        return jsonify({"error": "date is required"}), 400
    conn = db()
    row = conn.execute("SELECT id, arrived, departed FROM sessions WHERE date=?", (date,)).fetchone()
    conn.close()
    if row:
        return jsonify({"exists": True, "session": dict(row)})
    return jsonify({"exists": False})


@app.route("/api/sessions/<int:session_id>", methods=["DELETE"])
def api_sessions_delete(session_id):
    conn = db()
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()
    return "", 204


# ---------------------------------------------------------------------------
# Routes — weekly summary
# ---------------------------------------------------------------------------

@app.route("/api/weekly-summary")
def api_weekly_summary():
    week = request.args.get("week")
    tz = get_tz()
    start, end = week_bounds(week, tz)

    conn = db()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE date >= ? AND date <= ? ORDER BY arrived",
        (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
    ).fetchall()
    conn.close()

    by_date: dict[str, list] = {}
    totals = {"hours_total": 0.0, "hours_peak": 0.0, "hours_offpeak": 0.0,
               "pay_peak": 0.0, "pay_offpeak": 0.0, "pay_total": 0.0}

    for r in rows:
        d = r["date"]
        by_date.setdefault(d, []).append(dict(r))
        for k in totals:
            totals[k] += r[k]

    for k in totals:
        totals[k] = round(totals[k], 2)

    return jsonify({"by_date": by_date, "totals": totals,
                    "week": week or datetime.now(tz).strftime("%Y-W%V")})


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    cfg = get_config()
    print(f"[babysitter-tracker] Clips folder: {clips_dir()}")
    print(f"[babysitter-tracker] Timezone: {cfg.get('timezone')}")
    app.run(host="0.0.0.0", port=8099, debug=False)

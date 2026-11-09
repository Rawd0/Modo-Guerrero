"""Acceso a SQLite."""
import json
import sqlite3
import threading
import zlib
from contextlib import contextmanager

from .config import DB_PATH, DEFAULT_SETTINGS

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    name TEXT,
    sport TEXT,
    is_run INTEGER DEFAULT 0,
    start_local TEXT,
    start_utc TEXT,
    date TEXT,
    distance_m REAL,
    duration_s REAL,
    moving_s REAL,
    avg_speed REAL,
    max_speed REAL,
    avg_hr REAL,
    max_hr REAL,
    calories REAL,
    elev_gain REAL,
    elev_loss REAL,
    cadence REAL,
    aerobic_te REAL,
    anaerobic_te REAL,
    training_load REAL,
    vo2max REAL,
    start_lat REAL,
    start_lon REAL,
    source TEXT DEFAULT 'garmin',
    fit_status TEXT DEFAULT 'pending',
    raw TEXT
);
CREATE INDEX IF NOT EXISTS ix_act_date ON activities(date);
CREATE INDEX IF NOT EXISTS ix_act_run ON activities(is_run, date);
CREATE TABLE IF NOT EXISTS streams (
    activity_id INTEGER PRIMARY KEY,
    data BLOB
);
CREATE TABLE IF NOT EXISTS best_efforts (
    activity_id INTEGER,
    distance_m REAL,
    time_s REAL,
    PRIMARY KEY (activity_id, distance_m)
);
CREATE TABLE IF NOT EXISTS daily_health (
    date TEXT PRIMARY KEY,
    sleep_s REAL, sleep_score REAL, deep_s REAL, rem_s REAL, light_s REAL, awake_s REAL,
    hrv_night REAL, hrv_weekly REAL, hrv_status TEXT, hrv_low REAL, hrv_high REAL,
    rhr REAL, bb_high REAL, bb_low REAL, bb_last REAL, stress_avg REAL, steps REAL,
    readiness REAL, readiness_level TEXT,
    raw TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    date TEXT PRIMARY KEY,
    vo2max REAL, training_status TEXT, status_phrase TEXT,
    acute_load REAL, chronic_load REAL, acwr REAL,
    race_5k REAL, race_10k REAL, race_hm REAL, race_m REAL,
    raw TEXT
);
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT, finished TEXT, status TEXT, message TEXT
);
"""


def connect():
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def tx():
    with _lock:
        con = connect()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def init():
    with tx() as con:
        con.executescript(SCHEMA)


def rows(sql, params=()):
    with tx() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def one(sql, params=()):
    with tx() as con:
        r = con.execute(sql, params).fetchone()
        return dict(r) if r else None


def execute(sql, params=()):
    with tx() as con:
        con.execute(sql, params)


def upsert(table, data: dict, key: str):
    cols = list(data.keys())
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != key)
    sql = (f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT({key}) DO UPDATE SET {updates}")
    with tx() as con:
        con.execute(sql, [data[c] for c in cols])


# --- ajustes ---
def get_setting(key, default=None):
    r = one("SELECT value FROM settings WHERE key=?", (key,))
    if r is None:
        return DEFAULT_SETTINGS.get(key, default)
    return json.loads(r["value"])


def set_setting(key, value):
    upsert("settings", {"key": key, "value": json.dumps(value)}, "key")


def all_settings():
    out = dict(DEFAULT_SETTINGS)
    for r in rows("SELECT key, value FROM settings"):
        if r["key"] in DEFAULT_SETTINGS:
            out[r["key"]] = json.loads(r["value"])
    # widgets: añadir los nuevos que no estén en la configuración guardada
    known = {w["id"] for w in out["widgets"]}
    for w in DEFAULT_SETTINGS["widgets"]:
        if w["id"] not in known:
            out["widgets"].append(dict(w, visible=False))
    return out


# --- streams comprimidos ---
def save_stream(activity_id, data: dict):
    blob = zlib.compress(json.dumps(data, separators=(",", ":")).encode())
    upsert("streams", {"activity_id": activity_id, "data": blob}, "activity_id")


def load_stream(activity_id):
    r = one("SELECT data FROM streams WHERE activity_id=?", (activity_id,))
    if not r:
        return None
    return json.loads(zlib.decompress(r["data"]).decode())

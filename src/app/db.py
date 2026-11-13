"""Acceso a SQLite.

Cada dato pertenece a un usuario (columna user_id). user_id = 0 significa "sin asignar":
se usa para los datos que existían antes de haber usuarios (versiones < 0.4.0) y para los
datos de demostración; pasan al primer administrador en cuanto existe.
"""
import json
import logging
import sqlite3
import threading
import zlib
from contextlib import contextmanager

from .config import DB_PATH, DEFAULT_SETTINGS

log = logging.getLogger("guerrero.db")
_lock = threading.RLock()
SCHEMA_VERSION = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 0,
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
    gap_pace REAL,
    derived_v INTEGER DEFAULT 0,
    shoe_id INTEGER,
    route_id INTEGER,
    raw TEXT
);
CREATE INDEX IF NOT EXISTS ix_act_date ON activities(date);
CREATE INDEX IF NOT EXISTS ix_act_user_run ON activities(user_id, is_run, date);
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
CREATE TABLE IF NOT EXISTS best_durations (
    activity_id INTEGER,
    duration_s INTEGER,
    dist_m REAL,
    PRIMARY KEY (activity_id, duration_s)
);
CREATE INDEX IF NOT EXISTS ix_bd_dur ON best_durations(duration_s);
CREATE TABLE IF NOT EXISTS shoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    brand TEXT,
    start_date TEXT,
    initial_km REAL DEFAULT 0,
    limit_km REAL DEFAULT 700,
    retired INTEGER DEFAULT 0,
    is_default INTEGER DEFAULT 0,
    notes TEXT,
    created TEXT
);
CREATE INDEX IF NOT EXISTS ix_shoes_user ON shoes(user_id);
CREATE TABLE IF NOT EXISTS races (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    date TEXT NOT NULL,
    distance_m REAL NOT NULL,
    goal_time_s REAL,
    priority TEXT DEFAULT 'A',
    notes TEXT,
    result_activity_id INTEGER,
    result_manual INTEGER DEFAULT 0,
    created TEXT
);
CREATE INDEX IF NOT EXISTS ix_races_user ON races(user_id, date);
CREATE TABLE IF NOT EXISTS training_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    race_id INTEGER NOT NULL,
    params TEXT, paces TEXT, weeks TEXT,
    created TEXT, updated TEXT
);
CREATE INDEX IF NOT EXISTS ix_plans_user ON training_plans(user_id, race_id);
CREATE TABLE IF NOT EXISTS plan_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    type TEXT, title TEXT, description TEXT,
    distance_km REAL, target_pace REAL,
    status TEXT DEFAULT 'planned',
    activity_id INTEGER,
    manual INTEGER DEFAULT 0,
    execution TEXT
);
CREATE INDEX IF NOT EXISTS ix_psess_plan ON plan_sessions(plan_id, date);
CREATE INDEX IF NOT EXISTS ix_psess_user ON plan_sessions(user_id, date);
CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT,
    rep_activity_id INTEGER
);
CREATE TABLE IF NOT EXISTS route_sigs (
    activity_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    start_lat REAL, start_lon REAL, end_lat REAL, end_lon REAL,
    dist_m REAL, pts TEXT
);
CREATE INDEX IF NOT EXISTS ix_rsig ON route_sigs(user_id, dist_m);
CREATE TABLE IF NOT EXISTS strava_activities (
    strava_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    activity_id INTEGER,
    name TEXT,
    kudos INTEGER, achievements INTEGER, prs INTEGER, comments INTEGER,
    detail_fetched INTEGER DEFAULT 0,
    raw TEXT
);
CREATE INDEX IF NOT EXISTS ix_stra_act ON strava_activities(activity_id);
CREATE TABLE IF NOT EXISTS strava_efforts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    activity_id INTEGER,
    segment_id INTEGER,
    segment_name TEXT,
    distance_m REAL, elapsed_s REAL, moving_s REAL,
    pr_rank INTEGER, kom_rank INTEGER,
    avg_grade REAL, climb_category INTEGER, avg_hr REAL,
    date TEXT, city TEXT
);
CREATE INDEX IF NOT EXISTS ix_seff_seg ON strava_efforts(user_id, segment_id);
CREATE INDEX IF NOT EXISTS ix_seff_act ON strava_efforts(activity_id);
CREATE TABLE IF NOT EXISTS passkeys (
    credential_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    public_key TEXT NOT NULL,
    sign_count INTEGER DEFAULT 0,
    transports TEXT, name TEXT, rp_id TEXT,
    created TEXT, last_used TEXT, backed_up INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_passkeys_user ON passkeys(user_id);
CREATE TABLE IF NOT EXISTS push_subs (
    endpoint TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    p256dh TEXT NOT NULL, auth TEXT NOT NULL,
    user_agent TEXT, created TEXT, last_ok TEXT, fails INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS daily_health (
    user_id INTEGER NOT NULL DEFAULT 0,
    date TEXT NOT NULL,
    sleep_s REAL, sleep_score REAL, deep_s REAL, rem_s REAL, light_s REAL, awake_s REAL,
    hrv_night REAL, hrv_weekly REAL, hrv_status TEXT, hrv_low REAL, hrv_high REAL,
    rhr REAL, bb_high REAL, bb_low REAL, bb_last REAL, stress_avg REAL, steps REAL,
    readiness REAL, readiness_level TEXT,
    raw TEXT,
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS snapshots (
    user_id INTEGER NOT NULL DEFAULT 0,
    date TEXT NOT NULL,
    vo2max REAL, training_status TEXT, status_phrase TEXT,
    acute_load REAL, chronic_load REAL, acwr REAL,
    race_5k REAL, race_10k REAL, race_hm REAL, race_m REAL,
    raw TEXT,
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    pw_hash TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0,
    must_change INTEGER DEFAULT 0,
    created TEXT,
    pw_changed TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created TEXT,
    expires TEXT,
    last_seen TEXT,
    remember INTEGER DEFAULT 0,
    user_agent TEXT,
    ip TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    started TEXT, finished TEXT, status TEXT, message TEXT
);
CREATE INDEX IF NOT EXISTS ix_sync_user ON sync_log(user_id, id);
"""

# tablas con datos de cada usuario (best_efforts y streams cuelgan de activities)
USER_TABLES = ("activities", "daily_health", "snapshots", "sync_log", "user_settings", "shoes", "races",
               "training_plans", "plan_sessions", "routes", "route_sigs", "strava_activities", "strava_efforts",
               "passkeys", "push_subs")


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


# ---------- migraciones ----------
def _cols(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def _exists(con, table):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _rebuild_with_user(con, table, create_sql):
    """Recrea una tabla con clave (user_id, date) copiando los datos como 'sin asignar'."""
    old = _cols(con, table)
    con.execute(f"ALTER TABLE {table} RENAME TO {table}_v1")
    con.execute(create_sql)
    cols = ",".join(old)
    con.execute(f"INSERT INTO {table} (user_id,{cols}) SELECT 0,{cols} FROM {table}_v1")
    con.execute(f"DROP TABLE {table}_v1")


def _migrate(con):
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    if _exists(con, "activities") and "user_id" not in _cols(con, "activities"):
        log.info("Migrando a multiusuario (v2)")
        con.execute("ALTER TABLE activities ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
        for table in ("daily_health", "snapshots"):
            if _exists(con, table) and "user_id" not in _cols(con, table):
                block = SCHEMA.split(f"CREATE TABLE IF NOT EXISTS {table} (")[1].split(");")[0]
                _rebuild_with_user(con, table, f"CREATE TABLE {table} ({block})")
    # v3: GAP, versión de cálculos derivados y zapatilla de cada carrera
    if _exists(con, "activities"):
        have = _cols(con, "activities")
        for col, typ in (("gap_pace", "REAL"), ("derived_v", "INTEGER DEFAULT 0"), ("shoe_id", "INTEGER"),
                         ("route_id", "INTEGER")):  # v7: ruta repetida
            if col not in have:
                con.execute(f"ALTER TABLE activities ADD COLUMN {col} {typ}")
    # v6: cómo se hizo cada sesión del plan (ritmo cumplido)
    if _exists(con, "plan_sessions") and "execution" not in _cols(con, "plan_sessions"):
        con.execute("ALTER TABLE plan_sessions ADD COLUMN execution TEXT")
    if _exists(con, "sync_log") and "user_id" not in _cols(con, "sync_log"):
        con.execute("ALTER TABLE sync_log ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
    if _exists(con, "users") and "must_change" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN must_change INTEGER DEFAULT 0")
    # los ajustes de antes (cuenta de Garmin, objetivos, inicio, tema...) eran de la única persona
    # (sólo al venir de < 0.4.0; desde entonces la tabla settings guarda ajustes globales de la app)
    if version < 2 and _exists(con, "settings"):
        con.executescript(SCHEMA)
        con.execute("INSERT OR IGNORE INTO user_settings (user_id, key, value) SELECT 0, key, value FROM settings")
        con.execute("DELETE FROM settings")


def init():
    with tx() as con:
        _migrate(con)
        con.executescript(SCHEMA)
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        admin = con.execute("SELECT id FROM users WHERE is_admin=1 ORDER BY id LIMIT 1").fetchone()
    if admin:
        claim_unassigned(admin[0])


def claim_unassigned(user_id: int):
    """Asigna al usuario los datos sin dueño (los de antes de la 0.4.0 o los de demostración)."""
    with tx() as con:
        n = con.execute("SELECT COUNT(*) FROM activities WHERE user_id=0").fetchone()[0] \
            + con.execute("SELECT COUNT(*) FROM daily_health WHERE user_id=0").fetchone()[0] \
            + con.execute("SELECT COUNT(*) FROM user_settings WHERE user_id=0").fetchone()[0]
        if not n:
            return
        for t in ("activities", "daily_health", "snapshots", "sync_log", "shoes", "races", "training_plans", "plan_sessions",
                  "routes", "route_sigs", "strava_activities", "strava_efforts"):
            con.execute(f"UPDATE OR IGNORE {t} SET user_id=? WHERE user_id=0", (user_id,))
        con.execute("INSERT OR IGNORE INTO user_settings (user_id, key, value) "
                    "SELECT ?, key, value FROM user_settings WHERE user_id=0", (user_id,))
        for t in USER_TABLES:
            con.execute(f"DELETE FROM {t} WHERE user_id=0")
    log.info("Datos sin asignar pasados al usuario %s", user_id)


def delete_user_data(user_id: int):
    with tx() as con:
        ids = "SELECT id FROM activities WHERE user_id=?"
        con.execute(f"DELETE FROM streams WHERE activity_id IN ({ids})", (user_id,))
        con.execute(f"DELETE FROM best_efforts WHERE activity_id IN ({ids})", (user_id,))
        con.execute(f"DELETE FROM best_durations WHERE activity_id IN ({ids})", (user_id,))
        for t in USER_TABLES:
            con.execute(f"DELETE FROM {t} WHERE user_id=?", (user_id,))


# ---------- utilidades ----------
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


def upsert(table, data: dict, key):
    keys = (key,) if isinstance(key, str) else tuple(key)
    cols = list(data.keys())
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in keys)
    sql = (f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT({','.join(keys)}) DO " + (f"UPDATE SET {updates}" if updates else "NOTHING"))
    with tx() as con:
        con.execute(sql, [data[c] for c in cols])


# ---------- ajustes globales de la app (no de un usuario) ----------
def get_global(key, default=None):
    r = one("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(r["value"]) if r else default


def set_global(key, value):
    upsert("settings", {"key": key, "value": json.dumps(value)}, "key")


# ---------- ajustes de cada usuario ----------
def get_setting(user_id: int, key, default=None):
    r = one("SELECT value FROM user_settings WHERE user_id=? AND key=?", (user_id, key))
    if r is None:
        return DEFAULT_SETTINGS.get(key, default)
    return json.loads(r["value"])


def set_setting(user_id: int, key, value):
    upsert("user_settings", {"user_id": user_id, "key": key, "value": json.dumps(value)}, ("user_id", "key"))


def delete_settings(user_id: int, *keys):
    with tx() as con:
        for k in keys:
            con.execute("DELETE FROM user_settings WHERE user_id=? AND key=?", (user_id, k))


def all_settings(user_id: int):
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    for r in rows("SELECT key, value FROM user_settings WHERE user_id=?", (user_id,)):
        if r["key"] in DEFAULT_SETTINGS:
            out[r["key"]] = json.loads(r["value"])
    # widgets: añadir al final los que hayan aparecido en versiones nuevas
    for w in out["widgets"]:
        # anchura en columnas de 12 (antes sólo había «ancho» o «estrecho»)
        if w.get("cols") not in (3, 4, 6, 8, 12):
            w["cols"] = 8 if w.get("wide") else 4
    known = {w["id"] for w in out["widgets"]}
    for w in DEFAULT_SETTINGS["widgets"]:
        if w["id"] not in known:
            out["widgets"].append(dict(w))
    return out


# ---------- streams comprimidos ----------
def save_stream(activity_id, data: dict):
    blob = zlib.compress(json.dumps(data, separators=(",", ":")).encode())
    upsert("streams", {"activity_id": activity_id, "data": blob}, "activity_id")


def load_stream(activity_id):
    r = one("SELECT data FROM streams WHERE activity_id=?", (activity_id,))
    if not r:
        return None
    return json.loads(zlib.decompress(r["data"]).decode())

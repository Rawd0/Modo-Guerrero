"""Strava como fuente complementaria de Garmin.

- Cada usuario crea su propia «API Application» en strava.com/settings/api (las aplicaciones nuevas de
  Strava sólo admiten a su dueño) y pega aquí el Client ID y el Client Secret.
- Se conecta con OAuth: Strava vuelve a /api/strava/callback en esta misma app, así que en
  «Authorization Callback Domain» hay que poner el dominio con el que abres Modo Guerrero
  (por ejemplo 192.168.1.10 o umbrel.local).
- En cada sincronización: se enlazan las carreras de Strava con las de Garmin (misma hora y
  distancia) para añadir kudos, logros y segmentos; y, si quieres, se importan las carreras que
  sólo estén en Strava, con su registro completo.
- Permisos que se piden: `read,activity:read_all` (sólo lectura). Los tokens se guardan cifrados.
- Límites de Strava: 100 lecturas cada 15 min y 1000 al día. La primera carga se hace por partes.
"""
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from . import crypto, db, metrics, sync

log = logging.getLogger("guerrero.strava")

API = "https://www.strava.com/api/v3"
TIMEOUT = 30
PAUSE = 1.0
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}
DETAILS_PER_SYNC = 25      # actividades con segmentos por sincronización
IMPORTS_PER_SYNC = 25      # carreras sólo de Strava importadas (con registro) por sincronización

_states: dict[int, dict] = {}
_oauth_state: dict[int, tuple[str, float]] = {}
_run_lock = threading.Lock()


class StravaError(Exception):
    pass


class RateLimited(Exception):
    pass


def state(uid):
    return _states.setdefault(uid, {"running": False, "phase": "", "last_end": None, "last_error": None, "last_msg": None})


# ---------- ajustes (por usuario) ----------
def _cfg(uid) -> dict:
    return db.get_setting(uid, "strava") or {}


def _save_cfg(uid, cfg):
    db.set_setting(uid, "strava", cfg)


def public(uid) -> dict:
    c = _cfg(uid)
    st = state(uid)
    counts = db.one("SELECT COUNT(*) total, SUM(CASE WHEN activity_id IS NOT NULL THEN 1 ELSE 0 END) linked "
                    "FROM strava_activities WHERE user_id=?", (uid,))
    imported = db.one("SELECT COUNT(*) n FROM activities WHERE user_id=? AND source='strava'", (uid,))["n"]
    efforts = db.one("SELECT COUNT(*) n, COUNT(DISTINCT segment_id) segs FROM strava_efforts WHERE user_id=?", (uid,))
    return {"client_id": c.get("client_id", ""), "has_secret": bool(c.get("client_secret")),
            "connected": bool(c.get("refresh_token")), "athlete": c.get("athlete"),
            "import_missing": c.get("import_missing", True), "segments": c.get("segments", True),
            "state": st, "counts": {"strava": counts["total"] or 0, "linked": counts["linked"] or 0,
                                    "imported": imported, "efforts": efforts["n"], "segments": efforts["segs"]}}


def save_settings(uid, payload: dict):
    c = _cfg(uid)
    if "client_id" in payload:
        cid = str(payload.get("client_id") or "").strip()
        if cid and not cid.isdigit():
            raise StravaError("El Client ID de Strava es un número")
        if cid != c.get("client_id"):
            c.update(refresh_token=None, access_token=None, expires_at=None, athlete=None)
        c["client_id"] = cid
    if payload.get("client_secret"):
        c["client_secret"] = crypto.encrypt(str(payload["client_secret"]).strip())
    for k in ("import_missing", "segments"):
        if k in payload:
            c[k] = bool(payload[k])
    _save_cfg(uid, c)
    return public(uid)


# ---------- OAuth ----------
def authorize_url(uid, redirect_uri: str) -> str:
    c = _cfg(uid)
    if not c.get("client_id") or not c.get("client_secret"):
        raise StravaError("Guarda primero el Client ID y el Client Secret de tu aplicación de Strava")
    tok = secrets.token_urlsafe(24)
    _oauth_state[uid] = (tok, time.time() + 900)
    from urllib.parse import urlencode
    return "https://www.strava.com/oauth/authorize?" + urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
        "approval_prompt": "auto", "scope": "read,activity:read_all", "state": tok})


def callback(uid, code: str, st: str, scope: str):
    saved = _oauth_state.pop(uid, None)
    if not saved or saved[0] != st or saved[1] < time.time():
        raise StravaError("La autorización de Strava ha caducado o no es válida; vuelve a intentarlo")
    if "activity:read" not in (scope or ""):
        raise StravaError("Hace falta permitir el acceso a tus actividades (marca la casilla al autorizar)")
    c = _cfg(uid)
    r = requests.post("https://www.strava.com/oauth/token", timeout=TIMEOUT, data={
        "client_id": c["client_id"], "client_secret": crypto.decrypt(c["client_secret"]) or "",
        "code": code, "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise StravaError(f"Strava rechazó la autorización ({r.status_code})")
    j = r.json()
    a = j.get("athlete") or {}
    c.update(refresh_token=crypto.encrypt(j["refresh_token"]), access_token=crypto.encrypt(j["access_token"]),
             expires_at=j.get("expires_at"), athlete={"id": a.get("id"),
                                                      "name": " ".join(x for x in (a.get("firstname"), a.get("lastname")) if x)})
    _save_cfg(uid, c)


def disconnect(uid):
    c = _cfg(uid)
    try:
        tok = _token(uid)
        requests.post("https://www.strava.com/oauth/deauthorize", data={"access_token": tok}, timeout=15)
    except (StravaError, requests.RequestException):
        pass
    c.update(refresh_token=None, access_token=None, expires_at=None, athlete=None)
    _save_cfg(uid, c)


def is_connected(uid) -> bool:
    return bool(_cfg(uid).get("refresh_token"))


def _token(uid) -> str:
    c = _cfg(uid)
    if not c.get("refresh_token"):
        raise StravaError("Strava no está conectado")
    if c.get("access_token") and (c.get("expires_at") or 0) > time.time() + 120:
        return crypto.decrypt(c["access_token"])
    r = requests.post("https://www.strava.com/oauth/token", timeout=TIMEOUT, data={
        "client_id": c["client_id"], "client_secret": crypto.decrypt(c.get("client_secret") or "") or "",
        "refresh_token": crypto.decrypt(c["refresh_token"]) or "", "grant_type": "refresh_token"})
    if r.status_code in (400, 401):
        c.update(refresh_token=None, access_token=None)
        _save_cfg(uid, c)
        raise StravaError("Strava ha retirado el permiso: vuelve a conectar Strava en Ajustes")
    if r.status_code != 200:
        raise StravaError(f"Strava respondió {r.status_code} al renovar el acceso")
    j = r.json()
    c.update(access_token=crypto.encrypt(j["access_token"]), refresh_token=crypto.encrypt(j["refresh_token"]),
             expires_at=j.get("expires_at"))
    _save_cfg(uid, c)
    return j["access_token"]


def _get(uid, path, **params):
    r = requests.get(API + path, params=params, timeout=TIMEOUT, headers={"Authorization": f"Bearer {_token(uid)}"})
    time.sleep(PAUSE)
    if r.status_code == 429:
        raise RateLimited()
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise StravaError(f"Strava respondió {r.status_code} en {path.split('?')[0]}")
    usage = r.headers.get("X-ReadRateLimit-Usage") or r.headers.get("X-RateLimit-Usage")
    limit = r.headers.get("X-ReadRateLimit-Limit") or r.headers.get("X-RateLimit-Limit")
    if usage and limit:
        try:
            u15, ud = (int(x) for x in usage.split(",")[:2])
            l15, ld = (int(x) for x in limit.split(",")[:2])
            if u15 >= l15 - 3 or ud >= ld - 10:
                raise RateLimited()
        except ValueError:
            pass
    return r.json()


# ---------- mapeo ----------
def _local(s):
    return s.replace("T", " ").replace("Z", "")[:19] if s else None


def _match(uid, a):
    """Busca la misma carrera ya guardada (de Garmin o de un .FIT): inicio ±2 min y distancia ±10 %."""
    st = _local(a.get("start_date"))
    if not st:
        return None
    t = datetime.strptime(st, "%Y-%m-%d %H:%M:%S")
    lo, hi = (t - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"), (t + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
    for r in db.rows("SELECT id, distance_m FROM activities WHERE user_id=? AND start_utc BETWEEN ? AND ? AND source<>'strava'",
                     (uid, lo, hi)):
        d = a.get("distance") or 0
        if not d or not r["distance_m"] or abs(r["distance_m"] - d) <= 0.1 * max(d, r["distance_m"]):
            return r["id"]
    return None


def activity_row(a: dict) -> dict:
    start_local = _local(a.get("start_date_local"))
    return {
        "id": -int(a["id"]),  # negativo: no choca con los identificadores de Garmin
        "name": a.get("name") or "Carrera (Strava)",
        "sport": {"TrailRun": "trail_running", "VirtualRun": "treadmill_running"}.get(a.get("sport_type") or a.get("type"), "running"),
        "is_run": 1,
        "start_local": start_local,
        "start_utc": _local(a.get("start_date")),
        "date": start_local[:10] if start_local else None,
        "distance_m": a.get("distance"),
        "duration_s": a.get("elapsed_time"),
        "moving_s": a.get("moving_time"),
        "avg_speed": a.get("average_speed"),
        "max_speed": a.get("max_speed"),
        "avg_hr": a.get("average_heartrate"),
        "max_hr": a.get("max_heartrate"),
        "calories": a.get("calories"),
        "elev_gain": a.get("total_elevation_gain"),
        "cadence": round(a["average_cadence"] * 2) if a.get("average_cadence") else None,
        "start_lat": (a.get("start_latlng") or [None, None])[0] if a.get("start_latlng") else None,
        "start_lon": (a.get("start_latlng") or [None, None])[1] if a.get("start_latlng") else None,
        "source": "strava",
        "fit_status": "ok",
        "raw": json.dumps(a),
    }


def stream_from_strava(s: dict) -> dict:
    """Convierte los streams de Strava (key_by_type) al formato interno."""
    def g(k):
        return (s.get(k) or {}).get("data") or []
    t = g("time")
    n = len(t)
    latlng = g("latlng")
    cad = g("cadence")

    def fit(arr):
        return list(arr) + [None] * (n - len(arr)) if len(arr) < n else list(arr[:n])
    return {
        "t": t, "d": fit(g("distance")), "hr": fit(g("heartrate")), "alt": fit(g("altitude")),
        "cad": [c * 2 if c is not None and c < 120 else c for c in fit(cad)],
        "spd": fit(g("velocity_smooth")),
        "lat": [p[0] if p else None for p in fit(latlng)], "lon": [p[1] if p else None for p in fit(latlng)],
    }


# ---------- sincronización ----------
def _sync_list(uid, st):
    """Trae la lista de actividades nuevas (desde la última vista) y las enlaza o guarda."""
    last = db.one("SELECT MAX(json_extract(raw,'$.start_date')) d FROM strava_activities WHERE user_id=?", (uid,))["d"]
    after = int(datetime.strptime(last[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()) - 3600 \
        if last else 0
    page, n = 1, 0
    while True:
        st["phase"] = f"Strava: lista de actividades (página {page})"
        items = _get(uid, "/athlete/activities", after=after, per_page=100, page=page) or []
        for a in items:
            if (a.get("sport_type") or a.get("type")) not in RUN_TYPES:
                continue
            link = _match(uid, a)
            prev = db.one("SELECT activity_id, detail_fetched FROM strava_activities WHERE strava_id=?", (a["id"],))
            if prev and prev["activity_id"] and not link:
                link = prev["activity_id"]
            db.upsert("strava_activities", {
                "strava_id": a["id"], "user_id": uid, "activity_id": link, "name": a.get("name"),
                "kudos": a.get("kudos_count"), "achievements": a.get("achievement_count"), "prs": a.get("pr_count"),
                "comments": a.get("comment_count"), "detail_fetched": prev["detail_fetched"] if prev else 0,
                "raw": json.dumps(a)}, "strava_id")
            n += 1
        if len(items) < 100:
            return n
        page += 1


def _import_missing(uid, st):
    """Carreras que sólo están en Strava: se guardan como actividades con su registro completo."""
    pend = db.rows("SELECT strava_id, raw FROM strava_activities WHERE user_id=? AND activity_id IS NULL "
                   "ORDER BY json_extract(raw,'$.start_date') DESC LIMIT ?", (uid, IMPORTS_PER_SYNC))
    done = 0
    for i, p in enumerate(pend):
        st["phase"] = f"Strava: importando carreras {i + 1}/{len(pend)}"
        a = json.loads(p["raw"])
        # quizá llegó después desde Garmin
        link = _match(uid, a)
        if link:
            db.execute("UPDATE strava_activities SET activity_id=? WHERE strava_id=?", (link, p["strava_id"]))
            continue
        row = activity_row(a)
        exists = db.one("SELECT user_id FROM activities WHERE id=?", (row["id"],))
        if exists and exists["user_id"] != uid:
            continue
        db.upsert("activities", dict(row, user_id=uid), "id")
        sync.assign_default_shoe(uid, row["id"])
        s = _get(uid, f"/activities/{p['strava_id']}/streams",
                 keys="time,distance,latlng,altitude,heartrate,cadence,velocity_smooth", key_by_type="true")
        if s and (s.get("time") or {}).get("data"):
            stream = stream_from_strava(s)
            db.save_stream(row["id"], stream)
            metrics.store_derived(row["id"], stream)
        db.execute("UPDATE strava_activities SET activity_id=? WHERE strava_id=?", (row["id"], p["strava_id"]))
        done += 1
    return done


def _fetch_segments(uid, st):
    pend = db.rows("SELECT strava_id, activity_id FROM strava_activities WHERE user_id=? AND activity_id IS NOT NULL "
                   "AND detail_fetched=0 ORDER BY json_extract(raw,'$.start_date') DESC LIMIT ?", (uid, DETAILS_PER_SYNC))
    n = 0
    for i, p in enumerate(pend):
        st["phase"] = f"Strava: segmentos {i + 1}/{len(pend)}"
        d = _get(uid, f"/activities/{p['strava_id']}", include_all_efforts="false")
        if d is None:
            db.execute("UPDATE strava_activities SET detail_fetched=1 WHERE strava_id=?", (p["strava_id"],))
            continue
        with db.tx() as con:
            con.execute("DELETE FROM strava_efforts WHERE activity_id=? AND user_id=?", (p["activity_id"], uid))
            for e in d.get("segment_efforts") or []:
                seg = e.get("segment") or {}
                con.execute("INSERT OR REPLACE INTO strava_efforts (id, user_id, activity_id, segment_id, segment_name, distance_m, "
                            "elapsed_s, moving_s, pr_rank, kom_rank, avg_grade, climb_category, avg_hr, date, city) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (e["id"], uid, p["activity_id"], seg.get("id"), seg.get("name") or e.get("name"),
                             e.get("distance") or seg.get("distance"), e.get("elapsed_time"), e.get("moving_time"),
                             e.get("pr_rank"), e.get("kom_rank"), seg.get("average_grade"), seg.get("climb_category"),
                             e.get("average_heartrate"), _local(e.get("start_date_local") or "")[:10] or None, seg.get("city")))
            con.execute("UPDATE strava_activities SET detail_fetched=1, kudos=?, achievements=?, prs=?, comments=? "
                        "WHERE strava_id=?", (d.get("kudos_count"), d.get("achievement_count"), d.get("pr_count"),
                                              d.get("comment_count"), p["strava_id"]))
        n += 1
    return n


def run(uid) -> str:
    st = state(uid)
    if not is_connected(uid):
        return ""
    with _run_lock:
        st.update(running=True, last_error=None)
        msg = ""
        try:
            c = _cfg(uid)
            n = _sync_list(uid, st)
            imp = _import_missing(uid, st) if c.get("import_missing", True) else 0
            seg = _fetch_segments(uid, st) if c.get("segments", True) else 0
            msg = f"Strava: {n} actividades revisadas, {imp} importadas, {seg} con segmentos"
        except RateLimited:
            msg = "Strava limita las peticiones (100 cada 15 min): se sigue en la próxima sincronización"
        except (StravaError, requests.RequestException) as e:
            st["last_error"] = str(e)
            msg = f"Strava: {e}"
            log.warning("Strava (%s): %s", uid, e)
        finally:
            st.update(running=False, phase="", last_end=datetime.now().isoformat(timespec="seconds"), last_msg=msg)
        return msg


def run_async(uid):
    if state(uid)["running"]:
        return
    threading.Thread(target=run, args=(uid,), daemon=True, name=f"strava-{uid}").start()


# ---------- consultas ----------
def for_activity(uid: int, activity_id: int):
    s = db.one("SELECT strava_id, kudos, achievements, prs, comments, detail_fetched FROM strava_activities "
               "WHERE user_id=? AND activity_id=?", (uid, activity_id))
    if not s:
        return None
    efforts = db.rows("SELECT e.*, (SELECT COUNT(*) FROM strava_efforts x WHERE x.user_id=e.user_id AND x.segment_id=e.segment_id) n, "
                      "(SELECT MIN(elapsed_s) FROM strava_efforts x WHERE x.user_id=e.user_id AND x.segment_id=e.segment_id) best "
                      "FROM strava_efforts e WHERE e.user_id=? AND e.activity_id=? ORDER BY e.id", (uid, activity_id))
    return {**s, "url": f"https://www.strava.com/activities/{s['strava_id']}", "efforts": efforts}


def segment(uid: int, segment_id: int):
    rows = db.rows("SELECT e.*, a.name act_name FROM strava_efforts e LEFT JOIN activities a ON a.id=e.activity_id "
                   "WHERE e.user_id=? AND e.segment_id=? ORDER BY e.date", (uid, segment_id))
    if not rows:
        raise StravaError("Segmento no encontrado")
    best = min(r["elapsed_s"] for r in rows if r["elapsed_s"])
    return {"id": segment_id, "name": rows[-1]["segment_name"], "distance_m": rows[-1]["distance_m"],
            "avg_grade": rows[-1]["avg_grade"], "city": rows[-1]["city"], "best_s": best, "efforts": rows,
            "url": f"https://www.strava.com/segments/{segment_id}"}


def top_segments(uid: int, limit=30):
    return db.rows("SELECT segment_id, MAX(segment_name) name, MAX(distance_m) distance_m, MAX(avg_grade) avg_grade, "
                   "COUNT(*) n, MIN(elapsed_s) best_s, MAX(date) last FROM strava_efforts WHERE user_id=? "
                   "GROUP BY segment_id HAVING n>=2 ORDER BY n DESC, last DESC LIMIT ?", (uid, limit))

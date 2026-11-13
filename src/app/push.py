"""Notificaciones push (Web Push) al móvil y al ordenador.

En el iPhone funcionan con la app añadida a la pantalla de inicio (iOS 16.4 o posterior) y abierta
por HTTPS. El servidor firma cada envío con sus claves VAPID (se generan una vez y la privada se
guarda cifrada); el contenido va cifrado de extremo a extremo hasta tu dispositivo.

Avisos:
- «Hoy toca»: la sesión del plan, a la hora que elijas.
- Resumen semanal: los lunes, a la misma hora.
- Nuevos récords personales tras sincronizar.
- Zapatillas que se acercan al final (85 %) o lo superan.
- Problemas: la sesión de Garmin o Strava ha caducado, o (administradores) falla una copia.
"""
import base64
import json
import logging
import threading
import time
from datetime import date, datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from . import crypto, db

log = logging.getLogger("guerrero.push")

DEFAULT_PREFS = {"daily": True, "weekly": True, "records": True, "shoes": True, "problems": True,
                 "time": "07:30", "tz": "Europe/Madrid"}


class PushError(Exception):
    pass


# ---------- claves VAPID ----------
_vapid_cache = {}


def _vapid():
    if _vapid_cache:
        return _vapid_cache["pem"], _vapid_cache["public"]
    v = db.get_global("vapid")
    pem = crypto.decrypt(v["private"]) if v else None
    if not pem:
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        v = {"private": crypto.encrypt(pem), "public": base64.urlsafe_b64encode(pub).rstrip(b"=").decode()}
        db.set_global("vapid", v)
    _vapid_cache.update(pem=pem, public=v["public"])
    return pem, v["public"]


def public_key() -> str:
    return _vapid()[1]


def _subject() -> str:
    # VAPID sólo admite «https://dominio» (sin puerto ni ruta) o un mailto:
    from urllib.parse import urlparse
    origins = db.get_global("https_origins", []) or []
    host = urlparse(origins[0]).hostname if origins else None
    return f"https://{host}" if host and "." in host else "https://github.com"


# ---------- suscripciones y preferencias ----------
def prefs(uid: int) -> dict:
    p = dict(DEFAULT_PREFS)
    p.update(db.get_setting(uid, "notify") or {})
    return p


def save_prefs(uid: int, payload: dict) -> dict:
    p = prefs(uid)
    for k in ("daily", "weekly", "records", "shoes", "problems"):
        if k in payload:
            p[k] = bool(payload[k])
    if "time" in payload:
        t = str(payload["time"])
        try:
            datetime.strptime(t, "%H:%M")
        except ValueError:
            raise PushError("Hora no válida")
        p["time"] = t
    if payload.get("tz"):
        _zone(payload["tz"])
        p["tz"] = payload["tz"]
    db.set_setting(uid, "notify", p)
    return p


def _zone(name):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise PushError("Zona horaria no válida")


def subscribe(uid: int, sub: dict, user_agent: str = ""):
    endpoint = (sub or {}).get("endpoint", "")
    keys = (sub or {}).get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth") or len(endpoint) > 1000:
        raise PushError("Suscripción no válida")
    db.execute("INSERT INTO push_subs (endpoint, user_id, p256dh, auth, user_agent, created, fails) VALUES (?,?,?,?,?,?,0) "
               "ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id, p256dh=excluded.p256dh, auth=excluded.auth, "
               "user_agent=excluded.user_agent, fails=0",
               (endpoint, uid, keys["p256dh"], keys["auth"], user_agent[:300], datetime.now().isoformat(timespec="seconds")))


def unsubscribe(uid: int, endpoint: str):
    db.execute("DELETE FROM push_subs WHERE endpoint=? AND user_id=?", (endpoint, uid))


def devices(uid: int):
    return db.rows("SELECT endpoint, user_agent, created, last_ok FROM push_subs WHERE user_id=? ORDER BY created", (uid,))


# ---------- envío ----------
def send(uid: int, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    """Envía a todos los dispositivos del usuario. Devuelve a cuántos llegó."""
    from py_vapid import Vapid02  # RFC 8292 («vapid t=…, k=…»), el que pide Apple
    from pywebpush import WebPushException, webpush
    subs = db.rows("SELECT * FROM push_subs WHERE user_id=?", (uid,))
    if not subs:
        return 0
    pem, _ = _vapid()
    vapid = Vapid02.from_pem(pem.encode())
    data = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    ok = 0
    for s in subs:
        try:
            webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}, data,
                    vapid_private_key=vapid, vapid_claims={"sub": _subject(), "exp": int(time.time()) + 12 * 3600}, ttl=12 * 3600, timeout=20)
            db.execute("UPDATE push_subs SET last_ok=?, fails=0 WHERE endpoint=?",
                       (datetime.now().isoformat(timespec="seconds"), s["endpoint"]))
            ok += 1
        except WebPushException as e:
            code = e.response.status_code if e.response is not None else None
            if code in (404, 410):  # el dispositivo ya no existe o retiró el permiso
                db.execute("DELETE FROM push_subs WHERE endpoint=?", (s["endpoint"],))
            else:
                db.execute("UPDATE push_subs SET fails=fails+1 WHERE endpoint=?", (s["endpoint"],))
                log.warning("Push a %s falló: %s", s["endpoint"][:40], e)
        except Exception as e:  # noqa: BLE001 (red, etc.)
            db.execute("UPDATE push_subs SET fails=fails+1 WHERE endpoint=?", (s["endpoint"],))
            log.warning("Push falló: %s", e)
    return ok


def send_async(uid, *a, **k):
    threading.Thread(target=lambda: _safe(send, uid, *a, **k), daemon=True, name="push").start()


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception:  # noqa: BLE001
        log.exception("Notificación")


def _has_subs(uid):
    return bool(db.one("SELECT 1 x FROM push_subs WHERE user_id=? LIMIT 1", (uid,)))


def _state(uid) -> dict:
    return db.get_setting(uid, "notify_state") or {}


def _save_state(uid, st):
    db.set_setting(uid, "notify_state", st)


# ---------- avisos tras sincronizar ----------
def after_sync(uid: int, status: str, msg: str):
    if not _has_subs(uid):
        return
    p, st = prefs(uid), _state(uid)
    from . import shoes, stats
    # problemas de conexión: avisar una vez hasta que vuelva a funcionar
    if p["problems"]:
        if status == "auth" and not st.get("auth_warned"):
            send(uid, "Garmin necesita que vuelvas a entrar", "La sesión con Garmin ha caducado. Entra en Ajustes para reconectar.",
                 "/#/ajustes", "garmin-auth")
            st["auth_warned"] = True
        elif status == "ok":
            st["auth_warned"] = False
        if "Strava ha retirado el permiso" in (msg or "") and not st.get("strava_warned"):
            send(uid, "Strava se ha desconectado", "Vuelve a conectar Strava en Ajustes.", "/#/ajustes", "strava-auth")
            st["strava_warned"] = True
    # récords nuevos
    if p["records"]:
        seen = set(st.get("records", []))
        cur = []
        for r in stats.records(uid):
            best = (r.get("top") or [None])[0]
            if best:
                cur.append(f"{r['distance']}:{best['id']}")
        if "records" in st:  # la primera vez sólo se apunta lo que hay
            new = [c for c in cur if c not in seen]
            for r in stats.records(uid):
                best = (r.get("top") or [None])[0]
                if best and f"{r['distance']}:{best['id']}" in new:
                    m, s_ = divmod(round(best["time_s"]), 60)
                    h, m = divmod(m, 60)
                    t = f"{h}:{m:02d}:{s_:02d}" if h else f"{m}:{s_:02d}"
                    send(uid, f"🏅 ¡Nuevo récord en {r['label']}!", f"{t} en «{best['name']}».", f"/#/carrera/{best['id']}", f"pr-{r['distance']}")
        st["records"] = cur
    # zapatillas
    if p["shoes"]:
        warned = st.get("shoes", {})
        for sh in shoes.list_shoes(uid):
            prev = warned.get(str(sh["id"]))
            if sh["status"] in ("soon", "replace") and prev != sh["status"]:
                if sh["status"] == "replace":
                    send(uid, f"👟 {sh['name']}: toca cambiarlas", f"Llevan {round(sh['km'])} km (límite {round(sh['limit_km'])} km).", "/#/zapatillas", f"shoe-{sh['id']}")
                else:
                    send(uid, f"👟 {sh['name']}: cerca del final", f"Llevan {round(sh['km'])} km de {round(sh['limit_km'])} km.", "/#/zapatillas", f"shoe-{sh['id']}")
            warned[str(sh["id"])] = sh["status"]
        st["shoes"] = warned
    _save_state(uid, st)


def backup_failed(error: str):
    for u in db.rows("SELECT id FROM users WHERE is_admin=1"):
        if _has_subs(u["id"]) and prefs(u["id"])["problems"]:
            send_async(u["id"], "La copia de seguridad ha fallado", str(error)[:180], "/#/ajustes", "backup")


# ---------- avisos programados ----------
def _daily(uid):
    from . import plans
    t = plans.today_session(uid)
    s = t and t["session"]
    if not s or s["date"] != date.today().isoformat() or s["status"] != "planned":
        return False
    title = f"Hoy toca: {s['title'].lower()}" + (f" · {s['distance_km']:g} km".replace(".", ",") if s["type"] != "race" else "")
    if s["type"] == "race":
        title = f"🏁 ¡Hoy es el día! {t['race_name']}"
    send(uid, title, s["description"], f"/#/plan/{t['race_id']}", "daily")
    return True


def _weekly(uid, today: date):
    mon = today - timedelta(days=today.weekday() + 7)
    sun = mon + timedelta(days=6)
    r = db.one("SELECT COUNT(*) n, COALESCE(SUM(distance_m),0)/1000.0 km, COALESCE(SUM(moving_s),0) s FROM activities "
               "WHERE user_id=? AND is_run=1 AND date BETWEEN ? AND ?", (uid, mon.isoformat(), sun.isoformat()))
    prev = db.one("SELECT COALESCE(SUM(distance_m),0)/1000.0 km FROM activities WHERE user_id=? AND is_run=1 AND date BETWEEN ? AND ?",
                  (uid, (mon - timedelta(days=7)).isoformat(), (sun - timedelta(days=7)).isoformat()))["km"]
    from . import metrics
    fit = metrics.fitness_series(uid, days=3)
    form = fit[-1] if fit else None
    h, m = divmod(round(r["s"] / 60), 60)
    body = f"{r['n']} carreras · {r['km']:.1f} km · {h} h {m:02d} min".replace(".", ",")
    if prev:
        diff = r["km"] - prev
        body += f" ({'+' if diff >= 0 else '−'}{abs(diff):.1f} km frente a la anterior)".replace(".", ",")
    if form and form.get("tsb") is not None:
        body += f". Forma (TSB): {round(form['tsb']):+d}"
    send(uid, "Tu semana", body, "/#/", "weekly")


def scheduler_loop():
    time.sleep(40)
    while True:
        try:
            uids = [r["user_id"] for r in db.rows("SELECT DISTINCT user_id FROM push_subs")]
            for uid in uids:
                p = prefs(uid)
                try:
                    now = datetime.now(_zone(p["tz"]))
                except PushError:
                    now = datetime.now()
                hh, mm = (int(x) for x in p["time"].split(":"))
                if (now.hour, now.minute) < (hh, mm) or now.hour > hh + 3:
                    continue  # sólo en la ventana de 3 h desde la hora elegida (sin avisos a deshora tras un corte)
                st = _state(uid)
                today = now.date().isoformat()
                changed = False
                if p["daily"] and st.get("daily_sent") != today:
                    _safe(_daily, uid)
                    st["daily_sent"] = today
                    changed = True
                if p["weekly"] and now.weekday() == 0 and st.get("weekly_sent") != today:
                    _safe(_weekly, uid, now.date())
                    st["weekly_sent"] = today
                    changed = True
                if changed:
                    cur = _state(uid)
                    cur.update({k: st[k] for k in ("daily_sent", "weekly_sent") if k in st})
                    _save_state(uid, cur)
        except Exception:  # noqa: BLE001
            log.exception("Programador de notificaciones")
        time.sleep(60)


def start_scheduler():
    threading.Thread(target=scheduler_loop, daemon=True, name="push").start()

"""Usuarios y sesiones de la app.

- Contraseñas con scrypt (biblioteca estándar), sal aleatoria por usuario.
- Sesión: token aleatorio en una cookie HttpOnly; en la base de datos sólo se guarda su hash.
- "Recordar este dispositivo": la sesión dura 90 días y se renueva con el uso.
  Sin recordar: 12 horas y la cookie desaparece al cerrar el navegador.
- Bloqueo tras intentos fallidos, por usuario y por IP.
"""
import base64
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta

from . import db

COOKIE = "mg_session"
REMEMBER_DAYS = 90
SHORT_HOURS = 12
MIN_PASSWORD = 10
MAX_FAILS = 5
LOCK_SECONDS = 15 * 60

_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024, "dklen": 32}
# hash ficticio para que un usuario inexistente tarde lo mismo que uno real
_DUMMY_HASH = None

_fails: dict[str, list[float]] = {}
_fails_lock = threading.Lock()


class AuthFailed(Exception):
    pass


# ---------- contraseñas ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$%d$%d$%d$%s$%s" % (_SCRYPT["n"], _SCRYPT["r"], _SCRYPT["p"],
                                       base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              maxmem=_SCRYPT["maxmem"], dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:  # noqa: BLE001
        return False


def check_password_strength(password: str, username: str = ""):
    if len(password) < MIN_PASSWORD:
        raise AuthFailed(f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")
    if username and password.lower() == username.lower():
        raise AuthFailed("La contraseña no puede ser igual al usuario.")


# ---------- usuarios ----------
def user_count() -> int:
    return db.one("SELECT COUNT(*) n FROM users")["n"]


def create_user(username: str, password: str, is_admin=False, must_change=False) -> int:
    username = (username or "").strip()
    if not (3 <= len(username) <= 40) or not all(c.isalnum() or c in "._-" for c in username):
        raise AuthFailed("El usuario debe tener entre 3 y 40 caracteres: letras, números, punto, guion o guion bajo.")
    check_password_strength(password, username)
    if db.one("SELECT id FROM users WHERE username=?", (username,)):
        raise AuthFailed("Ese usuario ya existe.")
    now = _now()
    with db.tx() as con:
        cur = con.execute("INSERT INTO users (username, pw_hash, is_admin, must_change, created, pw_changed) "
                          "VALUES (?,?,?,?,?,?)",
                          (username, hash_password(password), 1 if is_admin else 0, 1 if must_change else 0, now, now))
        return cur.lastrowid


def setup_first_user(username: str, password: str) -> int:
    """Crea el administrador. Sólo funciona si todavía no hay ningún usuario."""
    with db.tx() as con:
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise AuthFailed("La app ya tiene un administrador.")
    uid = create_user(username, password, is_admin=True)
    db.claim_unassigned(uid)  # los datos de antes de haber usuarios son del primer administrador
    return uid


def change_password(user_id: int, current: str, new: str, keep_token_hash: str | None):
    u = db.one("SELECT * FROM users WHERE id=?", (user_id,))
    if not u or not verify_password(current, u["pw_hash"]):
        raise AuthFailed("La contraseña actual no es correcta.")
    check_password_strength(new, u["username"])
    with db.tx() as con:
        con.execute("UPDATE users SET pw_hash=?, pw_changed=?, must_change=0 WHERE id=?",
                    (hash_password(new), _now(), user_id))
        # cerrar el resto de sesiones: si alguien conocía la contraseña anterior, pierde el acceso
        con.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user_id, keep_token_hash or ""))


# ---------- administración de usuarios ----------
def list_users():
    return db.rows(
        "SELECT u.id, u.username, u.is_admin, u.must_change, u.created, "
        "(SELECT MAX(last_seen) FROM sessions s WHERE s.user_id=u.id) last_seen, "
        "(SELECT COUNT(*) FROM activities a WHERE a.user_id=u.id AND a.is_run=1) runs, "
        "EXISTS(SELECT 1 FROM user_settings x WHERE x.user_id=u.id AND x.key='garmin_token') garmin "
        "FROM users u ORDER BY u.id")


def admin_reset_password(user_id: int, new_password: str):
    u = db.one("SELECT username FROM users WHERE id=?", (user_id,))
    if not u:
        raise AuthFailed("El usuario no existe.")
    check_password_strength(new_password, u["username"])
    with db.tx() as con:
        con.execute("UPDATE users SET pw_hash=?, pw_changed=?, must_change=1 WHERE id=?",
                    (hash_password(new_password), _now(), user_id))
        con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    _clear(f"u:{u['username'].lower()}")


def set_admin(user_id: int, is_admin: bool, acting_user_id: int):
    if not is_admin and _admins_except(user_id) == 0:
        raise AuthFailed("Tiene que quedar al menos un administrador.")
    if user_id == acting_user_id and not is_admin:
        raise AuthFailed("No puedes quitarte a ti mismo el permiso de administrador.")
    db.execute("UPDATE users SET is_admin=? WHERE id=?", (1 if is_admin else 0, user_id))


def delete_user(user_id: int, acting_user_id: int):
    if user_id == acting_user_id:
        raise AuthFailed("No puedes eliminar tu propia cuenta.")
    u = db.one("SELECT is_admin FROM users WHERE id=?", (user_id,))
    if not u:
        raise AuthFailed("El usuario no existe.")
    if u["is_admin"] and _admins_except(user_id) == 0:
        raise AuthFailed("Tiene que quedar al menos un administrador.")
    db.delete_user_data(user_id)
    db.execute("DELETE FROM users WHERE id=?", (user_id,))


def _admins_except(user_id: int) -> int:
    return db.one("SELECT COUNT(*) n FROM users WHERE is_admin=1 AND id<>?", (user_id,))["n"]


# ---------- intentos fallidos ----------
def _locked(key: str) -> int:
    now = time.time()
    with _fails_lock:
        times = [t for t in _fails.get(key, []) if now - t < LOCK_SECONDS]
        _fails[key] = times
        if len(times) >= MAX_FAILS:
            return int(LOCK_SECONDS - (now - times[0]))
    return 0


def _fail(*keys):
    with _fails_lock:
        for k in keys:
            _fails.setdefault(k, []).append(time.time())


def _clear(*keys):
    with _fails_lock:
        for k in keys:
            _fails.pop(k, None)


def login(username: str, password: str, ip: str) -> dict:
    ukey, ikey = f"u:{(username or '').lower()}", f"ip:{ip}"
    wait = max(_locked(ukey), _locked(ikey))
    if wait:
        raise AuthFailed(f"Demasiados intentos fallidos. Prueba de nuevo en {max(1, wait // 60)} min.")
    u = db.one("SELECT * FROM users WHERE username=?", ((username or "").strip(),))
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_hex(8))
    ok = verify_password(password or "", u["pw_hash"] if u else _DUMMY_HASH)
    if not u or not ok:
        _fail(ukey, ikey)
        time.sleep(0.5)
        raise AuthFailed("Usuario o contraseña incorrectos.")
    _clear(ukey, ikey)
    return u


# ---------- sesiones ----------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(user_id: int, remember: bool, user_agent: str, ip: str) -> tuple[str, int | None]:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires = now + (timedelta(days=REMEMBER_DAYS) if remember else timedelta(hours=SHORT_HOURS))
    with db.tx() as con:
        con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)",
                    (_hash_token(token), user_id, _iso(now), _iso(expires), _iso(now), 1 if remember else 0,
                     (user_agent or "")[:200], ip))
        con.execute("DELETE FROM sessions WHERE expires < ?", (_iso(now),))
    max_age = REMEMBER_DAYS * 86400 if remember else None
    return token, max_age


def session_user(token: str | None) -> dict | None:
    """Devuelve el usuario de la sesión (o None). Renueva las sesiones recordadas."""
    if not token:
        return None
    th = _hash_token(token)
    s = db.one("SELECT s.*, u.username, u.is_admin, u.must_change FROM sessions s JOIN users u ON u.id=s.user_id "
               "WHERE s.token_hash=?", (th,))
    now = datetime.now()
    if not s or s["expires"] < _iso(now):
        if s:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
        return None
    # actualizar como mucho cada 10 minutos
    if s["last_seen"] < _iso(now - timedelta(minutes=10)):
        exp = _iso(now + timedelta(days=REMEMBER_DAYS)) if s["remember"] else s["expires"]
        db.execute("UPDATE sessions SET last_seen=?, expires=? WHERE token_hash=?", (_iso(now), exp, th))
    return {"id": s["user_id"], "username": s["username"], "is_admin": bool(s["is_admin"]),
            "must_change": bool(s["must_change"]), "token_hash": th, "remember": bool(s["remember"])}


def end_session(token: str | None):
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))


def list_sessions(user_id: int, current_hash: str):
    rows = db.rows("SELECT token_hash, created, last_seen, expires, remember, user_agent, ip FROM sessions "
                   "WHERE user_id=? AND expires>=? ORDER BY last_seen DESC", (user_id, _iso(datetime.now())))
    for r in rows:
        r["current"] = r["token_hash"] == current_hash
        r["id"] = r.pop("token_hash")[:16]
    return rows


def revoke_session(user_id: int, short_id: str):
    db.execute("DELETE FROM sessions WHERE user_id=? AND substr(token_hash,1,16)=?", (user_id, short_id))


def revoke_others(user_id: int, current_hash: str):
    db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user_id, current_hash))


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def _now() -> str:
    return _iso(datetime.now())

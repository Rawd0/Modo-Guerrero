"""Inicio de sesión con Garmin Connect (incluida la verificación en dos pasos).

La contraseña sólo se usa durante el login. Lo que se guarda (cifrado) es el
token de sesión que devuelve Garmin, que se renueva solo.
"""
import logging
import threading
import time

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from . import crypto, db

log = logging.getLogger("guerrero.auth")

# solicitudes de código pendientes, una por usuario de la app
_pending: dict[int, dict] = {}
_lock = threading.Lock()
MFA_TTL = 600  # 10 minutos para introducir el código


class AuthError(Exception):
    pass


def _save_tokens(uid: int, g: Garmin, email: str | None = None):
    db.set_setting(uid, "garmin_token", crypto.encrypt(g.client.dumps()))
    if email:
        db.set_setting(uid, "garmin_email", email)
    db.set_setting(uid, "garmin_auth_ok", True)


def start_login(uid: int, email: str, password: str) -> dict:
    """Primer paso. Devuelve {'mfa': True} si Garmin pide código."""
    with _lock:
        try:
            g = Garmin(email, password, return_on_mfa=True)
            status, state = g.login()
        except GarminConnectTooManyRequestsError:
            raise AuthError("Garmin ha bloqueado temporalmente los intentos de inicio de sesión. Espera unos minutos.")
        except GarminConnectAuthenticationError as e:
            raise AuthError("Correo o contraseña incorrectos, o cuenta bloqueada.") from e
        except Exception as e:  # noqa: BLE001
            log.exception("Login falló")
            raise AuthError(f"No se pudo conectar con Garmin: {e}") from e
        if status == "needs_mfa":
            _pending[uid] = {"state": state, "email": email, "ts": time.time()}
            return {"mfa": True}
        _save_tokens(uid, g, email)
        return {"mfa": False, "ok": True}


def finish_mfa(uid: int, code: str) -> dict:
    with _lock:
        p = _pending.get(uid)
        if not p or time.time() - p["ts"] > MFA_TTL:
            _pending.pop(uid, None)
            raise AuthError("La solicitud de código ha caducado. Vuelve a introducir correo y contraseña.")
        try:
            g = Garmin()
            g.resume_login(p["state"], code.strip())
        except GarminConnectTooManyRequestsError:
            raise AuthError("Demasiados intentos. Espera unos minutos.")
        except Exception as e:  # noqa: BLE001
            log.warning("MFA falló: %s", e)
            raise AuthError("Código incorrecto o caducado.") from e
        _pending.pop(uid, None)
        _save_tokens(uid, g, p["email"])
        return {"ok": True}


def get_client(uid: int) -> Garmin:
    """Cliente autenticado a partir del token guardado del usuario."""
    enc = db.get_setting(uid, "garmin_token")
    tokens = crypto.decrypt(enc) if enc else None
    if not tokens:
        raise AuthError("No hay sesión de Garmin. Conéctate desde Ajustes.")
    g = Garmin()
    try:
        g.login(tokenstore=tokens)
    except Exception as e:  # noqa: BLE001
        db.set_setting(uid, "garmin_auth_ok", False)
        raise AuthError("La sesión de Garmin ha caducado. Vuelve a conectar desde Ajustes.") from e
    return g


def persist_refreshed(uid: int, g: Garmin):
    """Guarda el token tras usarlo (Garmin lo renueva en segundo plano)."""
    try:
        _save_tokens(uid, g)
    except Exception:  # noqa: BLE001
        log.warning("No se pudo guardar el token renovado")


def logout(uid: int):
    db.delete_settings(uid, "garmin_token", "garmin_auth_ok")


def is_connected(uid: int) -> bool:
    return bool(db.get_setting(uid, "garmin_token")) and db.get_setting(uid, "garmin_auth_ok") is not False

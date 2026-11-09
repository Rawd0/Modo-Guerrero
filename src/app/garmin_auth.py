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

_pending = {"state": None, "email": None, "ts": 0}
_lock = threading.Lock()
MFA_TTL = 600  # 10 minutos para introducir el código


class AuthError(Exception):
    pass


def _save_tokens(g: Garmin, email: str | None = None):
    db.set_setting("garmin_token", crypto.encrypt(g.client.dumps()))
    if email:
        db.set_setting("garmin_email", email)
    db.set_setting("garmin_auth_ok", True)


def start_login(email: str, password: str) -> dict:
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
            _pending.update(state=state, email=email, ts=time.time())
            return {"mfa": True}
        _save_tokens(g, email)
        return {"mfa": False, "ok": True}


def finish_mfa(code: str) -> dict:
    with _lock:
        if not _pending["state"] or time.time() - _pending["ts"] > MFA_TTL:
            _pending.update(state=None, email=None, ts=0)
            raise AuthError("La solicitud de código ha caducado. Vuelve a introducir correo y contraseña.")
        try:
            g = Garmin()
            g.resume_login(_pending["state"], code.strip())
        except GarminConnectTooManyRequestsError:
            raise AuthError("Demasiados intentos. Espera unos minutos.")
        except Exception as e:  # noqa: BLE001
            log.warning("MFA falló: %s", e)
            raise AuthError("Código incorrecto o caducado.") from e
        email = _pending["email"]
        _pending.update(state=None, email=None, ts=0)
        _save_tokens(g, email)
        return {"ok": True}


def get_client() -> Garmin:
    """Cliente autenticado a partir del token guardado."""
    enc = db.get_setting("garmin_token")
    tokens = crypto.decrypt(enc) if enc else None
    if not tokens:
        raise AuthError("No hay sesión de Garmin. Conéctate desde Ajustes.")
    g = Garmin()
    try:
        g.login(tokenstore=tokens)
    except Exception as e:  # noqa: BLE001
        db.set_setting("garmin_auth_ok", False)
        raise AuthError("La sesión de Garmin ha caducado. Vuelve a conectar desde Ajustes.") from e
    return g


def persist_refreshed(g: Garmin):
    """Guarda el token tras usarlo (Garmin lo renueva en segundo plano)."""
    try:
        _save_tokens(g)
    except Exception:  # noqa: BLE001
        log.warning("No se pudo guardar el token renovado")


def logout():
    db.execute("DELETE FROM settings WHERE key IN ('garmin_token','garmin_auth_ok')")


def is_connected() -> bool:
    return bool(db.get_setting("garmin_token")) and db.get_setting("garmin_auth_ok") is not False

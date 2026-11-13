"""Entrar con Face ID, Touch ID o la huella: llaves de acceso (passkeys, WebAuthn).

- Sólo funcionan con HTTPS y un nombre de dominio (no con una IP): por ejemplo la dirección
  https://umbrel.tu-red.ts.net que da Tailscale. El administrador registra en Ajustes las direcciones
  HTTPS válidas; una llave queda ligada al dominio con el que se creó.
- La llave privada nunca sale del iPhone (o del llavero de iCloud); el servidor sólo guarda la
  pública. Se exige verificación del usuario (Face ID / código del dispositivo).
- Las llaves son «detectables»: para entrar no hace falta escribir el usuario.
"""
import json
import secrets
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from . import db

RP_NAME = "Modo Guerrero"
CHALLENGE_TTL = 300
_challenges: dict[str, tuple[bytes, float, int | None, str]] = {}  # flujo -> (reto, caduca, usuario, origen)
_lock = threading.Lock()


class PasskeyError(Exception):
    pass


# ---------- direcciones HTTPS permitidas ----------
def allowed_origins() -> list[str]:
    return db.get_global("https_origins", []) or []


def normalize_origin(origin: str) -> str:
    u = urlparse((origin or "").strip())
    if u.scheme != "https" or not u.hostname:
        raise PasskeyError("La dirección debe empezar por https://")
    host = u.hostname
    if host.replace(".", "").isdigit() or ":" in host:
        raise PasskeyError("Face ID necesita un nombre de dominio, no una IP (usa la dirección .ts.net de Tailscale)")
    return f"https://{host}{':' + str(u.port) if u.port and u.port != 443 else ''}"


def add_origin(origin: str) -> list[str]:
    o = normalize_origin(origin)
    lst = allowed_origins()
    if o not in lst:
        lst.append(o)
        db.set_global("https_origins", lst)
    return lst


def remove_origin(origin: str) -> list[str]:
    lst = [o for o in allowed_origins() if o != origin]
    db.set_global("https_origins", lst)
    return lst


def _check_origin(origin: str) -> tuple[str, str]:
    try:
        o = normalize_origin(origin)
    except PasskeyError:
        raise PasskeyError("Face ID sólo funciona abriendo la app por HTTPS con su dirección de dominio")
    if o not in allowed_origins():
        raise PasskeyError("Esta dirección HTTPS no está autorizada todavía: un administrador debe añadirla en Ajustes › HTTPS y Face ID")
    return o, urlparse(o).hostname


def _new_flow(challenge: bytes, uid, origin) -> str:
    now = time.time()
    flow = secrets.token_urlsafe(18)
    with _lock:
        for k in [k for k, v in _challenges.items() if v[1] < now]:
            _challenges.pop(k, None)
        if len(_challenges) > 500:
            raise PasskeyError("Demasiados intentos; espera un momento")
        _challenges[flow] = (challenge, now + CHALLENGE_TTL, uid, origin)
    return flow


def _take_flow(flow: str):
    with _lock:
        v = _challenges.pop(flow or "", None)
    if not v or v[1] < time.time():
        raise PasskeyError("La solicitud ha caducado; vuelve a intentarlo")
    return v


# ---------- alta de una llave ----------
def registration_options(user: dict, origin: str) -> dict:
    o, rp_id = _check_origin(origin)
    existing = db.rows("SELECT credential_id FROM passkeys WHERE user_id=? AND rp_id=?", (user["id"], rp_id))
    opts = generate_registration_options(
        rp_id=rp_id, rp_name=RP_NAME, user_name=user["username"], user_display_name=user["username"],
        user_id=f"mg-user-{user['id']}".encode(),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(r["credential_id"])) for r in existing],
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED,
                                                               user_verification=UserVerificationRequirement.REQUIRED),
        timeout=CHALLENGE_TTL * 1000)
    flow = _new_flow(opts.challenge, user["id"], o)
    return {"flow": flow, "options": json.loads(options_to_json(opts))}


def register(user: dict, flow: str, credential: dict, name: str, origin: str) -> dict:
    challenge, _, uid, o = _take_flow(flow)
    if uid != user["id"] or o != normalize_origin(origin):
        raise PasskeyError("Solicitud no válida")
    rp_id = urlparse(o).hostname
    try:
        v = verify_registration_response(credential=credential, expected_challenge=challenge, expected_origin=o,
                                         expected_rp_id=rp_id, require_user_verification=True)
    except Exception as e:  # noqa: BLE001 (la librería lanza varios tipos)
        raise PasskeyError(f"No se pudo verificar la llave: {e}")
    cid = bytes_to_base64url(v.credential_id)
    if db.one("SELECT 1 x FROM passkeys WHERE credential_id=?", (cid,)):
        raise PasskeyError("Esta llave ya está registrada")
    transports = (credential.get("response") or {}).get("transports") or []
    name = (name or "").strip()[:60] or "Llave de acceso"
    db.execute("INSERT INTO passkeys (credential_id, user_id, public_key, sign_count, transports, name, rp_id, created, "
               "last_used, backed_up) VALUES (?,?,?,?,?,?,?,?,NULL,?)",
               (cid, user["id"], bytes_to_base64url(v.credential_public_key), v.sign_count, json.dumps(transports),
                name, rp_id, datetime.now().isoformat(timespec="seconds"), int(bool(v.credential_backed_up))))
    return {"ok": True, "name": name}


# ---------- entrar ----------
def login_options(origin: str) -> dict:
    o, rp_id = _check_origin(origin)
    opts = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED,
                                           timeout=CHALLENGE_TTL * 1000)
    return {"flow": _new_flow(opts.challenge, None, o), "options": json.loads(options_to_json(opts))}


def login(flow: str, credential: dict, origin: str) -> int:
    challenge, _, _, o = _take_flow(flow)
    if o != normalize_origin(origin):
        raise PasskeyError("Solicitud no válida")
    cid = credential.get("id") or credential.get("rawId")
    row = db.one("SELECT p.*, u.id uid FROM passkeys p JOIN users u ON u.id=p.user_id WHERE p.credential_id=?", (cid,))
    if not row:
        raise PasskeyError("Esta llave no está registrada en Modo Guerrero (quizá se borró)")
    if row["rp_id"] != urlparse(o).hostname:
        raise PasskeyError("Esta llave se creó para otra dirección")
    try:
        v = verify_authentication_response(
            credential=credential, expected_challenge=challenge, expected_origin=o, expected_rp_id=row["rp_id"],
            credential_public_key=base64url_to_bytes(row["public_key"]), credential_current_sign_count=row["sign_count"] or 0,
            require_user_verification=True)
    except Exception as e:  # noqa: BLE001
        raise PasskeyError(f"No se pudo verificar la llave: {e}")
    db.execute("UPDATE passkeys SET sign_count=?, last_used=? WHERE credential_id=?",
               (v.new_sign_count, datetime.now().isoformat(timespec="seconds"), cid))
    return row["uid"]


# ---------- gestión ----------
def list_for(uid: int):
    return db.rows("SELECT credential_id id, name, rp_id, created, last_used, backed_up FROM passkeys WHERE user_id=? "
                   "ORDER BY created", (uid,))


def rename(uid: int, cid: str, name: str):
    name = (name or "").strip()[:60]
    if not name:
        raise PasskeyError("Pon un nombre")
    db.execute("UPDATE passkeys SET name=? WHERE credential_id=? AND user_id=?", (name, cid, uid))


def delete(uid: int, cid: str):
    db.execute("DELETE FROM passkeys WHERE credential_id=? AND user_id=?", (cid, uid))

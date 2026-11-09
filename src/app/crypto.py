"""Cifrado del token de sesión de Garmin (Fernet)."""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from .config import APP_SECRET_KEY, DATA_DIR

_KEY_FILE = DATA_DIR / "secret.key"


def _key() -> bytes:
    if APP_SECRET_KEY:
        return base64.urlsafe_b64encode(hashlib.sha256(APP_SECRET_KEY.encode()).digest())
    if not _KEY_FILE.exists():
        _KEY_FILE.write_bytes(Fernet.generate_key())
        os.chmod(_KEY_FILE, 0o600)
    return _KEY_FILE.read_bytes().strip()


def encrypt(text: str) -> str:
    return Fernet(_key()).encrypt(text.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return Fernet(_key()).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None

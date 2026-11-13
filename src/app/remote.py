"""Copia de las copias de seguridad fuera del servidor: Nextcloud (WebDAV) o Google Drive.

- Nextcloud / WebDAV: dirección WebDAV, usuario y una contraseña de aplicación (no la tuya).
- Google Drive: con una aplicación OAuth propia del usuario (tipo «TV y dispositivos de entrada
  limitada») y el permiso mínimo `drive.file`, que sólo da acceso a los archivos que crea esta app.
  La autorización se hace con un código que se introduce en google.com/device: no hace falta que el
  servidor sea accesible desde internet.

Las contraseñas y tokens se guardan cifrados con la misma clave que el token de Garmin.
"""
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree

import requests

from . import backup, crypto, db

log = logging.getLogger("guerrero.remote")

TIMEOUT = 60
GOOGLE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DEFAULTS = {"provider": "none", "keep": 14, "upload_manual": True,
            "webdav": {"url": "", "user": "", "folder": "Modo Guerrero", "password": None},
            "gdrive": {"client_id": "", "client_secret": None, "refresh_token": None, "folder_id": None,
                       "account": None},
            "last": None}

_lock = threading.Lock()
_pending_device = {}  # código de Google pendiente de autorizar


class RemoteError(Exception):
    pass


# ---------- ajustes ----------
def _raw() -> dict:
    s = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    saved = db.get_global("remote_backup", {}) or {}
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k].update(v)
        else:
            s[k] = v
    return s


def _save(s: dict):
    db.set_global("remote_backup", s)


def public_settings() -> dict:
    """Ajustes sin secretos, para la interfaz."""
    s = _raw()
    w, g = s["webdav"], s["gdrive"]
    return {"provider": s["provider"], "keep": s["keep"], "upload_manual": s["upload_manual"], "last": s["last"],
            "webdav": {"url": w["url"], "user": w["user"], "folder": w["folder"], "has_password": bool(w["password"])},
            "gdrive": {"client_id": g["client_id"], "has_secret": bool(g["client_secret"]),
                       "connected": bool(g["refresh_token"]), "account": g["account"]},
            "pending_code": {k: v for k, v in _pending_device.items() if k != "device_code"} or None}


def save_settings(payload: dict) -> dict:
    s = _raw()
    provider = payload.get("provider", s["provider"])
    if provider not in ("none", "webdav", "gdrive"):
        raise RemoteError("Destino no válido")
    s["provider"] = provider
    if "keep" in payload:
        try:
            s["keep"] = int(payload["keep"])
        except (TypeError, ValueError):
            raise RemoteError("Número de copias no válido")
        if not 1 <= s["keep"] <= 365:
            raise RemoteError("Conserva entre 1 y 365 copias en el destino")
    if "upload_manual" in payload:
        s["upload_manual"] = bool(payload["upload_manual"])
    w = payload.get("webdav")
    if isinstance(w, dict):
        url = (w.get("url") or "").strip()
        if url and urlparse(url).scheme not in ("http", "https"):
            raise RemoteError("La dirección WebDAV debe empezar por http:// o https://")
        s["webdav"]["url"] = url
        s["webdav"]["user"] = (w.get("user") or "").strip()
        s["webdav"]["folder"] = (w.get("folder") or "Modo Guerrero").strip().strip("/") or "Modo Guerrero"
        if w.get("password"):
            s["webdav"]["password"] = crypto.encrypt(w["password"])
    g = payload.get("gdrive")
    if isinstance(g, dict):
        cid = (g.get("client_id") or "").strip()
        if cid != s["gdrive"]["client_id"]:
            # otra aplicación: hay que volver a autorizar
            s["gdrive"].update(refresh_token=None, folder_id=None, account=None)
        s["gdrive"]["client_id"] = cid
        if g.get("client_secret"):
            s["gdrive"]["client_secret"] = crypto.encrypt(g["client_secret"].strip())
    _save(s)
    return public_settings()


def _secret(enc):
    return crypto.decrypt(enc) if enc else None


def _http_error(e: Exception) -> str:
    if isinstance(e, requests.exceptions.ConnectionError):
        return "No se pudo conectar con el destino (revisa la dirección y que sea accesible desde el servidor)"
    if isinstance(e, requests.exceptions.Timeout):
        return "El destino no responde (tiempo agotado)"
    return str(e)


# ---------- WebDAV (Nextcloud, ownCloud, NAS…) ----------
class WebDAV:
    def __init__(self, cfg):
        if not cfg["url"] or not cfg["user"] or not cfg["password"]:
            raise RemoteError("Completa la dirección WebDAV, el usuario y la contraseña de aplicación")
        pw = _secret(cfg["password"])
        if pw is None:
            raise RemoteError("No se puede leer la contraseña guardada; vuelve a escribirla")
        self.base = cfg["url"].rstrip("/") + "/"
        self.folder = cfg["folder"]
        self.s = requests.Session()
        self.s.auth = (cfg["user"], pw)

    def _url(self, name=""):
        parts = [quote(p) for p in self.folder.split("/") if p]
        return self.base + "/".join(parts) + "/" + quote(name)

    def _check(self, r, what):
        if r.status_code in (401, 403):
            raise RemoteError("Usuario o contraseña incorrectos (usa una contraseña de aplicación de Nextcloud)")
        if r.status_code == 400 and "trusted" in r.text.lower():
            raise RemoteError("Nextcloud rechaza esta dirección: añádela a «trusted_domains» o usa la IP del servidor")
        if r.status_code >= 400:
            raise RemoteError(f"{what}: el servidor respondió {r.status_code}")
        return r

    def ensure_folder(self):
        path = ""
        for part in [p for p in self.folder.split("/") if p]:
            path += quote(part) + "/"
            r = self.s.request("PROPFIND", self.base + path, headers={"Depth": "0"}, timeout=TIMEOUT)
            if r.status_code == 404:
                self._check(self.s.request("MKCOL", self.base + path, timeout=TIMEOUT), "No se pudo crear la carpeta")
            else:
                self._check(r, "No se pudo abrir la carpeta")

    def upload(self, path: Path):
        with open(path, "rb") as f:
            self._check(self.s.put(self._url(path.name), data=f, timeout=600,
                                   headers={"Content-Type": "application/gzip"}), "No se pudo subir la copia")

    def list(self):
        r = self._check(self.s.request("PROPFIND", self._url(), headers={"Depth": "1"}, timeout=TIMEOUT),
                        "No se pudo listar la carpeta")
        out = []
        ns = {"d": "DAV:"}
        for resp in ElementTree.fromstring(r.content).findall("d:response", ns):
            href = unquote(resp.findtext("d:href", "", ns)).rstrip("/").rsplit("/", 1)[-1]
            if backup.NAME_RE.match(href):
                size = resp.findtext(".//d:getcontentlength", None, ns)
                out.append({"name": href, "id": href, "size": int(size) if size else None})
        return out

    def delete(self, item):
        r = self.s.delete(self._url(item["name"]), timeout=TIMEOUT)
        if r.status_code not in (200, 204, 404):
            self._check(r, "No se pudo borrar una copia antigua")

    def describe(self):
        return f"{self.base}{self.folder}"


# ---------- Google Drive ----------
class GDrive:
    API = "https://www.googleapis.com/drive/v3"

    def __init__(self, s):
        self.s = s
        g = s["gdrive"]
        if not g["refresh_token"]:
            raise RemoteError("Google Drive no está autorizado todavía")
        self.cfg = g
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {self._access_token()}"

    def _access_token(self):
        g = self.cfg
        r = requests.post("https://oauth2.googleapis.com/token", timeout=TIMEOUT, data={
            "client_id": g["client_id"], "client_secret": _secret(g["client_secret"]) or "",
            "refresh_token": _secret(g["refresh_token"]) or "", "grant_type": "refresh_token"})
        if r.status_code != 200:
            err = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("error")
            if err in ("invalid_grant", "unauthorized_client", "invalid_client"):
                raise RemoteError("Google ha retirado el permiso (o la app de Google está en modo de prueba y "
                                  "caduca a los 7 días). Vuelve a autorizar Google Drive.")
            raise RemoteError(f"Google respondió {r.status_code} al renovar el acceso")
        return r.json()["access_token"]

    def ensure_folder(self):
        fid = self.cfg.get("folder_id")
        if fid:
            r = self.http.get(f"{self.API}/files/{fid}", params={"fields": "id,trashed"}, timeout=TIMEOUT)
            if r.status_code == 200 and not r.json().get("trashed"):
                return fid
        r = self.http.post(f"{self.API}/files", timeout=TIMEOUT, json={
            "name": "Modo Guerrero", "mimeType": "application/vnd.google-apps.folder"})
        if r.status_code >= 400:
            raise RemoteError(f"No se pudo crear la carpeta en Drive ({r.status_code})")
        self.cfg["folder_id"] = r.json()["id"]
        s = _raw()
        s["gdrive"]["folder_id"] = self.cfg["folder_id"]
        _save(s)
        return self.cfg["folder_id"]

    def upload(self, path: Path):
        fid = self.ensure_folder()
        r = self.http.post("https://www.googleapis.com/upload/drive/v3/files", params={"uploadType": "resumable"},
                           json={"name": path.name, "parents": [fid]}, timeout=TIMEOUT)
        if r.status_code >= 400 or "Location" not in r.headers:
            raise RemoteError(f"Drive no aceptó la subida ({r.status_code})")
        with open(path, "rb") as f:
            up = self.http.put(r.headers["Location"], data=f, timeout=600, headers={"Content-Type": "application/gzip"})
        if up.status_code >= 400:
            raise RemoteError(f"La subida a Drive falló ({up.status_code})")

    def list(self):
        fid = self.ensure_folder()
        out, token = [], None
        while True:
            r = self.http.get(f"{self.API}/files", timeout=TIMEOUT, params={
                "q": f"'{fid}' in parents and trashed=false", "fields": "nextPageToken,files(id,name,size)",
                "pageSize": 200, **({"pageToken": token} if token else {})})
            if r.status_code >= 400:
                raise RemoteError(f"No se pudo listar la carpeta de Drive ({r.status_code})")
            j = r.json()
            out += [{"name": f["name"], "id": f["id"], "size": int(f["size"]) if f.get("size") else None}
                    for f in j.get("files", []) if backup.NAME_RE.match(f["name"])]
            token = j.get("nextPageToken")
            if not token:
                return out

    def delete(self, item):
        r = self.http.delete(f"{self.API}/files/{item['id']}", timeout=TIMEOUT)
        if r.status_code not in (200, 204, 404):
            raise RemoteError(f"No se pudo borrar una copia antigua en Drive ({r.status_code})")

    def describe(self):
        return f"Google Drive{' (' + self.cfg['account'] + ')' if self.cfg.get('account') else ''} › Modo Guerrero"


def _client(s=None):
    s = s or _raw()
    if s["provider"] == "webdav":
        return WebDAV(s["webdav"])
    if s["provider"] == "gdrive":
        return GDrive(s)
    raise RemoteError("No hay ningún destino configurado")


# ---------- autorización de Google (flujo de dispositivo) ----------
def gdrive_start():
    s = _raw()
    g = s["gdrive"]
    if not g["client_id"] or not g["client_secret"]:
        raise RemoteError("Guarda primero el ID de cliente y el secreto de tu aplicación de Google")
    try:
        r = requests.post("https://oauth2.googleapis.com/device/code", timeout=TIMEOUT,
                          data={"client_id": g["client_id"], "scope": GOOGLE_SCOPE})
    except requests.RequestException as e:
        raise RemoteError(_http_error(e))
    if r.status_code != 200:
        err = r.json().get("error") if r.headers.get("content-type", "").startswith("application/json") else None
        if err == "invalid_client":
            raise RemoteError("Google no reconoce el ID de cliente. Comprueba que el tipo de cliente sea "
                              "«TV y dispositivos de entrada limitada»")
        raise RemoteError(f"Google respondió {r.status_code} ({err or 'error'})")
    j = r.json()
    _pending_device.clear()
    _pending_device.update(device_code=j["device_code"], user_code=j["user_code"],
                           url=j.get("verification_url") or j.get("verification_uri"),
                           interval=int(j.get("interval", 5)), expires=time.time() + int(j.get("expires_in", 1800)))
    return {k: v for k, v in _pending_device.items() if k != "device_code"}


def gdrive_poll():
    if not _pending_device:
        return {"status": "none"}
    if time.time() > _pending_device["expires"]:
        _pending_device.clear()
        return {"status": "expired"}
    s = _raw()
    g = s["gdrive"]
    r = requests.post("https://oauth2.googleapis.com/token", timeout=TIMEOUT, data={
        "client_id": g["client_id"], "client_secret": _secret(g["client_secret"]) or "",
        "device_code": _pending_device["device_code"], "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code == 200 and j.get("refresh_token"):
        g["refresh_token"] = crypto.encrypt(j["refresh_token"])
        g["folder_id"] = None
        try:
            about = requests.get("https://www.googleapis.com/drive/v3/about", params={"fields": "user(emailAddress)"},
                                 headers={"Authorization": f"Bearer {j['access_token']}"}, timeout=TIMEOUT)
            g["account"] = about.json().get("user", {}).get("emailAddress") if about.ok else None
        except requests.RequestException:
            g["account"] = None
        s["provider"] = "gdrive"
        _save(s)
        _pending_device.clear()
        return {"status": "ok", "account": g["account"]}
    err = j.get("error")
    if err in ("authorization_pending", "slow_down"):
        return {"status": "pending"}
    _pending_device.clear()
    return {"status": "denied" if err == "access_denied" else "error", "error": err}


def gdrive_disconnect():
    s = _raw()
    tok = _secret(s["gdrive"]["refresh_token"])
    if tok:
        try:
            requests.post("https://oauth2.googleapis.com/revoke", data={"token": tok}, timeout=15)
        except requests.RequestException:
            pass
    s["gdrive"].update(refresh_token=None, folder_id=None, account=None)
    if s["provider"] == "gdrive":
        s["provider"] = "none"
    _save(s)


# ---------- operaciones ----------
def test():
    try:
        c = _client()
        c.ensure_folder()
        items = c.list()
    except RemoteError:
        raise
    except requests.RequestException as e:
        raise RemoteError(_http_error(e))
    return {"ok": True, "where": c.describe(), "count": len(items)}


def upload(name: str | None = None) -> dict:
    """Sube una copia (la última si no se indica) y aplica la retención en el destino."""
    s = _raw()
    if s["provider"] == "none":
        raise RemoteError("No hay ningún destino configurado")
    with _lock:
        try:
            if name is None:
                items = [b for b in backup.list_backups() if b["kind"] != "pre-restore"]
                if not items:
                    raise RemoteError("Aún no hay ninguna copia que subir")
                name = items[0]["name"]
            path = backup.path_for(name)
            c = _client(s)
            c.ensure_folder()
            c.upload(path)
            remote = sorted(c.list(), key=lambda x: x["name"], reverse=True)  # el nombre lleva la fecha
            removed = 0
            for item in remote[s["keep"]:]:
                c.delete(item)
                removed += 1
            last = {"ok": True, "at": datetime.now().isoformat(timespec="seconds"), "name": name,
                    "where": c.describe(), "remote_count": min(len(remote), s["keep"]), "removed": removed}
            log.info("Copia %s subida a %s", name, c.describe())
        except (RemoteError, backup.BackupError, requests.RequestException) as e:
            msg = _http_error(e) if isinstance(e, requests.RequestException) else str(e)
            last = {"ok": False, "at": datetime.now().isoformat(timespec="seconds"), "name": name, "error": msg}
            log.warning("No se pudo subir la copia: %s", msg)
        s = _raw()
        s["last"] = last
        _save(s)
        if not last["ok"]:
            raise RemoteError(last["error"])
        return last


def after_backup(info: dict):
    """Se llama tras crear una copia: la sube en segundo plano si procede."""
    s = _raw()
    if s["provider"] == "none" or info["kind"] == "pre-restore":
        return
    if info["kind"] == "manual" and not s["upload_manual"]:
        return

    def run():
        try:
            upload(info["name"])
        except RemoteError as e:  # queda registrado en «last»; se avisa a los administradores
            try:
                from . import push
                push.backup_failed(f"No se pudo subir la copia fuera del servidor: {e}")
            except Exception:  # noqa: BLE001
                pass
    threading.Thread(target=run, daemon=True, name="remote-upload").start()

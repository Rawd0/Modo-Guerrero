"""Copias de seguridad de la base de datos.

- La copia se hace en caliente con la API de copia de SQLite: es consistente aunque la app
  esté sincronizando en ese momento.
- Se guarda comprimida en DATA_DIR/backups con la versión de la app en el nombre.
- Retención por defecto: 7 diarias, 4 semanales (lunes) y 6 mensuales (día 1), más las manuales
  y las previas a una restauración, que se conservan hasta que se borren a mano.
- La clave que cifra los tokens de Garmin NO va dentro de la copia: si la copia se filtra, no
  sirve para entrar en las cuentas de Garmin. Restaurando en el mismo servidor todo sigue igual;
  en otro servidor, cada usuario tendrá que volver a conectar Garmin.
"""
import gzip
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import db, metrics
from .config import DATA_DIR, DB_PATH, VERSION

log = logging.getLogger("guerrero.backup")

BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
NAME_RE = re.compile(r"^modo-guerrero-(\d{8}-\d{6})-v([0-9A-Za-z.\-]+)-(auto|manual|pre-restore)\.db\.gz$")
REQUIRED_TABLES = {"activities", "users", "daily_health"}  # comunes a todas las versiones con usuarios

DEFAULTS = {"enabled": True, "hour": 4, "keep_daily": 7, "keep_weekly": 4, "keep_monthly": 6}

_lock = threading.Lock()
state = {"running": False, "last_error": None, "next_run": None}


class BackupError(Exception):
    pass


# ---------- ajustes ----------
def get_settings() -> dict:
    s = dict(DEFAULTS)
    s.update(db.get_global("backup", {}) or {})
    return s


def save_settings(payload: dict) -> dict:
    s = get_settings()
    try:
        if "enabled" in payload:
            s["enabled"] = bool(payload["enabled"])
        if "hour" in payload:
            s["hour"] = int(payload["hour"])
        for k in ("keep_daily", "keep_weekly", "keep_monthly"):
            if k in payload:
                s[k] = int(payload[k])
    except (TypeError, ValueError):
        raise BackupError("Valores no válidos")
    if not 0 <= s["hour"] <= 23:
        raise BackupError("La hora debe estar entre 0 y 23")
    if not (1 <= s["keep_daily"] <= 60 and 0 <= s["keep_weekly"] <= 52 and 0 <= s["keep_monthly"] <= 60):
        raise BackupError("Revisa cuántas copias conservar")
    db.set_global("backup", s)
    return s


# ---------- listado ----------
def _parse(p: Path):
    m = NAME_RE.match(p.name)
    if not m:
        return None
    created = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")
    return {"name": p.name, "created": created.isoformat(timespec="seconds"), "version": m.group(2),
            "kind": m.group(3), "size": p.stat().st_size}


def list_backups():
    items = [x for x in (_parse(p) for p in BACKUP_DIR.glob("*.db.gz")) if x]
    return sorted(items, key=lambda x: x["created"], reverse=True)


def path_for(name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise BackupError("Copia no encontrada")
    p = BACKUP_DIR / name
    if not p.is_file():
        raise BackupError("Copia no encontrada")
    return p


# ---------- crear ----------
def create(kind="manual") -> dict:
    if kind not in ("auto", "manual", "pre-restore"):
        raise BackupError("Tipo de copia no válido")
    with _lock:
        state["running"] = True
        try:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = f"modo-guerrero-{stamp}-v{VERSION}-{kind}.db.gz"
            final = BACKUP_DIR / name
            with tempfile.TemporaryDirectory(dir=BACKUP_DIR) as tmp:
                snap = Path(tmp) / "snapshot.db"
                src = sqlite3.connect(DB_PATH, timeout=60)
                dst = sqlite3.connect(snap)
                try:
                    src.backup(dst, pages=4096, sleep=0.01)  # por bloques: no bloquea la app
                finally:
                    dst.close()
                    src.close()
                # una copia de una base dañada no sirve: comprobarla antes de guardarla
                _verify(snap)
                part = final.with_suffix(".part")
                with open(snap, "rb") as fi, gzip.open(part, "wb", compresslevel=6) as fo:
                    shutil.copyfileobj(fi, fo, 1024 * 1024)
                os.replace(part, final)
            os.chmod(final, 0o600)
            state["last_error"] = None
            log.info("Copia creada: %s (%s KB)", name, final.stat().st_size // 1024)
            info = _parse(final)
        except BackupError:
            raise
        except Exception as e:  # noqa: BLE001
            state["last_error"] = str(e)
            log.exception("La copia de seguridad falló")
            raise BackupError(f"No se pudo crear la copia: {e}")
        finally:
            state["running"] = False
    from . import remote  # subirla fuera del servidor, si está configurado (en segundo plano)
    remote.after_backup(info)
    return info


def delete(name: str):
    path_for(name).unlink()


# ---------- validar y restaurar ----------
def _verify(db_file: Path) -> dict:
    try:
        con = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            version = con.execute("PRAGMA user_version").fetchone()[0]
            users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0] if "users" in tables else 0
            runs = con.execute("SELECT COUNT(*) FROM activities WHERE is_run=1").fetchone()[0] \
                if "activities" in tables else 0
        finally:
            con.close()
    except sqlite3.DatabaseError:
        raise BackupError("El archivo no es una copia válida de Modo Guerrero")
    if ok != "ok":
        raise BackupError("La copia está dañada")
    if not REQUIRED_TABLES.issubset(tables):
        raise BackupError("El archivo no es una copia de Modo Guerrero (faltan tablas)")
    if version > db.SCHEMA_VERSION:
        raise BackupError("La copia es de una versión más nueva de la app; actualiza la app primero")
    if users == 0:
        raise BackupError("La copia no tiene ningún usuario: no podrías entrar después de restaurarla")
    return {"schema": version, "users": users, "runs": runs}


def _gunzip_to(src_gz: Path, dest: Path, max_bytes=8 * 1024 ** 3):
    try:
        with gzip.open(src_gz, "rb") as fi, open(dest, "wb") as fo:
            total = 0
            while chunk := fi.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise BackupError("La copia es demasiado grande")
                fo.write(chunk)
    except (OSError, EOFError) as e:
        if isinstance(e, BackupError):
            raise
        raise BackupError("El archivo no es una copia válida (no es .db.gz)")


def restore_file(gz_path: Path) -> dict:
    """Restaura una copia. Antes guarda una copia del estado actual por si hay que deshacerlo."""
    with tempfile.TemporaryDirectory(dir=BACKUP_DIR) as tmp:
        raw = Path(tmp) / "restore.db"
        _gunzip_to(gz_path, raw)
        info = _verify(raw)
        safety = create("pre-restore")
        # la copia sustituye a la base actual por dentro (mismo archivo), con la app bloqueada
        with db._lock:
            src = sqlite3.connect(raw)
            dst = sqlite3.connect(DB_PATH, timeout=60)
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()
        db.init()  # migra la copia si es de una versión anterior
    # recalcular en segundo plano lo derivado (GAP, curva de ritmo) si la copia es de una versión anterior
    def _after():
        from . import routes
        metrics.backfill_derived()
        routes.backfill()
    threading.Thread(target=_after, daemon=True, name="backfill-restore").start()
    log.info("Copia restaurada (%s usuarios, %s carreras)", info["users"], info["runs"])
    return {**info, "safety_backup": safety["name"]}


# ---------- retención ----------
def prune():
    """Borra copias automáticas sobrantes según la retención diaria/semanal/mensual."""
    s = get_settings()
    autos = [b for b in list_backups() if b["kind"] == "auto"]
    keep = set()
    days, weeks, months = set(), set(), set()
    for b in autos:  # de la más nueva a la más antigua
        d = datetime.fromisoformat(b["created"]).date()
        if len(days) < s["keep_daily"] and d not in days:
            days.add(d)
            keep.add(b["name"])
        wk = d - timedelta(days=d.weekday())
        if len(weeks) < s["keep_weekly"] and wk not in weeks:
            weeks.add(wk)
            keep.add(b["name"])
        mo = (d.year, d.month)
        if len(months) < s["keep_monthly"] and mo not in months:
            months.add(mo)
            keep.add(b["name"])
    removed = 0
    for b in autos:
        if b["name"] not in keep:
            try:
                (BACKUP_DIR / b["name"]).unlink()
                removed += 1
            except OSError:
                pass
    # restos de copias interrumpidas
    for p in BACKUP_DIR.glob("*.part"):
        if time.time() - p.stat().st_mtime > 3600:
            p.unlink(missing_ok=True)
    return removed


# ---------- programación ----------
def _has_auto_today(today: date) -> bool:
    return any(b["kind"] == "auto" and b["created"][:10] == today.isoformat() for b in list_backups())


def scheduler_loop():
    time.sleep(30)
    while True:
        try:
            s = get_settings()
            now = datetime.now()
            if s["enabled"]:
                # una copia automática al día, a partir de la hora elegida (o en cuanto arranque, si ya pasó)
                if now.hour >= s["hour"] and not _has_auto_today(now.date()):
                    create("auto")
                    prune()
                today_at = now.replace(hour=s["hour"], minute=0, second=0, microsecond=0)
                nxt = today_at + timedelta(days=1) if _has_auto_today(now.date()) else today_at
                state["next_run"] = nxt.isoformat(timespec="minutes")
            else:
                state["next_run"] = None
        except Exception as e:  # noqa: BLE001
            state["last_error"] = str(e)
            log.exception("Programador de copias")
        time.sleep(60)


def start_scheduler():
    threading.Thread(target=scheduler_loop, daemon=True, name="backup").start()


def summary():
    items = list_backups()
    return {"settings": get_settings(), "state": state, "backups": items,
            "total_size": sum(b["size"] for b in items), "dir": str(BACKUP_DIR)}

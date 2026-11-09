"""API web de Modo Guerrero."""
import base64
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import db, garmin_auth, metrics, stats, sync
from .config import APP_NAME, APP_PASSWORD, APP_USER, DEFAULT_SETTINGS, VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app):
    db.init()
    sync.start_scheduler()
    yield


app = FastAPI(title=APP_NAME, version=VERSION, docs_url=None, redoc_url=None, lifespan=lifespan)


# ---------- contraseña opcional (HTTP Basic) ----------
@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if APP_PASSWORD and request.url.path != "/healthz":
        ok = False
        h = request.headers.get("authorization", "")
        if h.lower().startswith("basic "):
            try:
                user, _, pwd = base64.b64decode(h[6:]).decode().partition(":")
                ok = secrets.compare_digest(user, APP_USER) and secrets.compare_digest(pwd, APP_PASSWORD)
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": f'Basic realm="{APP_NAME}"'})
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # los mapas de OpenStreetMap exigen la cabecera Referer
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------- estado y sincronización ----------
@app.get("/api/status")
def status():
    counts = db.one("SELECT COUNT(*) total, SUM(is_run) runs, "
                    "SUM(CASE WHEN is_run=1 AND fit_status='pending' THEN 1 ELSE 0 END) pending_fit "
                    "FROM activities")
    last_log = db.one("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1")
    return {
        "app": APP_NAME, "version": VERSION,
        "connected": garmin_auth.is_connected(),
        "email": db.get_setting("garmin_email"),
        "sync": sync.state, "last_log": last_log, "counts": counts,
        "health_days": (db.one("SELECT COUNT(*) n FROM daily_health") or {}).get("n", 0),
    }


@app.post("/api/sync")
def sync_now():
    if not garmin_auth.is_connected():
        raise HTTPException(400, "Conecta primero tu cuenta de Garmin")
    sync.trigger()
    return {"ok": True}


@app.get("/api/sync/log")
def sync_log():
    return db.rows("SELECT * FROM sync_log ORDER BY id DESC LIMIT 30")


# ---------- autenticación Garmin ----------
def _auth_call(fn, *a):
    try:
        return fn(*a)
    except garmin_auth.AuthError as e:
        raise HTTPException(400, str(e))


@app.post("/api/garmin/login")
def garmin_login(payload: dict = Body(...)):
    email, pwd = (payload.get("email") or "").strip(), payload.get("password") or ""
    if not email or not pwd:
        raise HTTPException(400, "Introduce correo y contraseña")
    r = _auth_call(garmin_auth.start_login, email, pwd)
    if r.get("ok"):
        sync.trigger()
    return r


@app.post("/api/garmin/mfa")
def garmin_mfa(payload: dict = Body(...)):
    r = _auth_call(garmin_auth.finish_mfa, payload.get("code") or "")
    sync.trigger()
    return r


@app.post("/api/garmin/logout")
def garmin_logout():
    garmin_auth.logout()
    return {"ok": True}


# ---------- ajustes ----------
@app.get("/api/settings")
def get_settings():
    return db.all_settings()


@app.put("/api/settings")
def put_settings(payload: dict = Body(...)):
    for k, v in payload.items():
        if k in DEFAULT_SETTINGS:
            db.set_setting(k, v)
    return db.all_settings()


# ---------- datos ----------
@app.get("/api/home")
def home():
    return stats.home()


@app.get("/api/activities")
def activities(q: str = "", year: str = "", sport: str = "", min_km: float = 0, max_km: float = 0,
               sort: str = "date", order: str = "desc", page: int = 1, size: int = 50):
    where, params = ["is_run=1"], []
    if q:
        where.append("name LIKE ?")
        params.append(f"%{q}%")
    if year:
        where.append("substr(date,1,4)=?")
        params.append(year)
    if sport:
        where.append("sport=?")
        params.append(sport)
    if min_km:
        where.append("distance_m>=?")
        params.append(min_km * 1000)
    if max_km:
        where.append("distance_m<=?")
        params.append(max_km * 1000)
    cols = {"date": "start_local", "distance": "distance_m", "time": "moving_s", "pace": "moving_s/distance_m",
            "hr": "avg_hr", "elev": "elev_gain", "load": "training_load"}
    sort_col = cols.get(sort, "start_local")
    order = "ASC" if order.lower() == "asc" else "DESC"
    w = " AND ".join(where)
    total = db.one(f"SELECT COUNT(*) n FROM activities WHERE {w}", params)["n"]
    size = min(max(size, 1), 200)
    items = db.rows(f"SELECT {stats.RUN_COLS} FROM activities WHERE {w} ORDER BY {sort_col} {order} NULLS LAST "
                    f"LIMIT ? OFFSET ?", params + [size, (max(page, 1) - 1) * size])
    years = [r["y"] for r in db.rows("SELECT DISTINCT substr(date,1,4) y FROM activities WHERE is_run=1 ORDER BY y DESC")]
    sports = [r["sport"] for r in db.rows("SELECT DISTINCT sport FROM activities WHERE is_run=1")]
    return {"total": total, "items": items, "years": years, "sports": sports}


@app.get("/api/activities/{aid}")
def activity(aid: int):
    a = db.one(f"SELECT {stats.RUN_COLS}, max_speed, elev_loss, start_lat, start_lon FROM activities WHERE id=?", (aid,))
    if not a:
        raise HTTPException(404, "Actividad no encontrada")
    st = db.load_stream(aid)
    efforts = db.rows("SELECT distance_m, time_s FROM best_efforts WHERE activity_id=? ORDER BY distance_m", (aid,))
    # ¿es récord personal?
    for e in efforts:
        best = db.one("SELECT MIN(time_s) m FROM best_efforts WHERE distance_m=?", (e["distance_m"],))
        e["is_pr"] = best and abs(best["m"] - e["time_s"]) < 0.05
    hr_rest, hr_max = metrics.hr_bounds()
    zones = None
    if st and any(st.get("hr") or []):
        # tiempo en 5 zonas por % de FC máxima
        bounds = [0.6, 0.7, 0.8, 0.9]
        zt = [0.0] * 5
        ta = metrics.active_time(st["t"], st["d"])
        for k in range(1, len(st["t"])):
            h = st["hr"][k]
            if not h:
                continue
            frac = h / hr_max
            z = sum(1 for b in bounds if frac >= b)
            zt[z] += ta[k] - ta[k - 1]
        zones = {"seconds": [round(x) for x in zt], "hr_max": hr_max,
                 "limits": [round(b * hr_max) for b in bounds]}
    return {
        "activity": a,
        "stream": metrics.downsample(st) if st else None,
        "splits": metrics.km_splits(st) if st else [],
        "efforts": efforts,
        "zones": zones,
    }


@app.get("/api/records")
def records():
    return stats.records()


@app.get("/api/stats")
def get_stats(group: str = "month"):
    if group not in ("week", "month", "year"):
        group = "month"
    return stats.stats(group)


@app.get("/api/health")
def get_health(days: int = 90):
    return stats.health(min(max(days, 7), 3650))


@app.get("/api/fitness")
def get_fitness(days: int = 180):
    snaps = db.rows("SELECT date, vo2max FROM snapshots WHERE vo2max IS NOT NULL ORDER BY date")
    vo2 = db.rows("SELECT date, MAX(vo2max) vo2max FROM activities WHERE vo2max IS NOT NULL GROUP BY date ORDER BY date")
    return {"series": metrics.fitness_series(min(max(days, 14), 3650)), "vo2": vo2 or snaps,
            "snapshot": stats.latest_snapshot()}


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        blob = await f.read()
        try:
            r = sync.import_fit(blob)
        except Exception:  # noqa: BLE001
            r = [{"ok": False, "error": "No es un archivo .FIT válido o está dañado"}]
        results.append({"file": f.filename, "results": r})
    return results


# ---------- frontend ----------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "No encontrado"}, status_code=404)
    html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__VERSION__", VERSION)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

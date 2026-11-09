"""API web de Modo Guerrero."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, db, garmin_auth, metrics, stats, sync
from .config import APP_NAME, DEFAULT_SETTINGS, VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app):
    db.init()
    sync.start_scheduler()
    yield


app = FastAPI(title=APP_NAME, version=VERSION, docs_url=None, redoc_url=None, lifespan=lifespan)


# ---------- autenticación ----------
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "modo-guerrero"
PUBLIC_API = ("/api/auth/",)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@app.middleware("http")
async def session_auth(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        # Protección CSRF: un formulario de otra web no puede añadir esta cabecera
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return JSONResponse({"detail": "Petición no permitida"}, status_code=403)
        user = auth.session_user(request.cookies.get(auth.COOKIE))
        request.state.user = user
        if not user and not path.startswith(PUBLIC_API):
            return JSONResponse({"detail": "Inicia sesión", "auth": True}, status_code=401)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    # los mapas de OpenStreetMap exigen la cabecera Referer
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def _set_cookie(request: Request, resp: Response, token: str, max_age):
    resp.set_cookie(auth.COOKIE, token, max_age=max_age, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https", path="/")


def _start_session(request: Request, user_id: int, remember: bool) -> JSONResponse:
    token, max_age = auth.new_session(user_id, remember, request.headers.get("user-agent", ""), _client_ip(request))
    u = db.one("SELECT id, username, is_admin FROM users WHERE id=?", (user_id,))
    resp = JSONResponse({"ok": True, "user": {"username": u["username"], "is_admin": bool(u["is_admin"])}})
    _set_cookie(request, resp, token, max_age)
    return resp


@app.get("/api/auth/me")
def auth_me(request: Request):
    u = request.state.user
    return {"setup_required": auth.user_count() == 0,
            "user": {"username": u["username"], "is_admin": u["is_admin"]} if u else None,
            "version": VERSION}


@app.post("/api/auth/setup")
def auth_setup(request: Request, payload: dict = Body(...)):
    try:
        uid = auth.setup_first_user(payload.get("username", ""), payload.get("password", ""))
    except auth.AuthFailed as e:
        raise HTTPException(400, str(e))
    return _start_session(request, uid, bool(payload.get("remember", True)))


@app.post("/api/auth/login")
def auth_login(request: Request, payload: dict = Body(...)):
    try:
        u = auth.login(payload.get("username", ""), payload.get("password", ""), _client_ip(request))
    except auth.AuthFailed as e:
        raise HTTPException(401, str(e))
    return _start_session(request, u["id"], bool(payload.get("remember", False)))


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    auth.end_session(request.cookies.get(auth.COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.post("/api/account/password")
def account_password(request: Request, payload: dict = Body(...)):
    u = request.state.user
    try:
        auth.change_password(u["id"], payload.get("current", ""), payload.get("new", ""), u["token_hash"])
    except auth.AuthFailed as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/account/sessions")
def account_sessions(request: Request):
    u = request.state.user
    return auth.list_sessions(u["id"], u["token_hash"])


@app.delete("/api/account/sessions/{sid}")
def account_revoke(request: Request, sid: str):
    auth.revoke_session(request.state.user["id"], sid)
    return {"ok": True}


@app.post("/api/account/sessions/revoke-others")
def account_revoke_others(request: Request):
    u = request.state.user
    auth.revoke_others(u["id"], u["token_hash"])
    return {"ok": True}


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

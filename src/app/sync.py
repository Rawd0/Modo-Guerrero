"""Sincronización con Garmin Connect e importación manual de .FIT."""
import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone

from garminconnect import GarminConnectTooManyRequestsError

from . import db, fitparse, garmin_auth, metrics
from .config import GARMIN_PAUSE

log = logging.getLogger("guerrero.sync")

state = {
    "running": False,
    "phase": "",
    "last_start": None,
    "last_end": None,
    "last_ok": None,
    "last_error": None,
    "next_run": None,
}
_trigger = threading.Event()
_run_lock = threading.Lock()


# ---------- utilidades ----------
def find_key(obj, key):
    """Busca la primera aparición de `key` en un JSON anidado."""
    if isinstance(obj, dict):
        if key in obj and obj[key] is not None:
            return obj[key]
        for v in obj.values():
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, key)
            if r is not None:
                return r
    return None


def is_run_type(type_key: str) -> bool:
    t = (type_key or "").lower()
    return "run" in t and "rowing" not in t


def _pause():
    time.sleep(GARMIN_PAUSE)


def _call(fn, *args, **kwargs):
    """Llama a Garmin; un error puntual en un dato no debe tumbar toda la sync."""
    try:
        r = fn(*args, **kwargs)
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:  # noqa: BLE001
        log.info("%s falló: %s", getattr(fn, "__name__", fn), e)
        r = None
    _pause()
    return r


# ---------- mapeo de actividades ----------
def map_activity(a: dict) -> dict:
    tkey = (a.get("activityType") or {}).get("typeKey", "")
    start_local = a.get("startTimeLocal")
    cad = a.get("averageRunningCadenceInStepsPerMinute")
    return {
        "id": int(a["activityId"]),
        "name": a.get("activityName") or tkey,
        "sport": tkey,
        "is_run": 1 if is_run_type(tkey) else 0,
        "start_local": start_local,
        "start_utc": a.get("startTimeGMT"),
        "date": start_local[:10] if start_local else None,
        "distance_m": a.get("distance"),
        "duration_s": a.get("elapsedDuration") or a.get("duration"),
        "moving_s": a.get("movingDuration") or a.get("duration"),
        "avg_speed": a.get("averageSpeed"),
        "max_speed": a.get("maxSpeed"),
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "calories": a.get("calories"),
        "elev_gain": a.get("elevationGain"),
        "elev_loss": a.get("elevationLoss"),
        "cadence": cad,
        "aerobic_te": a.get("aerobicTrainingEffect"),
        "anaerobic_te": a.get("anaerobicTrainingEffect"),
        "training_load": a.get("activityTrainingLoad"),
        "vo2max": a.get("vO2MaxValue"),
        "start_lat": a.get("startLatitude"),
        "start_lon": a.get("startLongitude"),
        "source": "garmin",
        "raw": json.dumps(a),
    }


def save_activity(row: dict):
    existing = db.one("SELECT fit_status FROM activities WHERE id=?", (row["id"],))
    if existing:
        row = dict(row)
        row.pop("fit_status", None)  # no reiniciar el estado del FIT
    db.upsert("activities", row, "id")
    if not existing:
        _merge_manual_duplicate(row)


def _merge_manual_duplicate(row):
    """Si esta carrera se importó antes a mano desde un .FIT, pasa su detalle a la de Garmin."""
    if not row.get("start_utc"):
        return
    try:
        start = datetime.strptime(row["start_utc"][:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return
    lo = (start - timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")
    hi = (start + timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")
    dup = db.one("SELECT id FROM activities WHERE source='fit' AND start_utc BETWEEN ? AND ?", (lo, hi))
    if not dup:
        return
    with db.tx() as con:
        con.execute("UPDATE streams SET activity_id=? WHERE activity_id=?", (row["id"], dup["id"]))
        con.execute("UPDATE best_efforts SET activity_id=? WHERE activity_id=?", (row["id"], dup["id"]))
        con.execute("UPDATE activities SET fit_status='ok' WHERE id=?", (row["id"],))
        con.execute("DELETE FROM activities WHERE id=?", (dup["id"],))


# ---------- fases de la sincronización ----------
def sync_activities(g):
    state["phase"] = "Actividades"
    known = {r["id"] for r in db.rows("SELECT id FROM activities WHERE source='garmin'")}
    first_run = not known
    start, page = 0, 100
    new = 0
    while True:
        batch = g.get_activities(start, page)
        _pause()
        if not batch:
            break
        page_new = 0
        for a in batch:
            row = map_activity(a)
            if row["id"] not in known:
                page_new += 1
                new += 1
            save_activity(row)
        state["phase"] = f"Actividades ({new} nuevas)"
        # en sincronizaciones normales paramos al llegar a actividades ya conocidas
        if not first_run and page_new == 0:
            break
        if len(batch) < page:
            break
        start += page
    return new


def health_row(day: str, summary, sleep, hrv, readiness) -> dict:
    dto = (sleep or {}).get("dailySleepDTO") or {}
    scores = dto.get("sleepScores") or {}
    hs = (hrv or {}).get("hrvSummary") or {}
    base = hs.get("baseline") or {}
    rd = readiness[0] if isinstance(readiness, list) and readiness else (readiness or {})
    s = summary or {}
    return {
        "date": day,
        "sleep_s": dto.get("sleepTimeSeconds"),
        "sleep_score": (scores.get("overall") or {}).get("value"),
        "deep_s": dto.get("deepSleepSeconds"),
        "rem_s": dto.get("remSleepSeconds"),
        "light_s": dto.get("lightSleepSeconds"),
        "awake_s": dto.get("awakeSleepSeconds"),
        "hrv_night": hs.get("lastNightAvg"),
        "hrv_weekly": hs.get("weeklyAvg"),
        "hrv_status": hs.get("status"),
        "hrv_low": base.get("balancedLow"),
        "hrv_high": base.get("balancedUpper"),
        "rhr": s.get("restingHeartRate"),
        "bb_high": s.get("bodyBatteryHighestValue"),
        "bb_low": s.get("bodyBatteryLowestValue"),
        "bb_last": s.get("bodyBatteryMostRecentValue"),
        "stress_avg": s.get("averageStressLevel") if (s.get("averageStressLevel") or -1) >= 0 else None,
        "steps": s.get("totalSteps"),
        "readiness": rd.get("score") if isinstance(rd, dict) else None,
        "readiness_level": rd.get("level") if isinstance(rd, dict) else None,
        "raw": json.dumps({"summary": summary, "sleep": sleep, "hrv": hrv, "readiness": readiness}),
    }


def sync_health(g):
    last = db.one("SELECT MAX(date) d FROM daily_health")
    today = date.today()
    if last and last["d"]:
        # repetimos los 2 últimos días: el sueño y el Body Battery se completan después
        start = date.fromisoformat(last["d"]) - timedelta(days=1)
    else:
        start = today - timedelta(days=int(db.get_setting("health_backfill_days")) - 1)
    days = (today - start).days + 1
    for i in range(days):
        day = (start + timedelta(days=i)).isoformat()
        state["phase"] = f"Salud {i + 1}/{days} ({day})"
        summary = _call(g.get_user_summary, day)
        sleep = _call(g.get_sleep_data, day)
        hrv = _call(g.get_hrv_data, day)
        readiness = _call(g.get_training_readiness, day)
        db.upsert("daily_health", health_row(day, summary, sleep, hrv, readiness), "date")
    return days


def sync_snapshot(g):
    state["phase"] = "Estado de forma"
    day = date.today().isoformat()
    ts = _call(g.get_training_status, day) or {}
    mm = _call(g.get_max_metrics_latest, day) or {}
    rp = _call(g.get_race_predictions) or {}
    if isinstance(rp, list):
        rp = rp[0] if rp else {}
    vo2 = find_key(mm, "vo2MaxPreciseValue") or find_key(mm, "vo2MaxValue") \
        or find_key(ts, "vo2MaxPreciseValue") or find_key(ts, "vo2MaxValue")
    acute = find_key(ts, "acuteTrainingLoadDTO") or {}
    row = {
        "date": day,
        "vo2max": vo2,
        "training_status": find_key(ts, "trainingStatus"),
        "status_phrase": find_key(ts, "trainingStatusFeedbackPhrase"),
        "acute_load": acute.get("dailyTrainingLoadAcute") if isinstance(acute, dict) else None,
        "chronic_load": acute.get("dailyTrainingLoadChronic") if isinstance(acute, dict) else None,
        "acwr": acute.get("dailyAcuteChronicWorkloadRatio") if isinstance(acute, dict) else None,
        "race_5k": rp.get("time5K"),
        "race_10k": rp.get("time10K"),
        "race_hm": rp.get("timeHalfMarathon"),
        "race_m": rp.get("timeMarathon"),
        "raw": json.dumps({"training_status": ts, "max_metrics": mm, "race_predictions": rp}),
    }
    if any(row[k] is not None for k in ("vo2max", "training_status", "race_5k")):
        db.upsert("snapshots", row, "date")


def store_stream(activity_id, stream):
    db.save_stream(activity_id, stream)
    metrics.store_best_efforts(activity_id, stream)


def sync_fit_files(g):
    limit = int(db.get_setting("fit_per_run"))
    pending = db.rows("SELECT id FROM activities WHERE is_run=1 AND fit_status='pending' "
                      "AND source='garmin' ORDER BY date DESC LIMIT ?", (limit,))
    done = 0
    for i, r in enumerate(pending):
        state["phase"] = f"Detalle de carreras {i + 1}/{len(pending)}"
        try:
            blob = g.download_activity(r["id"], dl_fmt=g.ActivityDownloadFormat.ORIGINAL)
            fits = fitparse.extract_fit_bytes(blob)
            if not fits:
                raise ValueError("sin .fit")
            parsed = fitparse.parse_fit(fits[0])
            store_stream(r["id"], parsed["stream"])
            db.execute("UPDATE activities SET fit_status='ok' WHERE id=?", (r["id"],))
            done += 1
        except GarminConnectTooManyRequestsError:
            raise
        except Exception as e:  # noqa: BLE001
            log.info("FIT %s falló: %s", r["id"], e)
            db.execute("UPDATE activities SET fit_status='error' WHERE id=?", (r["id"],))
        _pause()
    return done


# ---------- orquestación ----------
def run_sync():
    if not _run_lock.acquire(blocking=False):
        return
    state.update(running=True, last_start=_now(), last_error=None, phase="Conectando")
    log_id = None
    with db.tx() as con:
        cur = con.execute("INSERT INTO sync_log (started, status) VALUES (?, 'running')", (state["last_start"],))
        log_id = cur.lastrowid
    msg, status = "", "ok"
    try:
        g = garmin_auth.get_client()
        new = sync_activities(g)
        days = sync_health(g)
        sync_snapshot(g)
        fits = sync_fit_files(g)
        garmin_auth.persist_refreshed(g)
        msg = f"{new} actividades nuevas, {days} días de salud, {fits} detalles descargados"
        state["last_ok"] = _now()
    except garmin_auth.AuthError as e:
        status, msg = "auth", str(e)
    except GarminConnectTooManyRequestsError:
        status, msg = "rate", "Garmin limita las peticiones; se reintentará en la próxima sincronización."
    except Exception as e:  # noqa: BLE001
        log.exception("Sync falló")
        status, msg = "error", f"Error: {e}"
    finally:
        state.update(running=False, phase="", last_end=_now())
        if status != "ok":
            state["last_error"] = msg
        db.execute("UPDATE sync_log SET finished=?, status=?, message=? WHERE id=?",
                   (state["last_end"], status, msg, log_id))
        _run_lock.release()


def trigger():
    _trigger.set()


def scheduler_loop():
    """Hilo en segundo plano: sincroniza cada `sync_interval_min` minutos."""
    time.sleep(5)
    while True:
        interval = max(15, int(db.get_setting("sync_interval_min") or 60))
        if garmin_auth.is_connected():
            run_sync()
        nxt = datetime.now() + timedelta(minutes=interval)
        state["next_run"] = nxt.isoformat(timespec="minutes")
        _trigger.wait(timeout=interval * 60)
        _trigger.clear()


def start_scheduler():
    threading.Thread(target=scheduler_loop, daemon=True, name="sync").start()


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ---------- importación manual de .FIT ----------
def import_fit(blob: bytes) -> list[dict]:
    results = []
    for data in fitparse.extract_fit_bytes(blob):
        parsed = fitparse.parse_fit(data)
        s = parsed["session"]
        if not s.get("start_utc"):
            results.append({"ok": False, "error": "El archivo no contiene una sesión válida"})
            continue
        # ¿Ya existe en Garmin? (mismo inicio ±60 s) → sólo añadimos el detalle
        start = datetime.strptime(s["start_utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        lo = (start - timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")
        hi = (start + timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")
        match = db.one("SELECT id FROM activities WHERE start_utc BETWEEN ? AND ?", (lo, hi))
        if match:
            aid = match["id"]
        else:
            aid = -int(start.timestamp())
            local = start.astimezone()
            sport = s["sport"].lower()
            sub = s["sub_sport"].lower()
            tkey = "running" if sport == "running" else sport
            if sport == "running" and sub in ("treadmill", "trail", "track"):
                tkey = f"{sub}_running"
            db.upsert("activities", {
                "id": aid, "name": f"Carrera importada {local:%d/%m/%Y}" if sport == "running" else f"{sport} importado",
                "sport": tkey, "is_run": 1 if sport == "running" else 0,
                "start_local": local.strftime("%Y-%m-%d %H:%M:%S"), "start_utc": s["start_utc"],
                "date": local.strftime("%Y-%m-%d"),
                "avg_speed": s.get("avg_speed") or ((s["distance_m"] / s["moving_s"]) if s.get("distance_m") and s.get("moving_s") else None),
                **{k: s.get(k) for k in ("distance_m", "duration_s", "moving_s", "max_speed",
                                         "avg_hr", "max_hr", "calories", "elev_gain", "elev_loss",
                                         "cadence", "aerobic_te", "anaerobic_te")},
                "start_lat": next((x for x in parsed["stream"]["lat"] if x), None),
                "start_lon": next((x for x in parsed["stream"]["lon"] if x), None),
                "source": "fit", "fit_status": "ok", "raw": None,
            }, "id")
        store_stream(aid, parsed["stream"])
        db.execute("UPDATE activities SET fit_status='ok' WHERE id=?", (aid,))
        results.append({"ok": True, "id": aid, "merged": bool(match)})
    return results

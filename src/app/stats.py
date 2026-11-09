"""Consultas agregadas para la web: inicio, récords, estadísticas, salud."""
from datetime import date, timedelta

from . import db, metrics
from .config import RECORD_DISTANCES

RUN_COLS = ("id, name, sport, date, start_local, distance_m, moving_s, duration_s, avg_speed, "
            "avg_hr, max_hr, elev_gain, cadence, training_load, aerobic_te, anaerobic_te, vo2max, "
            "calories, fit_status, source")


def _totals(d0: date, d1: date):
    r = db.one("SELECT COUNT(*) n, COALESCE(SUM(distance_m),0) dist, COALESCE(SUM(moving_s),0) secs, "
               "COALESCE(SUM(elev_gain),0) elev FROM activities WHERE is_run=1 AND date>=? AND date<?",
               (d0.isoformat(), d1.isoformat()))
    r["pace"] = r["secs"] / (r["dist"] / 1000) if r["dist"] else None
    return r


def records():
    """Mejor marca por distancia + top 5 + progresión histórica del récord."""
    out = []
    for dist, label in RECORD_DISTANCES:
        rows = db.rows(
            "SELECT b.time_s, a.id, a.name, a.date FROM best_efforts b JOIN activities a ON a.id=b.activity_id "
            "WHERE b.distance_m=? ORDER BY b.time_s LIMIT 5", (dist,))
        prog_rows = db.rows(
            "SELECT b.time_s, a.id, a.date FROM best_efforts b JOIN activities a ON a.id=b.activity_id "
            "WHERE b.distance_m=? ORDER BY a.date", (dist,))
        progression, best = [], None
        for p in prog_rows:
            if best is None or p["time_s"] < best:
                best = p["time_s"]
                progression.append(p)
        year = str(date.today().year)
        best_year = db.one(
            "SELECT b.time_s, a.id, a.date FROM best_efforts b JOIN activities a ON a.id=b.activity_id "
            "WHERE b.distance_m=? AND a.date>=? ORDER BY b.time_s LIMIT 1", (dist, f"{year}-01-01"))
        out.append({"distance": dist, "label": label, "top": rows, "progression": progression,
                    "best_year": best_year})
    return out


def latest_health():
    return db.rows("SELECT date, sleep_s, sleep_score, deep_s, rem_s, light_s, awake_s, hrv_night, hrv_weekly, "
                   "hrv_status, hrv_low, hrv_high, rhr, bb_high, bb_low, bb_last, stress_avg, steps, readiness, "
                   "readiness_level FROM daily_health ORDER BY date DESC LIMIT 14")


def latest_snapshot():
    snap = db.one("SELECT date, vo2max, training_status, status_phrase, acute_load, chronic_load, acwr, race_5k, "
                  "race_10k, race_hm, race_m FROM snapshots ORDER BY date DESC LIMIT 1") or {}
    if not snap.get("vo2max"):
        r = db.one("SELECT vo2max, date FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1")
        if r:
            snap["vo2max"] = r["vo2max"]
    return snap


def weekly_series(weeks=12):
    today = date.today()
    ws = metrics.week_start(today)
    out = []
    for i in range(weeks - 1, -1, -1):
        d0 = ws - timedelta(weeks=i)
        t = _totals(d0, d0 + timedelta(days=7))
        out.append({"week": d0.isoformat(), "km": round(t["dist"] / 1000, 1), "runs": t["n"],
                    "secs": t["secs"]})
    return out


def home():
    today = date.today()
    ws = metrics.week_start(today)
    ms = today.replace(day=1)
    ys = today.replace(month=1, day=1)
    # mismo periodo transcurrido de la semana/mes anterior para comparar de forma justa
    elapsed_w = (today - ws).days + 1
    prev_ms = (ms - timedelta(days=1)).replace(day=1)
    prev_ys = ys.replace(year=ys.year - 1)
    last = db.one(f"SELECT {RUN_COLS} FROM activities WHERE is_run=1 ORDER BY start_local DESC LIMIT 1")
    last_track = None
    if last:
        st = db.load_stream(last["id"])
        if st and any(st.get("lat") or []):
            pts = [[la, lo] for la, lo in zip(st["lat"], st["lon"]) if la and lo]
            step = max(1, len(pts) // 400)
            last_track = pts[::step]
    fit = metrics.fitness_series(90)
    return {
        "today": today.isoformat(),
        "week": {
            "current": _totals(ws, today + timedelta(days=1)),
            "previous_same": _totals(ws - timedelta(days=7), ws - timedelta(days=7) + timedelta(days=elapsed_w)),
            "previous": _totals(ws - timedelta(days=7), ws),
            "goal_km": db.get_setting("weekly_goal_km"),
        },
        "month": {
            "current": _totals(ms, today + timedelta(days=1)),
            "previous_same": _totals(prev_ms, min(prev_ms + (today - ms) + timedelta(days=1), ms)),
            "goal_km": db.get_setting("monthly_goal_km"),
            "year": _totals(ys, today + timedelta(days=1)),
            "prev_year_same": _totals(prev_ys, prev_ys + (today - ys) + timedelta(days=1)),
            "yearly_goal_km": db.get_setting("yearly_goal_km"),
        },
        "weeks": weekly_series(12),
        "fitness": fit,
        "snapshot": latest_snapshot(),
        "health": latest_health(),
        "last": last,
        "last_track": last_track,
        "records": [{"label": r["label"], "distance": r["distance"], "best": r["top"][0] if r["top"] else None,
                     "best_year": r["best_year"]} for r in records()],
    }


def stats(group="month"):
    fmt = {"week": None, "month": "%Y-%m", "year": "%Y"}[group]
    if group == "week":
        rows = db.rows("SELECT date, distance_m, moving_s, elev_gain, avg_hr FROM activities WHERE is_run=1 ORDER BY date")
        buckets = {}
        for r in rows:
            k = metrics.week_start(date.fromisoformat(r["date"])).isoformat()
            b = buckets.setdefault(k, {"period": k, "n": 0, "dist": 0, "secs": 0, "elev": 0, "longest": 0})
            b["n"] += 1
            b["dist"] += r["distance_m"] or 0
            b["secs"] += r["moving_s"] or 0
            b["elev"] += r["elev_gain"] or 0
            b["longest"] = max(b["longest"], r["distance_m"] or 0)
        out = list(buckets.values())
    else:
        out = db.rows(
            f"SELECT strftime('{fmt}', date) period, COUNT(*) n, SUM(distance_m) dist, SUM(moving_s) secs, "
            "SUM(elev_gain) elev, MAX(distance_m) longest FROM activities WHERE is_run=1 GROUP BY period ORDER BY period")
    for b in out:
        b["pace"] = b["secs"] / (b["dist"] / 1000) if b["dist"] else None
    totals = db.one("SELECT COUNT(*) n, SUM(distance_m) dist, SUM(moving_s) secs, SUM(elev_gain) elev, "
                    "MIN(date) first FROM activities WHERE is_run=1")
    by_sport = db.rows("SELECT sport, COUNT(*) n, SUM(distance_m) dist FROM activities WHERE is_run=1 GROUP BY sport ORDER BY n DESC")
    # distribución de distancias
    dist_hist = db.rows(
        "SELECT CASE WHEN distance_m<5000 THEN '<5 km' WHEN distance_m<10000 THEN '5-10 km' "
        "WHEN distance_m<15000 THEN '10-15 km' WHEN distance_m<21000 THEN '15-21 km' ELSE '21+ km' END bucket, "
        "COUNT(*) n FROM activities WHERE is_run=1 GROUP BY bucket")
    weekday = db.rows("SELECT CAST(strftime('%w', date) AS INT) wd, COUNT(*) n, SUM(distance_m) dist "
                      "FROM activities WHERE is_run=1 GROUP BY wd")
    return {"periods": out, "totals": totals, "by_sport": by_sport, "dist_hist": dist_hist, "weekday": weekday}


def health(days=90):
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    return db.rows("SELECT date, sleep_s, sleep_score, deep_s, rem_s, light_s, awake_s, hrv_night, hrv_weekly, "
                   "hrv_status, hrv_low, hrv_high, rhr, bb_high, bb_low, bb_last, stress_avg, steps, readiness, "
                   "readiness_level FROM daily_health WHERE date>=? ORDER BY date", (since,))

"""Comparar dos periodos lado a lado (por ejemplo, esta preparación frente a la anterior)."""
from datetime import date, timedelta

from . import db, metrics, races
from .config import RECORD_DISTANCES

MAX_DAYS = 3 * 366


class CompareError(Exception):
    pass


def _parse(a, b):
    try:
        d1, d2 = date.fromisoformat(a), date.fromisoformat(b)
    except (TypeError, ValueError):
        raise CompareError("Fechas no válidas")
    if d2 < d1:
        d1, d2 = d2, d1
    if (d2 - d1).days > MAX_DAYS:
        raise CompareError("Cada periodo puede tener como mucho 3 años")
    return d1, d2


def period(uid: int, start: date, end: date, fitness: dict) -> dict:
    s, e = start.isoformat(), end.isoformat()
    days = (end - start).days + 1
    runs = db.rows("SELECT id, date, distance_m, moving_s, elev_gain, avg_hr, gap_pace FROM activities "
                   "WHERE user_id=? AND is_run=1 AND date BETWEEN ? AND ? ORDER BY date", (uid, s, e))
    dist = sum(r["distance_m"] or 0 for r in runs)
    secs = sum(r["moving_s"] or 0 for r in runs)
    hr_runs = [r for r in runs if r["avg_hr"] and r["moving_s"]]
    hr_secs = sum(r["moving_s"] for r in hr_runs)
    avg_hr = sum(r["avg_hr"] * r["moving_s"] for r in hr_runs) / hr_secs if hr_secs else None
    gap_runs = [r for r in runs if r["gap_pace"] and r["distance_m"]]
    gap_dist = sum(r["distance_m"] for r in gap_runs)
    gap = sum(r["gap_pace"] * r["distance_m"] for r in gap_runs) / gap_dist if gap_dist else None
    # eficiencia aeróbica: metros por minuto por pulsación (más alto = mejor)
    hr_dist = sum(r["distance_m"] or 0 for r in hr_runs)
    efficiency = (hr_dist / (hr_secs / 60)) / avg_hr if hr_secs and avg_hr else None

    # kilómetros acumulados día a día y por semana
    by_day = {}
    for r in runs:
        by_day[r["date"]] = by_day.get(r["date"], 0) + (r["distance_m"] or 0) / 1000
    cum, acc = [], 0.0
    for i in range(days):
        acc += by_day.get((start + timedelta(days=i)).isoformat(), 0)
        cum.append(round(acc, 1))
    weeks = [round(sum(by_day.get((start + timedelta(days=i)).isoformat(), 0)
                       for i in range(w * 7, min(days, w * 7 + 7))), 1) for w in range((days + 6) // 7)]

    # mejores marcas dentro del periodo y VDOT
    best = []
    vdot_best = None
    for d_m, label in RECORD_DISTANCES:
        r = db.one("SELECT MIN(b.time_s) t FROM best_efforts b JOIN activities a ON a.id=b.activity_id "
                   "WHERE a.user_id=? AND b.distance_m=? AND a.date BETWEEN ? AND ?", (uid, d_m, s, e))
        t = r["t"] if r else None
        best.append({"distance_m": d_m, "label": label, "time_s": t})
        if t and d_m >= 3000:
            v = races.vdot(d_m, t)
            vdot_best = max(vdot_best or 0, v)

    health = db.one("SELECT AVG(sleep_score) sleep, AVG(sleep_s) sleep_s, AVG(hrv_night) hrv, AVG(rhr) rhr, "
                    "AVG(stress_avg) stress, COUNT(*) n FROM daily_health WHERE user_id=? AND date BETWEEN ? AND ?",
                    (uid, s, e))
    return {
        "from": s, "to": e, "days": days,
        "runs": len(runs), "km": round(dist / 1000, 1), "secs": round(secs), "elev": round(sum(r["elev_gain"] or 0 for r in runs)),
        "km_week": round(dist / 1000 / (days / 7), 1), "runs_week": round(len(runs) / (days / 7), 1),
        "pace": round(secs / (dist / 1000), 1) if dist else None, "gap": round(gap, 1) if gap else None,
        "avg_hr": round(avg_hr) if avg_hr else None, "efficiency": round(efficiency, 3) if efficiency else None,
        "longest_km": round(max((r["distance_m"] or 0 for r in runs), default=0) / 1000, 1),
        "ctl_end": fitness.get(e, {}).get("ctl"), "ctl_start": fitness.get(s, {}).get("ctl"),
        "vdot": round(vdot_best, 1) if vdot_best else None, "best": best,
        "sleep_score": round(health["sleep"]) if health and health["sleep"] else None,
        "sleep_h": round(health["sleep_s"] / 3600, 1) if health and health["sleep_s"] else None,
        "hrv": round(health["hrv"]) if health and health["hrv"] else None,
        "rhr": round(health["rhr"], 1) if health and health["rhr"] else None,
        "stress": round(health["stress"]) if health and health["stress"] else None,
        "cum_km": cum, "weeks_km": weeks,
    }


def compare(uid: int, a_from, a_to, b_from, b_to) -> dict:
    a1, a2 = _parse(a_from, a_to)
    b1, b2 = _parse(b_from, b_to)
    first = min(a1, b1)
    fit = {x["date"]: x for x in metrics.fitness_series(uid, days=(date.today() - first).days + 2)}
    return {"a": period(uid, a1, a2, fit), "b": period(uid, b1, b2, fit)}


def presets(uid: int) -> list:
    """Comparaciones típicas listas para usar, incluidas las preparaciones de tus carreras objetivo."""
    t = date.today()
    out = []

    def add(key, label, a, b):
        out.append({"key": key, "label": label, "a": [a[0].isoformat(), a[1].isoformat()],
                    "b": [b[0].isoformat(), b[1].isoformat()]})

    add("4w", "Últimas 4 semanas frente a las 4 anteriores", (t - timedelta(days=27), t), (t - timedelta(days=55), t - timedelta(days=28)))
    add("12w", "Últimas 12 semanas frente a las 12 anteriores", (t - timedelta(days=83), t), (t - timedelta(days=167), t - timedelta(days=84)))
    m1 = t.replace(day=1)
    try:
        ly = t.replace(year=t.year - 1)
    except ValueError:
        ly = t.replace(year=t.year - 1, day=28)
    add("month", "Este mes frente al mismo mes del año pasado", (m1, t), (m1.replace(year=t.year - 1), ly))
    add("ytd", "Este año frente al año pasado (hasta hoy)", (t.replace(month=1, day=1), t), (date(t.year - 1, 1, 1), ly))
    # preparaciones: las 12 semanas antes de cada carrera objetivo (la más reciente frente a la anterior)
    rs = db.rows("SELECT name, date FROM races WHERE user_id=? ORDER BY date DESC LIMIT 6", (uid,))
    for i in range(len(rs) - 1):
        a, b = rs[i], rs[i + 1]
        ad, bd = date.fromisoformat(a["date"]), date.fromisoformat(b["date"])
        add(f"race{i}", f"Preparación de «{a['name']}» frente a «{b['name']}» (12 semanas)",
            (ad - timedelta(days=83), min(ad, t)), (bd - timedelta(days=83), bd))
    return out

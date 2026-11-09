"""Objetivos de carrera: predicción de tiempo, proyección de forma hasta el día y preparación.

Predicciones
- VDOT (Jack Daniels): se calcula tu VDOT con tus mejores tramos recientes y se busca el tiempo
  que corresponde a ese VDOT en la distancia objetivo.
- Riegel: T2 = T1 · (D2/D1)^1,06 a partir del mejor tramo reciente de distancia más parecida.
- Garmin: la predicción del reloj, escalada con Riegel si la distancia no es 5K/10K/media/maratón.
Los tramos salen de entrenamientos, no sólo de carreras: si no has corrido a tope, la predicción
tiende a ser conservadora.
"""
import math
from datetime import date, datetime, timedelta

from . import db, metrics, stats

PRESET_DISTANCES = {5000: "5 km", 10000: "10 km", 15000: "15 km", 21097.5: "Media maratón", 42195: "Maratón"}
RECENT_DAYS = 90

# orientaciones por distancia (km): tirada larga mínima, volumen semanal mínimo, días de taper
GUIDE = [  # (hasta distancia, long_run_km, weekly_km, taper_days)
    (6000, 8, 20, 5),
    (12000, 12, 30, 7),
    (17000, 15, 35, 9),
    (25000, 18, 40, 10),
    (10 ** 9, 30, 55, 14),
]
TSB_WINDOW = {"A": (5, 15), "B": (0, 10), "C": (-15, 5)}


class RaceError(Exception):
    pass


# ---------- fórmulas ----------
def _vo2(v_m_min):
    return -4.60 + 0.182258 * v_m_min + 0.000104 * v_m_min ** 2


def _pct_max(t_min):
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def vdot(distance_m, time_s):
    t = time_s / 60
    return _vo2(distance_m / t) / _pct_max(t)


def time_for_vdot(v, distance_m):
    """Tiempo (s) que corresponde a un VDOT en una distancia (búsqueda binaria)."""
    lo, hi = 60.0, 60.0 * 900
    for _ in range(80):
        mid = (lo + hi) / 2
        if vdot(distance_m, mid) > v:
            lo = mid  # demasiado rápido para ese VDOT
        else:
            hi = mid
    return (lo + hi) / 2


def riegel(t1, d1, d2, k=1.06):
    return t1 * (d2 / d1) ** k


def guide_for(distance_m):
    for limit, long_km, weekly_km, taper in GUIDE:
        if distance_m <= limit:
            return {"long_run_km": long_km, "weekly_km": weekly_km, "taper_days": taper}


# ---------- datos ----------
def _clean(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if not name or len(name) > 80:
        raise RaceError("Pon un nombre a la carrera (máximo 80 caracteres)")
    try:
        d = datetime.strptime(payload.get("date") or "", "%Y-%m-%d").date()
    except ValueError:
        raise RaceError("Fecha no válida")
    try:
        dist = float(payload.get("distance_m") or 0)
    except (TypeError, ValueError):
        raise RaceError("Distancia no válida")
    if not 1000 <= dist <= 250000:
        raise RaceError("La distancia debe estar entre 1 y 250 km")
    goal = payload.get("goal_time_s")
    if goal in ("", None):
        goal = None
    else:
        try:
            goal = float(goal)
        except (TypeError, ValueError):
            raise RaceError("Tiempo objetivo no válido")
        if not 60 <= goal <= 60 * 60 * 48:
            raise RaceError("Tiempo objetivo no válido")
    prio = payload.get("priority") or "A"
    if prio not in TSB_WINDOW:
        raise RaceError("Prioridad no válida")
    return {"name": name, "date": d.isoformat(), "distance_m": dist, "goal_time_s": goal, "priority": prio,
            "notes": (payload.get("notes") or "").strip()[:500] or None}


def create(uid: int, payload: dict) -> int:
    d = _clean(payload)
    with db.tx() as con:
        cur = con.execute("INSERT INTO races (user_id, name, date, distance_m, goal_time_s, priority, notes, created) "
                          "VALUES (?,?,?,?,?,?,?,?)", (uid, d["name"], d["date"], d["distance_m"], d["goal_time_s"],
                                                      d["priority"], d["notes"], datetime.now().isoformat(timespec="seconds")))
        return cur.lastrowid


def _own(uid: int, race_id: int) -> dict:
    r = db.one("SELECT * FROM races WHERE id=? AND user_id=?", (race_id, uid))
    if not r:
        raise RaceError("Carrera no encontrada")
    return r


def update(uid: int, race_id: int, payload: dict):
    _own(uid, race_id)
    d = _clean(payload)
    db.execute("UPDATE races SET name=?, date=?, distance_m=?, goal_time_s=?, priority=?, notes=?, "
               "result_activity_id=CASE WHEN date<>? OR distance_m<>? THEN NULL ELSE result_activity_id END "
               "WHERE id=? AND user_id=?", (d["name"], d["date"], d["distance_m"], d["goal_time_s"], d["priority"],
                                            d["notes"], d["date"], d["distance_m"], race_id, uid))
    if "result_activity_id" in payload:
        set_result(uid, race_id, payload["result_activity_id"])


def set_result(uid: int, race_id: int, activity_id):
    _own(uid, race_id)
    if activity_id not in (None, ""):
        if not db.one("SELECT 1 FROM activities WHERE id=? AND user_id=?", (int(activity_id), uid)):
            raise RaceError("Actividad no encontrada")
        activity_id = int(activity_id)
    else:
        activity_id = None
    db.execute("UPDATE races SET result_activity_id=?, result_manual=1 WHERE id=? AND user_id=?", (activity_id, race_id, uid))


def delete(uid: int, race_id: int):
    _own(uid, race_id)
    db.execute("DELETE FROM races WHERE id=? AND user_id=?", (race_id, uid))


# ---------- predicciones ----------
def _recent_efforts(uid: int, before: date | None = None):
    end = before or date.today() + timedelta(days=1)
    since = end - timedelta(days=RECENT_DAYS)
    rows = db.rows("SELECT b.distance_m, MIN(b.time_s) time_s FROM best_efforts b JOIN activities a ON a.id=b.activity_id "
                   "WHERE a.user_id=? AND a.date>=? AND a.date<? AND b.distance_m>=1000 GROUP BY b.distance_m",
                   (uid, since.isoformat(), end.isoformat()))
    return rows


def predictions(uid: int, distance_m: float, before: date | None = None) -> dict:
    eff = _recent_efforts(uid, before)
    out = {"vdot": None, "riegel": None, "garmin": None, "vdot_value": None, "based_on": None}
    long_eff = [e for e in eff if e["distance_m"] >= 3000] or eff
    if long_eff:
        best = max(long_eff, key=lambda e: vdot(e["distance_m"], e["time_s"]))
        v = vdot(best["distance_m"], best["time_s"])
        out["vdot_value"] = round(v, 1)
        out["vdot"] = round(time_for_vdot(v, distance_m))
        out["based_on"] = {"distance_m": best["distance_m"], "time_s": best["time_s"]}
        near = min(eff, key=lambda e: abs(math.log(e["distance_m"] / distance_m)))
        out["riegel"] = round(riegel(near["time_s"], near["distance_m"], distance_m))
        out["riegel_from"] = {"distance_m": near["distance_m"], "time_s": near["time_s"]}
    snap = stats.latest_snapshot(uid)
    garmin = [(d, snap.get(k)) for d, k in ((5000, "race_5k"), (10000, "race_10k"), (21097.5, "race_hm"),
                                             (42195, "race_m")) if snap.get(k)]
    if garmin and not before:
        gd, gt = min(garmin, key=lambda x: abs(math.log(x[0] / distance_m)))
        out["garmin"] = round(gt if abs(gd - distance_m) < 1 else riegel(gt, gd, distance_m))
    vals = sorted(out[k] for k in ("vdot", "riegel", "garmin") if out[k])
    # estimación central: la mediana de los métodos disponibles (más justa que la más optimista)
    if not vals:
        out["estimate"] = None
    elif len(vals) % 2:
        out["estimate"] = vals[len(vals) // 2]
    else:
        out["estimate"] = round((vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2)
    out["fastest"] = vals[0] if vals else None
    return out


# ---------- proyección de forma hasta el día ----------
def projection(uid: int, race_day: date, distance_m: float, taper=True):
    """Simula CTL/ATL/TSB hasta la carrera manteniendo tu carga media de las últimas 4 semanas
    y, si `taper`, reduciéndola al 60 % en los días de afinamiento recomendados."""
    hist = metrics.fitness_series(uid, days=60)
    if not hist:
        return None
    today = date.today()
    last = hist[-1]
    ctl, atl = last["ctl"], last["atl"]
    # la serie ya incluye hoy: partimos del final de hoy
    ctl += (last["load"] - ctl) * (1 - math.exp(-1 / 42))
    atl += (last["load"] - atl) * (1 - math.exp(-1 / 7))
    base = sum(x["load"] for x in hist[-28:]) / 28
    taper_days = guide_for(distance_m)["taper_days"]
    kc, ka = 1 - math.exp(-1 / 42), 1 - math.exp(-1 / 7)
    series = []
    d = today + timedelta(days=1)
    while d <= race_day:
        tsb = ctl - atl
        days_left = (race_day - d).days
        if d == race_day:
            load = 0.0
        elif taper and days_left <= taper_days:
            load = base * 0.6
        else:
            load = base
        series.append({"date": d.isoformat(), "ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(tsb, 1),
                       "load": round(load, 1)})
        ctl += (load - ctl) * kc
        atl += (load - atl) * ka
        d += timedelta(days=1)
    return {"series": series, "base_load": round(base, 1), "taper_days": taper_days,
            "race_tsb": series[-1]["tsb"] if series else round(last["tsb"], 1),
            "race_ctl": series[-1]["ctl"] if series else last["ctl"]}


# ---------- preparación ----------
def checklist(uid: int, race: dict, pred: dict, proj: dict | None):
    g = guide_for(race["distance_m"])
    today = date.today()
    since6 = (today - timedelta(weeks=6)).isoformat()
    since4 = (today - timedelta(weeks=4)).isoformat()
    longest = db.one("SELECT MAX(distance_m) m FROM activities WHERE user_id=? AND is_run=1 AND date>=?", (uid, since6))["m"] or 0
    vol = db.one("SELECT COALESCE(SUM(distance_m),0) d, COUNT(*) n FROM activities WHERE user_id=? AND is_run=1 AND date>=?",
                 (uid, since4))
    weekly_km = vol["d"] / 1000 / 4
    runs_week = vol["n"] / 4
    items = [
        {"id": "long", "label": "Tirada larga (últimas 6 semanas)", "value": round(longest / 1000, 1), "target": g["long_run_km"],
         "unit": "km", "ok": longest / 1000 >= g["long_run_km"] * 0.95},
        {"id": "volume", "label": "Volumen semanal medio (4 semanas)", "value": round(weekly_km, 1), "target": g["weekly_km"],
         "unit": "km", "ok": weekly_km >= g["weekly_km"] * 0.9},
        {"id": "freq", "label": "Carreras por semana", "value": round(runs_week, 1), "target": 3, "unit": "", "ok": runs_week >= 2.8},
    ]
    lo, hi = TSB_WINDOW[race["priority"]]
    if proj:
        items.append({"id": "tsb", "label": f"Forma (TSB) prevista el día de la carrera", "value": proj["race_tsb"],
                      "target": f"{lo:+d} a {hi:+d}", "unit": "", "ok": lo <= proj["race_tsb"] <= hi})
    verdict = None
    if race.get("goal_time_s") and pred.get("estimate"):
        diff = (race["goal_time_s"] - pred["estimate"]) / pred["estimate"] * 100
        verdict = {"diff_pct": round(diff, 1),
                   "label": "ambicioso" if diff < -3 else "realista" if diff <= 3 else "conservador"}
    return {"items": items, "guide": g, "tsb_window": [lo, hi], "verdict": verdict}


# ---------- resultado ----------
def auto_link_results(uid: int):
    """Enlaza a cada carrera pasada la actividad de ese día que mejor encaja por distancia."""
    pending = db.rows("SELECT * FROM races WHERE user_id=? AND date<? AND result_activity_id IS NULL "
                      "AND COALESCE(result_manual,0)=0", (uid, date.today().isoformat()))
    for r in pending:
        cands = db.rows("SELECT id, distance_m FROM activities WHERE user_id=? AND is_run=1 AND date=? "
                        "AND distance_m BETWEEN ? AND ?", (uid, r["date"], r["distance_m"] * 0.9, r["distance_m"] * 1.15))
        if cands:
            best = min(cands, key=lambda c: abs(c["distance_m"] - r["distance_m"]))
            db.execute("UPDATE races SET result_activity_id=? WHERE id=?", (best["id"], r["id"]))


def result_for(uid: int, race: dict):
    if not race.get("result_activity_id"):
        return None
    a = db.one("SELECT id, name, date, distance_m, moving_s, duration_s, avg_hr FROM activities WHERE id=? AND user_id=?",
               (race["result_activity_id"], uid))
    if not a:
        return None
    t = None
    be = db.one("SELECT time_s FROM best_efforts WHERE activity_id=? AND ABS(distance_m-?)<1", (a["id"], race["distance_m"]))
    if be:
        t = be["time_s"]
    elif a["distance_m"] and abs(a["distance_m"] - race["distance_m"]) / race["distance_m"] < 0.03:
        t = a["moving_s"]
    elif a["distance_m"]:
        t = a["moving_s"] * race["distance_m"] / a["distance_m"]
    return {"activity": a, "time_s": round(t) if t else None,
            "vs_goal_s": round(t - race["goal_time_s"]) if t and race.get("goal_time_s") else None}


# ---------- vistas ----------
def summary(uid: int, race: dict) -> dict:
    d = date.fromisoformat(race["date"])
    days = (d - date.today()).days
    out = dict(race, days_left=days, label=PRESET_DISTANCES.get(race["distance_m"]),
               goal_pace=race["goal_time_s"] / (race["distance_m"] / 1000) if race.get("goal_time_s") else None)
    if days >= 0:
        out["prediction"] = predictions(uid, race["distance_m"])
    else:
        out["result"] = result_for(uid, race)
        # predicción con los datos que tenías antes de la carrera
        out["prediction"] = predictions(uid, race["distance_m"], before=d)
    return out


def list_races(uid: int):
    auto_link_results(uid)
    rows = db.rows("SELECT * FROM races WHERE user_id=? ORDER BY date", (uid,))
    today = date.today().isoformat()
    upcoming = [summary(uid, r) for r in rows if r["date"] >= today]
    past = [summary(uid, r) for r in reversed(rows) if r["date"] < today]
    return {"upcoming": upcoming, "past": past}


def detail(uid: int, race_id: int):
    auto_link_results(uid)
    r = _own(uid, race_id)
    s = summary(uid, r)
    d = date.fromisoformat(r["date"])
    if s["days_left"] >= 0:
        proj = projection(uid, d, r["distance_m"], taper=r["priority"] != "C")
        s["projection"] = proj
        s["projection_no_taper"] = projection(uid, d, r["distance_m"], taper=False) if r["priority"] != "C" else None
        s["history"] = metrics.fitness_series(uid, days=42)
        s["checklist"] = checklist(uid, r, s["prediction"], proj)
    s["candidates"] = db.rows("SELECT id, name, distance_m, moving_s FROM activities WHERE user_id=? AND is_run=1 AND date=?",
                              (uid, r["date"]))
    return s


def next_race(uid: int):
    r = db.one("SELECT * FROM races WHERE user_id=? AND date>=? ORDER BY date LIMIT 1", (uid, date.today().isoformat()))
    if not r:
        return None
    s = summary(uid, r)
    proj = projection(uid, date.fromisoformat(r["date"]), r["distance_m"], taper=r["priority"] != "C")
    s["race_tsb"] = proj["race_tsb"] if proj else None
    s["tsb_window"] = list(TSB_WINDOW[r["priority"]])
    return s

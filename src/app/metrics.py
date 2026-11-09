"""Cálculos: mejores esfuerzos, parciales, carga (CTL/ATL/TSB), utilidades."""
import math
from datetime import date, timedelta

from . import db
from .config import RECORD_DISTANCES


# ---------- tiempo en movimiento ----------
def active_time(t, d):
    """Tiempo acumulado descontando pausas (huecos largos sin avanzar)."""
    out = [0.0]
    for k in range(1, len(t)):
        dt = t[k] - t[k - 1]
        dd = (d[k] or 0) - (d[k - 1] or 0)
        if dt > 5 and dd / dt < 0.5:
            dt = 0.0
        out.append(out[-1] + max(dt, 0.0))
    return out


# ---------- mejores esfuerzos ----------
def best_efforts(stream: dict) -> dict:
    """Mejor tiempo para cada distancia de RECORD_DISTANCES dentro de una actividad."""
    t, d = stream.get("t") or [], stream.get("d") or []
    if len(t) < 2 or not d or (d[-1] or 0) < 300:
        return {}
    ta = active_time(t, d)
    total = d[-1]
    res = {}
    for dist, _ in RECORD_DISTANCES:
        if total < dist * 0.999:
            continue
        best = math.inf
        i = 0
        n = len(d)
        for j in range(1, n):
            # avanzar i mientras el tramo (i+1, j) siga cubriendo la distancia
            while i + 1 < j and d[j] - d[i + 1] >= dist:
                i += 1
            span = d[j] - d[i]
            if span < dist:
                continue
            # interpolar el punto de inicio exacto entre i e i+1
            target = d[j] - dist
            if i + 1 < n and d[i + 1] > d[i]:
                frac = (target - d[i]) / (d[i + 1] - d[i])
                frac = min(max(frac, 0.0), 1.0)
                t_start = ta[i] + frac * (ta[i + 1] - ta[i])
            else:
                t_start = ta[i]
            el = ta[j] - t_start
            if 0 < el < best:
                best = el
        if best < math.inf:
            # descartar valores físicamente imposibles (GPS loco): > 7 m/s sostenido
            if dist / best <= 7.0:
                res[dist] = round(best, 1)
    return res


def store_best_efforts(activity_id, stream):
    be = best_efforts(stream)
    with db.tx() as con:
        con.execute("DELETE FROM best_efforts WHERE activity_id=?", (activity_id,))
        for dist, ts in be.items():
            con.execute("INSERT INTO best_efforts VALUES (?,?,?)", (activity_id, dist, ts))
    return be


# ---------- parciales por km ----------
def km_splits(stream: dict, split_m=1000):
    t, d = stream.get("t") or [], stream.get("d") or []
    if len(t) < 2:
        return []
    ta = active_time(t, d)
    hr, alt, cad = stream.get("hr") or [], stream.get("alt") or [], stream.get("cad") or []
    splits = []
    next_mark = split_m
    prev_t, prev_i, prev_d = 0.0, 0, 0.0
    for k in range(1, len(d)):
        while d[k] is not None and d[k] >= next_mark:
            # interpolar el instante del cruce
            dd = d[k] - d[k - 1]
            frac = (next_mark - d[k - 1]) / dd if dd > 0 else 1
            tc = ta[k - 1] + frac * (ta[k] - ta[k - 1])
            splits.append(_split(len(splits) + 1, next_mark - prev_d, tc - prev_t,
                                 hr[prev_i:k + 1], alt, cad[prev_i:k + 1], prev_i, k))
            prev_t, prev_i, prev_d = tc, k, next_mark
            next_mark += split_m
    rest = (d[-1] or 0) - prev_d
    if rest > 50:
        splits.append(_split(len(splits) + 1, rest, ta[-1] - prev_t,
                             hr[prev_i:], alt, cad[prev_i:], prev_i, len(d) - 1))
    return splits


def _split(n, dist, secs, hr, alt, cad, i0, i1):
    hrv = [x for x in hr if x]
    cv = [x for x in cad if x]
    a0 = alt[i0] if i0 < len(alt) else None
    a1 = alt[i1] if i1 < len(alt) else None
    return {
        "n": n,
        "dist": round(dist),
        "time": round(secs, 1),
        "pace": round(secs / (dist / 1000), 1) if dist > 0 else None,
        "hr": round(sum(hrv) / len(hrv)) if hrv else None,
        "cad": round(sum(cv) / len(cv)) if cv else None,
        "elev": round(a1 - a0, 1) if a0 is not None and a1 is not None else None,
    }


# ---------- reducción de puntos para la web ----------
def downsample(stream: dict, max_points=1500):
    n = len(stream.get("t") or [])
    if n <= max_points:
        return stream
    step = n / max_points
    idx = [int(i * step) for i in range(max_points)] + [n - 1]
    return {k: [v[i] for i in idx] if isinstance(v, list) and len(v) == n else v
            for k, v in stream.items()}


# ---------- carga de entrenamiento ----------
def activity_load(a, hr_rest, hr_max):
    """Carga Garmin si existe; si no, TRIMP de Banister como alternativa."""
    if a.get("training_load"):
        return a["training_load"]
    mins = (a.get("moving_s") or a.get("duration_s") or 0) / 60
    if a.get("avg_hr") and hr_rest and hr_max and hr_max > hr_rest:
        hrr = (a["avg_hr"] - hr_rest) / (hr_max - hr_rest)
        hrr = min(max(hrr, 0), 1)
        return mins * hrr * 0.64 * math.exp(1.92 * hrr)
    return 0.0


def hr_bounds():
    hr_max = db.get_setting("hr_max")
    hr_rest = db.get_setting("hr_rest")
    if not hr_max:
        r = db.one("SELECT MAX(max_hr) m FROM activities WHERE is_run=1")
        hr_max = r["m"] if r and r["m"] else 190
    if not hr_rest:
        r = db.one("SELECT AVG(rhr) m FROM (SELECT rhr FROM daily_health WHERE rhr IS NOT NULL ORDER BY date DESC LIMIT 30)")
        hr_rest = r["m"] if r and r["m"] else 55
    return hr_rest, hr_max


def fitness_series(days=180):
    """Serie diaria de carga, CTL (42 d), ATL (7 d) y TSB, usando todas las actividades."""
    acts = db.rows("SELECT date, training_load, moving_s, duration_s, avg_hr FROM activities WHERE date IS NOT NULL ORDER BY date")
    if not acts:
        return []
    hr_rest, hr_max = hr_bounds()
    daily = {}
    for a in acts:
        daily[a["date"]] = daily.get(a["date"], 0) + activity_load(a, hr_rest, hr_max)
    start = date.fromisoformat(acts[0]["date"])
    end = date.today()
    ctl = atl = 0.0
    kc, ka = 1 - math.exp(-1 / 42), 1 - math.exp(-1 / 7)
    out = []
    d = start
    while d <= end:
        load = daily.get(d.isoformat(), 0.0)
        tsb = ctl - atl  # forma de la mañana, antes del entreno del día
        ctl += (load - ctl) * kc
        atl += (load - atl) * ka
        out.append({"date": d.isoformat(), "load": round(load, 1), "ctl": round(ctl, 1),
                    "atl": round(atl, 1), "tsb": round(tsb, 1)})
        d += timedelta(days=1)
    return out[-days:]


# ---------- utilidades ----------
def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())

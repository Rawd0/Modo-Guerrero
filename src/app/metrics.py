"""Cálculos: mejores esfuerzos, curva de ritmo, ritmo ajustado a la pendiente (GAP), parciales,
carga (CTL/ATL/TSB), monotonía y tensión, utilidades."""
import math
from datetime import date, timedelta

from . import db
from .config import PACE_CURVE_DURATIONS, RECORD_DISTANCES

DERIVED_VERSION = 1  # súbelo si cambian los cálculos guardados por actividad (GAP, curva de ritmo)


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


# ---------- ritmo ajustado a la pendiente (GAP) ----------
def minetti_cost(grade: float) -> float:
    """Coste energético de correr (J/kg/m) según la pendiente (Minetti et al., 2002)."""
    g = min(max(grade, -0.45), 0.45)
    return 155.4 * g ** 5 - 30.4 * g ** 4 - 43.3 * g ** 3 + 46.3 * g ** 2 + 19.5 * g + 3.6


_FLAT = minetti_cost(0.0)
DOWNHILL_BENEFIT = 0.5


def _smooth(values, w):
    """Media móvil centrada que ignora huecos (None)."""
    out, n = [], len(values)
    for i in range(n):
        win = [v for v in values[max(0, i - w):i + w + 1] if v is not None]
        out.append(sum(win) / len(win) if win else None)
    return out


def grade_factors(stream: dict, window_m=60):
    """Factor de esfuerzo de cada punto respecto al llano (1 = llano, >1 = cuesta arriba).

    Devuelve None si la actividad no tiene altitud útil (cinta, interior).
    """
    d, alt = stream.get("d") or [], stream.get("alt") or []
    if len(d) < 3 or sum(1 for a in alt if a is not None) < len(alt) * 0.5:
        return None
    if max(a for a in alt if a is not None) - min(a for a in alt if a is not None) < 3:
        return [1.0] * len(d)  # prácticamente llano
    alt_s = _smooth(alt, 7)
    n = len(d)
    factors = [1.0] * n
    lo = hi = 0
    for k in range(n):
        # tramo de ±window/2 metros alrededor del punto
        while lo < k and d[k] - d[lo] > window_m / 2:
            lo += 1
        while hi < n - 1 and d[hi] - d[k] < window_m / 2:
            hi += 1
        span = d[hi] - d[lo]
        if span >= 10 and alt_s[hi] is not None and alt_s[lo] is not None:
            f = minetti_cost((alt_s[hi] - alt_s[lo]) / span) / _FLAT
            # En bajada, Minetti (medido en cinta) sobrestima el ahorro; con datos reales de corredores
            # el beneficio es aproximadamente la mitad, así que lo reducimos.
            factors[k] = f if f >= 1 else 1 - (1 - f) * DOWNHILL_BENEFIT
    return factors


def equivalent_distance(stream: dict, factors=None):
    """Distancia equivalente en llano acumulada en cada punto."""
    d = stream.get("d") or []
    factors = factors if factors is not None else grade_factors(stream)
    if factors is None:
        return None
    out = [0.0]
    for k in range(1, len(d)):
        out.append(out[-1] + max((d[k] or 0) - (d[k - 1] or 0), 0) * factors[k])
    return out


def gap_pace(stream: dict):
    """Ritmo ajustado a la pendiente de toda la actividad (s/km) o None."""
    t, d = stream.get("t") or [], stream.get("d") or []
    deq = equivalent_distance(stream)
    if not deq or deq[-1] < 200:
        return None
    ta = active_time(t, d)
    return round(ta[-1] / (deq[-1] / 1000), 1)


# ---------- curva de ritmo ----------
def best_durations(stream: dict) -> dict:
    """Máxima distancia recorrida en cada duración de PACE_CURVE_DURATIONS (en movimiento)."""
    t, d = stream.get("t") or [], stream.get("d") or []
    if len(t) < 2:
        return {}
    ta = active_time(t, d)
    total_t = ta[-1]
    res = {}
    n = len(ta)
    for dur in PACE_CURVE_DURATIONS:
        if total_t < dur * 0.999:
            continue
        best = 0.0
        i = 0
        for j in range(1, n):
            while i + 1 < j and ta[j] - ta[i + 1] >= dur:
                i += 1
            if ta[j] - ta[i] < dur:
                continue
            # interpolar la distancia en el instante exacto de inicio
            t0 = ta[j] - dur
            if ta[i + 1] > ta[i]:
                frac = min(max((t0 - ta[i]) / (ta[i + 1] - ta[i]), 0.0), 1.0)
                d0 = d[i] + frac * (d[i + 1] - d[i])
            else:
                d0 = d[i]
            best = max(best, d[j] - d0)
        # descartar valores imposibles (GPS loco)
        if best > 0 and best / dur <= (9.5 if dur <= 60 else 7.0):
            res[dur] = round(best, 1)
    return res


def store_derived(activity_id, stream):
    """Guarda los cálculos por actividad: mejores esfuerzos, curva de ritmo y GAP."""
    be = best_efforts(stream)
    bd = best_durations(stream)
    gp = gap_pace(stream)
    with db.tx() as con:
        con.execute("DELETE FROM best_efforts WHERE activity_id=?", (activity_id,))
        for dist, ts in be.items():
            con.execute("INSERT INTO best_efforts VALUES (?,?,?)", (activity_id, dist, ts))
        con.execute("DELETE FROM best_durations WHERE activity_id=?", (activity_id,))
        for dur, dist in bd.items():
            con.execute("INSERT INTO best_durations VALUES (?,?,?)", (activity_id, dur, dist))
        con.execute("UPDATE activities SET gap_pace=?, derived_v=? WHERE id=?", (gp, DERIVED_VERSION, activity_id))
    from . import routes  # ruta repetida (necesita el GPS del registro)
    try:
        routes.assign(activity_id, stream)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("guerrero.routes").exception("Asignando ruta a %s", activity_id)
    return be


def backfill_derived(limit=None):
    """Recalcula lo derivado en las carreras guardadas con una versión antigua de los cálculos."""
    pending = db.rows("SELECT a.id FROM activities a JOIN streams s ON s.activity_id=a.id "
                      "WHERE a.is_run=1 AND COALESCE(a.derived_v,0) < ? ORDER BY a.date DESC"
                      + (f" LIMIT {int(limit)}" if limit else ""), (DERIVED_VERSION,))
    for r in pending:
        st = db.load_stream(r["id"])
        if st:
            store_derived(r["id"], st)
    return len(pending)


# ---------- parciales por km ----------
def km_splits(stream: dict, split_m=1000):
    t, d = stream.get("t") or [], stream.get("d") or []
    if len(t) < 2:
        return []
    ta = active_time(t, d)
    hr, alt, cad = stream.get("hr") or [], stream.get("alt") or [], stream.get("cad") or []
    deq = equivalent_distance(stream)
    splits = []
    next_mark = split_m
    prev_t, prev_i, prev_d, prev_eq = 0.0, 0, 0.0, 0.0
    for k in range(1, len(d)):
        while d[k] is not None and d[k] >= next_mark:
            # interpolar el instante del cruce
            dd = d[k] - d[k - 1]
            frac = (next_mark - d[k - 1]) / dd if dd > 0 else 1
            tc = ta[k - 1] + frac * (ta[k] - ta[k - 1])
            eqc = deq[k - 1] + frac * (deq[k] - deq[k - 1]) if deq else None
            sp = _split(len(splits) + 1, next_mark - prev_d, tc - prev_t,
                        hr[prev_i:k + 1], alt, cad[prev_i:k + 1], prev_i, k)
            if deq and eqc - prev_eq > 0:
                sp["gap"] = round((tc - prev_t) / ((eqc - prev_eq) / 1000), 1)
            splits.append(sp)
            prev_t, prev_i, prev_d = tc, k, next_mark
            prev_eq = eqc
            next_mark += split_m
    rest = (d[-1] or 0) - prev_d
    if rest > 50:
        sp = _split(len(splits) + 1, rest, ta[-1] - prev_t, hr[prev_i:], alt, cad[prev_i:], prev_i, len(d) - 1)
        if deq and deq[-1] - prev_eq > 0:
            sp["gap"] = round((ta[-1] - prev_t) / ((deq[-1] - prev_eq) / 1000), 1)
        splits.append(sp)
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


def hr_bounds(uid: int):
    hr_max = db.get_setting(uid, "hr_max")
    hr_rest = db.get_setting(uid, "hr_rest")
    if not hr_max:
        r = db.one("SELECT MAX(max_hr) m FROM activities WHERE user_id=? AND is_run=1", (uid,))
        hr_max = r["m"] if r and r["m"] else 190
    if not hr_rest:
        r = db.one("SELECT AVG(rhr) m FROM (SELECT rhr FROM daily_health WHERE user_id=? AND rhr IS NOT NULL "
                   "ORDER BY date DESC LIMIT 30)", (uid,))
        hr_rest = r["m"] if r and r["m"] else 55
    return hr_rest, hr_max


def fitness_series(uid: int, days=180):
    """Serie diaria de carga, CTL (42 d), ATL (7 d) y TSB, usando todas las actividades."""
    acts = db.rows("SELECT date, training_load, moving_s, duration_s, avg_hr FROM activities "
                   "WHERE user_id=? AND date IS NOT NULL ORDER BY date", (uid,))
    if not acts:
        return []
    hr_rest, hr_max = hr_bounds(uid)
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


# ---------- monotonía y tensión (Foster) ----------
def monotony_strain(uid: int, weeks=26):
    """Por semana (lunes-domingo): carga, monotonía = media diaria / desviación típica, tensión = carga × monotonía.

    Monotonía > 2 indica un entrenamiento demasiado uniforme (poco contraste entre días duros y suaves).
    La tensión se compara con tu propia historia: alta si supera tu media + 1,5 desviaciones.
    """
    daily = fitness_series(uid, days=7 * (weeks + 12) + 7)
    if not daily:
        return {"weeks": [], "current": None}
    by_week = {}
    for x in daily:
        ws = week_start(date.fromisoformat(x["date"])).isoformat()
        by_week.setdefault(ws, []).append(x["load"])
    out = []
    for ws in sorted(by_week):
        loads = by_week[ws] + [0.0] * (7 - len(by_week[ws]))  # semana en curso: días que faltan = 0
        total = sum(loads)
        mean = total / 7
        sd = math.sqrt(sum((v - mean) ** 2 for v in loads) / 7)
        mono = round(mean / sd, 2) if sd > 0 else (None if total == 0 else 7.0)
        out.append({"week": ws, "load": round(total, 1), "monotony": mono,
                    "strain": round(total * mono, 1) if mono else 0.0,
                    "days": sum(1 for v in loads if v > 0), "complete": len(by_week[ws]) == 7})
    # umbral personal de tensión: media + 1,5·sd de las 12 semanas completas anteriores
    for i, w in enumerate(out):
        prev = [x["strain"] for x in out[max(0, i - 12):i] if x["complete"] and x["strain"]]
        if len(prev) >= 4:
            m = sum(prev) / len(prev)
            sd = math.sqrt(sum((v - m) ** 2 for v in prev) / len(prev))
            w["strain_limit"] = round(m + 1.5 * sd, 1)
        else:
            w["strain_limit"] = None
        flags = []
        if w["monotony"] and w["monotony"] > 2.0:
            flags.append("monotony")
        if w["strain_limit"] and w["strain"] > w["strain_limit"]:
            flags.append("strain")
        w["flags"] = flags
    out = out[-weeks:]
    return {"weeks": out, "current": out[-1] if out else None}

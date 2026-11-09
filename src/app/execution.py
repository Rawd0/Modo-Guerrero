"""¿Se hizo la sesión al ritmo previsto?

A partir del registro de la carrera (tiempo y distancia segundo a segundo) se buscan los tramos de
trabajo de la sesión sin depender de que hayas pulsado vuelta en el reloj:

- Series («5×1000 m», «6×800 m», «3×3 km»): los N tramos más rápidos de esa distancia que no se
  solapan.
- Fartlek y umbral por tiempo («8×1 min», «20 min continuos»): los N tramos de esa duración en los
  que más distancia recorriste.
- Tirada con final rápido («los últimos 8 km a ritmo…»): los últimos km de la actividad.
- Rodajes suaves y tiradas largas: el ritmo medio frente al rango de ritmo suave.

Se compara con el ritmo objetivo de la sesión: dentro de ±3 % está «en ritmo».
"""
import json
import math
import re

from . import db, metrics

TOL = 0.03

RE_REPS_M = re.compile(r"(\d+)×(\d+) m\b")
RE_REPS_KM = re.compile(r"(\d+)×(\d+(?:[.,]\d+)?) km\b")
RE_REPS_MIN = re.compile(r"(\d+)×(\d+) min\b")
RE_CONT_MIN = re.compile(r"(\d+) min continuos")
RE_FINISH = re.compile(r"últimos (\d+) km")


def structure(session: dict) -> dict:
    """Qué hay que medir en la sesión, leído de su descripción."""
    desc, typ = session.get("description") or "", session.get("type")
    if typ == "race":
        return {"kind": "whole"}
    if typ in ("intervals", "specific", "tempo", "fartlek"):
        if m := RE_REPS_M.search(desc):
            return {"kind": "reps_dist", "n": int(m[1]), "dist": float(m[2])}
        if m := RE_REPS_KM.search(desc):
            return {"kind": "reps_dist", "n": int(m[1]), "dist": float(m[2].replace(",", ".")) * 1000}
        if m := RE_REPS_MIN.search(desc):
            return {"kind": "reps_time", "n": int(m[1]), "secs": int(m[2]) * 60}
        if m := RE_CONT_MIN.search(desc):
            return {"kind": "reps_time", "n": 1, "secs": int(m[1]) * 60}
    if typ == "long" and (m := RE_FINISH.search(desc)):
        return {"kind": "finish", "dist": int(m[1]) * 1000}
    return {"kind": "easy"}


def _windows_dist(t, d, length):
    """Para cada final j, el tramo [i, j] más corto que cubre `length` metros, con su tiempo."""
    out, i = [], 0
    for j in range(1, len(d)):
        while i + 1 < j and d[j] - d[i + 1] >= length:
            i += 1
        if d[j] - d[i] >= length:
            out.append((t[j] - t[i], i, j, d[j] - d[i]))
    return out


def _windows_time(t, d, secs):
    """Para cada final j, el tramo de `secs` segundos que acaba en j, con la distancia recorrida."""
    out, i = [], 0
    for j in range(1, len(t)):
        while i + 1 < j and t[j] - t[i + 1] >= secs:
            i += 1
        if t[j] - t[i] >= secs:
            out.append((-(d[j] - d[i]), i, j, d[j] - d[i]))
    return out


def _pick(cands, n):
    """Los n mejores tramos que no se solapan."""
    chosen = []
    for c in sorted(cands):
        if all(c[2] <= x[1] or c[1] >= x[2] for x in chosen):
            chosen.append(c)
            if len(chosen) == n:
                break
    return sorted(chosen, key=lambda x: x[1])


def _verdict(actual, target):
    diff = (actual - target) / target  # positivo = más lento
    if abs(diff) <= TOL:
        return "ok", "En ritmo"
    if diff < 0:
        return "fast", "Más rápido de lo previsto"
    return ("slow", "Algo más lento") if diff <= 0.08 else ("veryslow", "Bastante más lento")


def evaluate(session: dict, paces: dict, stream: dict | None, act: dict) -> dict | None:
    """Devuelve el análisis de la sesión o None si no hay con qué medirlo."""
    st = structure(session)
    planned = session.get("distance_km") or 0
    dist_km = (act.get("distance_m") or 0) / 1000
    out = {"kind": st["kind"], "distance_km": round(dist_km, 2),
           "distance_ok": planned == 0 or dist_km >= planned * 0.9}
    if st["kind"] in ("easy", "whole"):
        if not act.get("moving_s") or not dist_km:
            return None
        avg = act["moving_s"] / dist_km
        out["actual_pace"] = round(avg, 1)
        if st["kind"] == "whole":
            target = session.get("target_pace") or paces.get("race")
            out["target_pace"] = target
            out["verdict"], out["label"] = _verdict(avg, target) if target else ("ok", "Hecha")
            return out
        lo, hi = paces["easy_fast"], paces["easy_slow"]
        out["target_range"] = [lo, hi]
        if avg < lo - 10:
            out["verdict"], out["label"] = "fast", "Demasiado rápido para ser suave"
        else:
            out["verdict"], out["label"] = "ok", "Ritmo suave"
        return out
    if not stream or len(stream.get("t") or []) < 10:
        return None
    t_raw, d = stream["t"], [x or 0 for x in stream["d"]]
    t = metrics.active_time(t_raw, d)
    target = session.get("target_pace")
    if not target:
        return None
    out["target_pace"] = target
    if st["kind"] == "finish":
        total = d[-1]
        if total < st["dist"]:
            return None
        start = next(k for k in range(len(d)) if d[k] >= total - st["dist"])
        secs = t[-1] - t[start]
        out["actual_pace"] = round(secs / ((total - d[start]) / 1000), 1)
        out["detail"] = f"Últimos {st['dist'] / 1000:.0f} km"
    else:
        if st["kind"] == "reps_dist":
            cands = _windows_dist(t, d, st["dist"])
        else:
            cands = _windows_time(t, d, st["secs"])
        reps = _pick(cands, st["n"])
        if not reps:
            return None
        rep_paces = []
        for c in reps:
            secs, dist = t[c[2]] - t[c[1]], c[3]
            if dist > 0 and secs > 0:
                rep_paces.append(round(secs / (dist / 1000), 1))
        if not rep_paces:
            return None
        total_secs = sum(t[c[2]] - t[c[1]] for c in reps)
        total_dist = sum(c[3] for c in reps)
        out["actual_pace"] = round(total_secs / (total_dist / 1000), 1)
        out["reps"] = rep_paces
        out["reps_found"] = len(rep_paces)
        out["reps_planned"] = st["n"]
        # regularidad: diferencia entre la más rápida y la más lenta
        out["spread"] = round(max(rep_paces) - min(rep_paces), 1) if len(rep_paces) > 1 else 0
        label = f"{st['n']}×{int(st['dist'])} m" if st["kind"] == "reps_dist" and st["dist"] <= 1600 else \
            f"{st['n']}×{st['dist'] / 1000:g} km" if st["kind"] == "reps_dist" else \
            (f"{st['n']}×{st['secs'] // 60} min" if st["n"] > 1 else f"{st['secs'] // 60} min continuos")
        out["detail"] = label
    out["verdict"], out["label"] = _verdict(out["actual_pace"], target)
    if out.get("reps_found") is not None and out["reps_found"] < out["reps_planned"]:
        out["verdict"], out["label"] = "slow", f"Sólo {out['reps_found']} de {out['reps_planned']} repeticiones"
    return out


def evaluate_session(uid: int, session: dict, paces: dict) -> dict | None:
    """Calcula (y guarda) el análisis de una sesión hecha con actividad enlazada."""
    if session.get("status") != "done" or not session.get("activity_id"):
        return None
    if session.get("execution"):
        try:
            return json.loads(session["execution"])
        except ValueError:
            pass
    act = db.one("SELECT id, distance_m, moving_s FROM activities WHERE id=? AND user_id=?",
                 (session["activity_id"], uid))
    if not act:
        return None
    stream = db.load_stream(act["id"])
    try:
        res = evaluate(session, paces, stream, act)
    except (ValueError, ZeroDivisionError, KeyError, StopIteration, TypeError):
        res = None
    if res is None:
        return None
    for k, v in list(res.items()):
        if isinstance(v, float) and not math.isfinite(v):
            res[k] = None
    db.execute("UPDATE plan_sessions SET execution=? WHERE id=?", (json.dumps(res), session["id"]))
    return res

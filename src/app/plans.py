"""Planes de entrenamiento para una carrera objetivo.

El plan se genera a partir de la carrera (distancia, fecha, objetivo), de tu forma actual (volumen
semanal y tirada larga recientes, VDOT) y de tus preferencias (días por semana, día de tirada larga).

- Fases: base → construcción → pico → afinamiento (las semanas que haya hasta la carrera).
- Volumen: sube como mucho un 8 % por semana hasta el volumen recomendado para la distancia,
  con una semana de descarga (−20 %) cada cuatro y el afinamiento al final.
- Ritmos: los de entrenamiento de Jack Daniels a partir de tu VDOT (suave, maratón, umbral,
  series, repeticiones) y tu ritmo objetivo de carrera en las sesiones específicas.
- Seguimiento: una sesión se da por hecha si hay una carrera tuya ese día; las pasadas sin
  actividad quedan como no hechas. Puedes marcarlas a mano, saltarlas o moverlas de día.
"""
import json
import math
from datetime import date, datetime, timedelta

from . import db, races

DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
TYPES = {
    "easy": "Rodaje suave", "long": "Tirada larga", "intervals": "Series", "tempo": "Umbral",
    "specific": "Ritmo de carrera", "fartlek": "Fartlek", "strides": "Rodaje con rectas",
    "shakeout": "Activación", "race": "Carrera",
}


class PlanError(Exception):
    pass


# ---------- ritmos de Daniels ----------
def _v_at(vo2):
    """Velocidad (m/min) a la que se consume `vo2` (inversa de la ecuación de Daniels)."""
    a, b, c = 0.000104, 0.182258, -4.60 - vo2
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def training_paces(vdot_value: float, race_distance=None, goal_time=None) -> dict:
    """Ritmos en s/km. Validado con la tabla de Daniels (VDOT 50: T 4:15, I 3:55, M 4:31)."""
    pace = lambda pct: round(60000 / _v_at(vdot_value * pct), 1)  # noqa: E731
    m_time = races.time_for_vdot(vdot_value, 42195)
    out = {"vdot": round(vdot_value, 1), "easy_slow": pace(0.62), "easy_fast": pace(0.70),
           "marathon": round(m_time / 42.195, 1), "threshold": pace(0.88), "interval": pace(0.975),
           "repetition": pace(1.05)}
    if race_distance:
        predicted = races.time_for_vdot(vdot_value, race_distance)
        out["race"] = round((goal_time or predicted) / (race_distance / 1000), 1)
        out["race_from_goal"] = bool(goal_time)
    return out


def fmt_pace(s):
    s = round(s)
    return f"{s // 60}:{s % 60:02d}"


# ---------- estructura del plan ----------
def _slots(days_per_week: int, long_day: int):
    base = {3: [1, 3, 6], 4: [1, 3, 5, 6], 5: [1, 2, 3, 5, 6], 6: [0, 1, 2, 3, 5, 6]}[days_per_week]
    if long_day == 5:  # tirada larga el sábado: desplazar viernes→jueves… sin solapar
        base = sorted({5 if d == 6 else (4 if d == 5 else d) for d in base})
    return base


def _phases(n_weeks: int, distance_m: float):
    taper = 2 if distance_m > 17000 else 1
    taper = min(taper, max(0, n_weeks - 1))
    rest = n_weeks - taper
    peak = min(3, max(0, rest // 3))
    base = max(0, round((rest - peak) * 0.4)) if rest >= 6 else 0
    build = rest - peak - base
    return ["base"] * base + ["build"] * build + ["peak"] * peak + ["taper"] * taper


def _round_km(x):
    return max(0.0, round(x * 2) / 2)


def build_plan(race: dict, start_km: float, start_long: float, days_per_week: int, long_day: int,
               paces: dict, start: date):
    """Devuelve la lista de semanas con sus sesiones (sin guardar)."""
    race_day = date.fromisoformat(race["date"])
    week0 = start - timedelta(days=start.weekday())
    race_week = race_day - timedelta(days=race_day.weekday())
    n = (race_week - week0).days // 7 + 1
    if n < 2:
        raise PlanError("La carrera es demasiado pronto para preparar un plan (hacen falta al menos 2 semanas)")
    if n > 40:
        raise PlanError("La carrera está a más de 40 semanas: crea el plan más adelante")
    dist = race["distance_m"]
    guide = races.guide_for(dist)
    phases = _phases(n, dist)
    early_race = race_day.weekday() <= 2 and n >= 3  # carrera de lunes a miércoles
    if early_race and phases[-2] != "taper":
        phases[-2] = "taper"
    peak_km = max(guide["weekly_km"], start_km * 1.15)
    long_target = guide["long_run_km"] + (2 if dist > 30000 else 0)
    slots = _slots(days_per_week, long_day)
    weeks = []
    vol, long_km = start_km, start_long
    build_weeks = 0
    for w in range(n):
        ph = phases[w]
        monday = week0 + timedelta(weeks=w)
        is_race_week = w == n - 1
        recovery = ph in ("base", "build") and w > 0 and (w + 1) % 4 == 0
        if ph in ("base", "build", "peak"):
            if w > 0 and not weeks[-1]["recovery"]:
                vol = min(peak_km, vol * 1.08)
                long_km = min(long_target, long_km + (2 if dist > 17000 else 1))
            week_vol = vol * (0.8 if recovery else 1)
            week_long = long_km * (0.75 if recovery else 1)
            build_weeks += 1
        else:  # afinamiento
            last = is_race_week or (early_race and w == n - 2)
            week_vol = vol * (0.45 if last else 0.65) if n - phases.count("taper") > 0 else vol * 0.6
            week_long = 0 if last else long_km * 0.6
        week_long = min(week_long, week_vol * (0.5 if dist > 30000 else 0.45))
        sessions = _week_sessions(race, ph, w, monday, slots, long_day, week_vol, week_long, paces,
                                  is_race_week, race_day, recovery, build_weeks)
        weeks.append({"index": w + 1, "monday": monday.isoformat(), "phase": ph, "recovery": recovery,
                      "planned_km": round(sum(s["distance_km"] for s in sessions if s["type"] != "race"), 1),
                      "sessions": sessions})
    _sharpen_before_race(weeks, race_day, paces)
    return weeks


def _sharpen_before_race(weeks, race_day, P):
    """La víspera, activación; dos días antes, nada largo (aunque caiga en la semana anterior)."""
    E = f"{fmt_pace(P['easy_fast'])}–{fmt_pace(P['easy_slow'])} /km"
    eve, eve2 = (race_day - timedelta(days=1)).isoformat(), (race_day - timedelta(days=2)).isoformat()
    for wk in weeks:
        for s in wk["sessions"]:
            if s["date"] == eve and s["type"] != "shakeout":
                s.update(type="shakeout", title=TYPES["shakeout"], distance_km=4.0, target_pace=P["easy_slow"],
                         description=f"20–25 min muy suave a {E} con 4×100 m alegres. Prepara el material.")
            elif s["date"] == eve2 and s["type"] in ("long", "intervals", "tempo", "specific", "fartlek"):
                s.update(type="easy", title=TYPES["easy"], distance_km=min(s["distance_km"], 6.0),
                         target_pace=P["easy_slow"], description=f"Rodaje suave a {E}. Corto: la carrera está cerca.")
        wk["planned_km"] = round(sum(s["distance_km"] for s in wk["sessions"] if s["type"] != "race"), 1)


def _week_sessions(race, phase, w, monday, slots, long_day, vol, long_km, P, is_race_week, race_day,
                   recovery, nth):
    dist = race["distance_m"]
    E = f"{fmt_pace(P['easy_fast'])}–{fmt_pace(P['easy_slow'])} /km"
    T, I, R, RP = fmt_pace(P["threshold"]), fmt_pace(P["interval"]), fmt_pace(P["repetition"]), fmt_pace(P["race"])
    M = fmt_pace(P["marathon"])
    wu = "Calienta 2 km suave y termina con 1–2 km suaves."
    out = []

    def add(day, typ, km, desc, pace=None):
        d = monday + timedelta(days=day)
        out.append({"date": d.isoformat(), "type": typ, "title": TYPES[typ], "distance_km": _round_km(km),
                    "description": desc, "target_pace": pace})

    if is_race_week:
        before = [d for d in slots if (monday + timedelta(days=d)) < race_day]
        easy_km = max(4, vol / max(1, len(before) + 1))
        for i, d in enumerate(before):
            day_date = monday + timedelta(days=d)
            if (race_day - day_date).days == 1:
                add(d, "shakeout", 4, f"20–25 min muy suave a {E} con 4×100 m alegres. Prepara el material.")
            elif i == 0 and (race_day - day_date).days >= 3:
                add(d, "specific", easy_km, f"{wu} 3×1 km a ritmo de carrera ({RP} /km) con 2 min suave. Sólo para recordar el ritmo, sin apretar.", P["race"])
            else:
                add(d, "easy", min(easy_km, 6), f"Rodaje suave a {E}.")
        add(race_day.weekday(), "race", dist / 1000,
            f"¡Día de carrera! Sal a {RP} /km y no te dejes llevar los primeros km. Calienta 10 min suave.", P["race"])
        return out

    n_slots = len(slots)
    q1_day, q2_day = slots[0], (slots[2] if n_slots >= 5 else slots[1]) if n_slots >= 4 else None
    q1_km, q2_km = vol * 0.18, vol * 0.16
    easy_days = [d for d in slots if d not in (q1_day, q2_day, long_day)]
    easy_total = vol - long_km - q1_km - (q2_km if q2_day is not None else 0)
    easy_km = max(4, easy_total / len(easy_days)) if easy_days else 0
    reps_i = min(6, 3 + nth // 3)

    # sesión de calidad 1
    if recovery:
        add(q1_day, "fartlek", q1_km, f"Semana de descarga. Fartlek suave: 6×1 min a ritmo de umbral ({T} /km) con 2 min suave.", P["threshold"])
    elif phase == "base":
        add(q1_day, "fartlek", q1_km, f"{wu} Fartlek: 8×1 min a ritmo de umbral ({T} /km) con 1 min suave.", P["threshold"])
    elif phase == "build":
        if dist <= 12000:
            add(q1_day, "intervals", q1_km, f"{wu} {reps_i + 1}×800 m a {I} /km, recuperando 400 m al trote.", P["interval"])
        else:
            add(q1_day, "intervals", q1_km, f"{wu} {reps_i}×1000 m a {I} /km, recuperando 400 m al trote.", P["interval"])
    elif phase == "peak":
        if dist <= 6000:
            add(q1_day, "specific", q1_km, f"{wu} 6×800 m a ritmo de carrera ({RP} /km) con 2 min suave.", P["race"])
        elif dist <= 12000:
            add(q1_day, "specific", q1_km, f"{wu} 5×1600 m a ritmo de carrera ({RP} /km) con 2 min suave.", P["race"])
        elif dist <= 25000:
            add(q1_day, "specific", q1_km, f"{wu} 3×3 km a ritmo de carrera ({RP} /km) con 3 min suave.", P["race"])
        else:
            add(q1_day, "specific", q1_km, f"{wu} 3×4 km a ritmo de maratón ({RP} /km) con 1 km suave.", P["race"])
    else:  # afinamiento
        add(q1_day, "specific", q1_km, f"{wu} 4×1 km a ritmo de carrera ({RP} /km) con 2 min suave. Menos volumen, misma chispa.", P["race"])

    # sesión de calidad 2
    if q2_day is not None:
        if recovery or phase == "base":
            add(q2_day, "strides", q2_km, f"Rodaje suave a {E} y al final 6×20 s rápidos ({R} /km) con recuperación completa.", P["easy_fast"])
        elif phase in ("build", "peak"):
            mins = 15 + min(10, nth)
            add(q2_day, "tempo", q2_km, f"{wu} {mins} min continuos a ritmo de umbral ({T} /km): «cómodamente duro».", P["threshold"])
        else:
            add(q2_day, "strides", q2_km, f"Rodaje suave a {E} con 4×20 s alegres.", P["easy_fast"])

    for d in easy_days:
        add(d, "easy", easy_km, f"Rodaje suave a {E}. Conversacional: deberías poder hablar.", P["easy_slow"])

    # tirada larga
    if long_km > 0:
        if phase in ("build", "peak") and not recovery and dist > 17000:
            seg = min(16 if dist > 30000 else 8, max(3, round(long_km * 0.35)))
            pace_label = M if dist > 30000 else RP
            add(long_day, "long", long_km, f"Tirada larga a {E}; los últimos {seg} km a ritmo {'de maratón' if dist > 30000 else 'de carrera'} ({pace_label} /km).",
                P["marathon"] if dist > 30000 else P["race"])
        else:
            add(long_day, "long", long_km, f"Tirada larga a {E}. Constante, sin mirar el reloj.", P["easy_slow"])
    out.sort(key=lambda s: s["date"])
    return out


# ---------- guardar / cargar ----------
def _current_fitness(uid: int):
    today = date.today()
    since4 = (today - timedelta(weeks=4)).isoformat()
    since6 = (today - timedelta(weeks=6)).isoformat()
    vol = db.one("SELECT COALESCE(SUM(distance_m),0) d FROM activities WHERE user_id=? AND is_run=1 AND date>=?",
                 (uid, since4))["d"] / 1000 / 4
    longest = (db.one("SELECT MAX(distance_m) m FROM activities WHERE user_id=? AND is_run=1 AND date>=?",
                      (uid, since6))["m"] or 0) / 1000
    return round(vol, 1), round(longest, 1)


def defaults(uid: int, race_id: int):
    races._own(uid, race_id)
    vol, longest = _current_fitness(uid)
    return {"start_km": max(15, round(vol)), "start_long": max(6, round(longest)), "days_per_week": 4, "long_day": 6,
            "current_weekly_km": vol, "current_long_km": longest}


def create(uid: int, race_id: int, payload: dict):
    race = races._own(uid, race_id)
    if date.fromisoformat(race["date"]) < date.today():
        raise PlanError("La carrera ya ha pasado")
    try:
        days = int(payload.get("days_per_week") or 4)
        long_day = int(payload.get("long_day") or 6)
        start_km = float(payload.get("start_km") or 0)
    except (TypeError, ValueError):
        raise PlanError("Valores no válidos")
    if days not in (3, 4, 5, 6) or long_day not in (5, 6):
        raise PlanError("Elige entre 3 y 6 días y la tirada larga en sábado o domingo")
    d = defaults(uid, race_id)
    start_km = start_km or d["start_km"]
    if not 5 <= start_km <= 250:
        raise PlanError("El volumen semanal de partida debe estar entre 5 y 250 km")
    start_long = min(max(d["start_long"], start_km * 0.25), races.guide_for(race["distance_m"])["long_run_km"])
    pred = races.predictions(uid, race["distance_m"])
    v = pred.get("vdot_value") or (races.vdot(race["distance_m"], race["goal_time_s"]) if race.get("goal_time_s") else None)
    if not v:
        raise PlanError("Hace falta algún tramo reciente o un tiempo objetivo para calcular tus ritmos")
    paces = training_paces(v, race["distance_m"], race.get("goal_time_s"))
    today = date.today()
    weeks = build_plan(race, start_km, start_long, days, long_day, paces, today)
    params = {"days_per_week": days, "long_day": long_day, "start_km": start_km, "start_long": round(start_long, 1)}
    with db.tx() as con:
        old = con.execute("SELECT id FROM training_plans WHERE user_id=? AND race_id=?", (uid, race_id)).fetchone()
        if old:
            # conservar lo ya hecho; rehacer lo que queda por delante
            # se conservan las sesiones ya hechas o marcadas a mano; se rehace el resto
            con.execute("DELETE FROM plan_sessions WHERE plan_id=? AND date>=? AND status='planned' AND manual=0",
                        (old[0], today.isoformat()))
            con.execute("UPDATE training_plans SET params=?, paces=?, weeks=?, updated=? WHERE id=?",
                        (json.dumps(params), json.dumps(paces), json.dumps(_week_meta(weeks)),
                         datetime.now().isoformat(timespec="seconds"), old[0]))
            plan_id = old[0]
        else:
            cur = con.execute("INSERT INTO training_plans (user_id, race_id, params, paces, weeks, created, updated) "
                              "VALUES (?,?,?,?,?,?,?)", (uid, race_id, json.dumps(params), json.dumps(paces),
                                                         json.dumps(_week_meta(weeks)), *(2 * [datetime.now().isoformat(timespec="seconds")])))
            plan_id = cur.lastrowid
        taken = {r[0] for r in con.execute("SELECT date FROM plan_sessions WHERE plan_id=?", (plan_id,)).fetchall()}
        for wk in weeks:
            for s in wk["sessions"]:
                if s["date"] < today.isoformat() or s["date"] in taken:
                    continue  # días ya pasados o con una sesión hecha
                con.execute("INSERT INTO plan_sessions (plan_id, user_id, date, type, title, description, distance_km, "
                            "target_pace, status) VALUES (?,?,?,?,?,?,?,?, 'planned')",
                            (plan_id, uid, s["date"], s["type"], s["title"], s["description"], s["distance_km"], s["target_pace"]))
    return plan_id


def _week_meta(weeks):
    return [{k: w[k] for k in ("index", "monday", "phase", "recovery", "planned_km")} for w in weeks]


def delete(uid: int, race_id: int):
    races._own(uid, race_id)
    with db.tx() as con:
        p = con.execute("SELECT id FROM training_plans WHERE user_id=? AND race_id=?", (uid, race_id)).fetchone()
        if p:
            con.execute("DELETE FROM plan_sessions WHERE plan_id=?", (p[0],))
            con.execute("DELETE FROM training_plans WHERE id=?", (p[0],))


# ---------- seguimiento ----------
def match_sessions(uid: int, plan_id: int):
    """Enlaza las sesiones con las carreras de ese día y marca como no hechas las pasadas sin actividad."""
    today = date.today().isoformat()
    pending = db.rows("SELECT id, date FROM plan_sessions WHERE plan_id=? AND user_id=? AND status='planned' AND date<=? "
                      "AND type<>'race' ORDER BY date", (plan_id, uid, today))
    for s in pending:
        used = {r["activity_id"] for r in db.rows("SELECT activity_id FROM plan_sessions WHERE user_id=? AND activity_id IS NOT NULL", (uid,))}
        acts = [a for a in db.rows("SELECT id, distance_m FROM activities WHERE user_id=? AND is_run=1 AND date=? "
                                   "ORDER BY distance_m DESC", (uid, s["date"])) if a["id"] not in used]
        if acts:
            db.execute("UPDATE plan_sessions SET status='done', activity_id=? WHERE id=?", (acts[0]["id"], s["id"]))
        elif s["date"] < today:
            db.execute("UPDATE plan_sessions SET status='missed' WHERE id=?", (s["id"],))
    # la carrera: enlazada al resultado del objetivo
    race_s = db.one("SELECT ps.id, r.result_activity_id FROM plan_sessions ps JOIN training_plans tp ON tp.id=ps.plan_id "
                    "JOIN races r ON r.id=tp.race_id WHERE ps.plan_id=? AND ps.type='race'", (plan_id,))
    if race_s and race_s["result_activity_id"]:
        db.execute("UPDATE plan_sessions SET status='done', activity_id=? WHERE id=?", (race_s["result_activity_id"], race_s["id"]))


def update_session(uid: int, session_id: int, payload: dict):
    s = db.one("SELECT * FROM plan_sessions WHERE id=? AND user_id=?", (session_id, uid))
    if not s:
        raise PlanError("Sesión no encontrada")
    status = payload.get("status")
    if status is not None:
        if status not in ("planned", "done", "skipped"):
            raise PlanError("Estado no válido")
        db.execute("UPDATE plan_sessions SET status=?, activity_id=CASE WHEN ?='done' THEN activity_id ELSE NULL END, "
                   "manual=1 WHERE id=?", (status, status, session_id))
    if payload.get("date"):
        try:
            nd = date.fromisoformat(payload["date"])
        except ValueError:
            raise PlanError("Fecha no válida")
        bounds = db.one("SELECT tp.weeks, r.date race_date FROM training_plans tp JOIN races r ON r.id=tp.race_id "
                        "WHERE tp.id=?", (s["plan_id"],))
        first = json.loads(bounds["weeks"])[0]["monday"]
        if s["type"] == "race":
            raise PlanError("La carrera se mueve desde el objetivo, no desde el plan")
        if not first <= nd.isoformat() < bounds["race_date"]:
            raise PlanError("La sesión tiene que quedar entre el inicio del plan y la carrera")
        db.execute("UPDATE plan_sessions SET date=?, status='planned', activity_id=NULL, manual=0 WHERE id=?",
                   (nd.isoformat(), session_id))


def get_plan(uid: int, race_id: int):
    race = races._own(uid, race_id)
    p = db.one("SELECT * FROM training_plans WHERE user_id=? AND race_id=?", (uid, race_id))
    if not p:
        return {"plan": None, "defaults": defaults(uid, race_id) if race["date"] >= date.today().isoformat() else None}
    races.auto_link_results(uid)
    match_sessions(uid, p["id"])
    sessions = db.rows("SELECT ps.*, a.distance_m act_distance, a.moving_s act_time, a.name act_name FROM plan_sessions ps "
                       "LEFT JOIN activities a ON a.id=ps.activity_id WHERE ps.plan_id=? ORDER BY ps.date, ps.id", (p["id"],))
    meta = json.loads(p["weeks"])
    weeks = []
    today = date.today()
    for m in meta:
        mon = date.fromisoformat(m["monday"])
        sun = mon + timedelta(days=6)
        ss = [s for s in sessions if m["monday"] <= s["date"] <= sun.isoformat()]
        done_km = db.one("SELECT COALESCE(SUM(distance_m),0)/1000.0 km FROM activities WHERE user_id=? AND is_run=1 "
                         "AND date BETWEEN ? AND ?", (uid, m["monday"], sun.isoformat()))["km"]
        planned = sum(s["distance_km"] for s in ss if s["type"] != "race") or m["planned_km"]
        current = mon <= today <= sun
        # en la semana en curso se compara con lo previsto hasta hoy
        due = sum(s["distance_km"] for s in ss if s["type"] != "race" and s["date"] <= today.isoformat()) if current else planned
        weeks.append({**m, "planned_km": round(planned, 1), "due_km": round(due, 1), "done_km": round(done_km, 1),
                      "sessions": ss, "current": current, "past": sun < today,
                      "compliance": round(100 * done_km / due) if due and mon <= today else None})
    past = [w for w in weeks if w["past"] or w["current"]]
    counted = [s for s in sessions if s["date"] <= today.isoformat() and s["type"] != "race"]
    done = sum(1 for s in counted if s["status"] == "done")
    return {"plan": {"id": p["id"], "params": json.loads(p["params"]), "paces": json.loads(p["paces"]),
                     "created": p["created"], "updated": p["updated"]},
            "weeks": weeks,
            "summary": {"sessions_done": done, "sessions_due": len(counted),
                        "km_done": round(sum(w["done_km"] for w in past), 1),
                        "km_planned": round(sum(w["due_km"] for w in past), 1)}}


def today_session(uid: int):
    """La sesión de hoy (o la próxima) del plan de la carrera más cercana."""
    p = db.one("SELECT tp.id, tp.race_id, r.name race_name, r.date race_date FROM training_plans tp "
               "JOIN races r ON r.id=tp.race_id WHERE tp.user_id=? AND r.date>=? ORDER BY r.date LIMIT 1",
               (uid, date.today().isoformat()))
    if not p:
        return None
    match_sessions(uid, p["id"])
    today = date.today().isoformat()
    s = db.one("SELECT * FROM plan_sessions WHERE plan_id=? AND date>=? AND status IN ('planned','done') "
               "ORDER BY date, id LIMIT 1", (p["id"], today))
    week = db.rows("SELECT date, type, status, distance_km FROM plan_sessions WHERE plan_id=? AND date BETWEEN ? AND ? ORDER BY date",
                   (p["id"], (date.today() - timedelta(days=date.today().weekday())).isoformat(),
                    (date.today() + timedelta(days=6 - date.today().weekday())).isoformat()))
    return {"race_id": p["race_id"], "race_name": p["race_name"], "race_date": p["race_date"], "session": s, "week": week}

"""Rutas repetidas: detecta las carreras que hacen el mismo recorrido para ver tu evolución en él.

Cada carrera con GPS se resume en una «firma»: inicio, final, distancia y 24 puntos repartidos a lo
largo del recorrido. Dos carreras son la misma ruta si tienen una distancia parecida (±6 %), salen y
llegan a menos de 250 m y sus recorridos se separan de media menos de 120 m. El sentido cuenta: ir
y volver por el mismo camino al revés es otra ruta.
"""
import json
import logging
import math
import threading

from . import db

log = logging.getLogger("guerrero.routes")

N_POINTS = 24
MAX_ENDPOINT_M = 250
MAX_MEAN_M = 120
DIST_TOL = 0.06
MIN_DIST_M = 1500
_lock = threading.Lock()


class RouteError(Exception):
    pass


def _hav(a, b):
    """Distancia en metros entre dos puntos [lat, lon]."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(min(1.0, math.sqrt(h)))


def signature(stream: dict):
    lat, lon, d = stream.get("lat") or [], stream.get("lon") or [], stream.get("d") or []
    pts = [(la, lo, dd) for la, lo, dd in zip(lat, lon, d) if la and lo and dd is not None]
    if len(pts) < 20:
        return None
    total = pts[-1][2] - pts[0][2]
    if total < MIN_DIST_M:
        return None
    out, j = [], 0
    for k in range(N_POINTS):
        target = pts[0][2] + total * k / (N_POINTS - 1)
        while j < len(pts) - 1 and pts[j + 1][2] < target:
            j += 1
        out.append([round(pts[j][0], 5), round(pts[j][1], 5)])
    return {"start": out[0], "end": out[-1], "dist": total, "pts": out}


def same_route(a: dict, b: dict) -> bool:
    if abs(a["dist"] - b["dist"]) > DIST_TOL * max(a["dist"], b["dist"]):
        return False
    if _hav(a["start"], b["start"]) > MAX_ENDPOINT_M or _hav(a["end"], b["end"]) > MAX_ENDPOINT_M:
        return False
    mean = sum(_hav(p, q) for p, q in zip(a["pts"], b["pts"])) / N_POINTS
    return mean <= MAX_MEAN_M


def _sig_row(r):
    return {"start": [r["start_lat"], r["start_lon"]], "end": [r["end_lat"], r["end_lon"]], "dist": r["dist_m"],
            "pts": json.loads(r["pts"])}


def _kind(sig):
    if _hav(sig["start"], sig["end"]) < MAX_ENDPOINT_M:
        far = max(_hav(sig["start"], p) for p in sig["pts"])
        # vuelve por donde fue (ida y vuelta) o da una vuelta (circular)
        half = sig["pts"][: N_POINTS // 2]
        back = sig["pts"][N_POINTS // 2:][::-1]
        mirror = sum(_hav(p, q) for p, q in zip(half, back)) / len(half)
        return "ida y vuelta" if mirror < max(150, far * 0.15) else "circular"
    return "lineal"


def _default_name(sig):
    km = f"{sig['dist'] / 1000:.1f}".replace(".", ",")
    return f"Ruta {_kind(sig)} de {km} km"


def assign(activity_id: int, stream: dict | None = None):
    """Calcula la firma de una carrera y la asigna a una ruta (creándola si coincide con otra suelta)."""
    act = db.one("SELECT id, user_id, is_run FROM activities WHERE id=?", (activity_id,))
    if not act or not act["is_run"]:
        return None
    stream = stream if stream is not None else db.load_stream(activity_id)
    sig = signature(stream or {})
    with _lock:
        if not sig:
            db.execute("INSERT OR REPLACE INTO route_sigs (activity_id, user_id, dist_m, pts) VALUES (?,?,0,'[]')",
                       (activity_id, act["user_id"]))
            return None
        uid = act["user_id"]
        db.execute("INSERT OR REPLACE INTO route_sigs (activity_id, user_id, start_lat, start_lon, end_lat, end_lon, "
                   "dist_m, pts) VALUES (?,?,?,?,?,?,?,?)",
                   (activity_id, uid, *sig["start"], *sig["end"], sig["dist"], json.dumps(sig["pts"])))
        # candidatos: misma distancia aproximada y salida cercana (filtro grueso en SQL)
        dlat = MAX_ENDPOINT_M / 111000 * 1.5
        dlon = dlat / max(0.2, math.cos(math.radians(sig["start"][0])))
        cands = db.rows("SELECT s.*, a.route_id FROM route_sigs s JOIN activities a ON a.id=s.activity_id "
                        "WHERE s.user_id=? AND s.activity_id<>? AND s.dist_m BETWEEN ? AND ? "
                        "AND s.start_lat BETWEEN ? AND ? AND s.start_lon BETWEEN ? AND ?",
                        (uid, activity_id, sig["dist"] * (1 - DIST_TOL), sig["dist"] * (1 + DIST_TOL),
                         sig["start"][0] - dlat, sig["start"][0] + dlat, sig["start"][1] - dlon, sig["start"][1] + dlon))
        # primero las que ya tienen ruta (comparando con su recorrido de referencia)
        reps = {}
        for c in cands:
            if c["route_id"] and c["route_id"] not in reps:
                rep = db.one("SELECT s.* FROM routes r JOIN route_sigs s ON s.activity_id=r.rep_activity_id "
                             "WHERE r.id=?", (c["route_id"],))
                reps[c["route_id"]] = _sig_row(rep) if rep else _sig_row(c)
        for rid, rsig in reps.items():
            if same_route(sig, rsig):
                db.execute("UPDATE activities SET route_id=? WHERE id=?", (rid, activity_id))
                return rid
        for c in cands:
            if not c["route_id"] and same_route(sig, _sig_row(c)):
                with db.tx() as con:
                    cur = con.execute("INSERT INTO routes (user_id, name, rep_activity_id) VALUES (?,?,?)",
                                      (uid, _default_name(sig), c["activity_id"]))
                    rid = cur.lastrowid
                    con.execute("UPDATE activities SET route_id=? WHERE id IN (?, ?)", (rid, activity_id, c["activity_id"]))
                # otras carreras sueltas que también encajen
                for o in cands:
                    if o["activity_id"] != c["activity_id"] and not o["route_id"] and same_route(_sig_row(o), _sig_row(c)):
                        db.execute("UPDATE activities SET route_id=? WHERE id=?", (rid, o["activity_id"]))
                return rid
        db.execute("UPDATE activities SET route_id=NULL WHERE id=?", (activity_id,))
        return None


def backfill(limit=None):
    """Firma y agrupa las carreras con GPS que aún no se han analizado (de la más antigua a la más nueva)."""
    pending = db.rows("SELECT a.id FROM activities a JOIN streams s ON s.activity_id=a.id "
                      "WHERE a.is_run=1 AND NOT EXISTS (SELECT 1 FROM route_sigs r WHERE r.activity_id=a.id) "
                      "ORDER BY a.start_local" + (f" LIMIT {int(limit)}" if limit else ""))
    for r in pending:
        try:
            assign(r["id"])
        except Exception:  # noqa: BLE001
            log.exception("Ruta de la actividad %s", r["id"])
    return len(pending)


# ---------- consultas ----------
def _runs(uid, route_id):
    return db.rows("SELECT id, name, date, start_local, distance_m, moving_s, avg_hr, gap_pace, elev_gain, shoe_id "
                   "FROM activities WHERE user_id=? AND route_id=? ORDER BY start_local", (uid, route_id))


def list_routes(uid: int):
    out = []
    for r in db.rows("SELECT r.*, s.pts, s.dist_m FROM routes r LEFT JOIN route_sigs s ON s.activity_id=r.rep_activity_id "
                     "WHERE r.user_id=? ORDER BY r.id", (uid,)):
        runs = _runs(uid, r["id"])
        if len(runs) < 2:
            continue
        paces = [x["moving_s"] / (x["distance_m"] / 1000) for x in runs if x["moving_s"] and x["distance_m"]]
        best = min(runs, key=lambda x: x["moving_s"] / x["distance_m"] if x["moving_s"] and x["distance_m"] else 9e9)
        last = runs[-1]
        recent = paces[-3:]
        out.append({"id": r["id"], "name": r["name"], "dist_m": r["dist_m"], "pts": json.loads(r["pts"] or "[]"),
                    "count": len(runs), "first": runs[0]["date"], "last": last["date"],
                    "best": {"id": best["id"], "date": best["date"], "time_s": best["moving_s"],
                             "pace": best["moving_s"] / (best["distance_m"] / 1000)},
                    "last_run": {"id": last["id"], "time_s": last["moving_s"],
                                 "pace": last["moving_s"] / (last["distance_m"] / 1000) if last["distance_m"] else None},
                    "recent_pace": sum(recent) / len(recent) if recent else None,
                    "avg_pace": sum(paces) / len(paces) if paces else None})
    out.sort(key=lambda x: (x["last"], x["count"]), reverse=True)
    return out


def detail(uid: int, route_id: int):
    r = db.one("SELECT * FROM routes WHERE id=? AND user_id=?", (route_id, uid))
    if not r:
        raise RouteError("Ruta no encontrada")
    runs = _runs(uid, route_id)
    rep = db.load_stream(r["rep_activity_id"]) or {}
    track = [[la, lo] for la, lo in zip(rep.get("lat") or [], rep.get("lon") or []) if la and lo]
    step = max(1, len(track) // 600)
    items = []
    for x in runs:
        pace = x["moving_s"] / (x["distance_m"] / 1000) if x["moving_s"] and x["distance_m"] else None
        eff = (x["distance_m"] / (x["moving_s"] / 60)) / x["avg_hr"] if pace and x["avg_hr"] else None
        items.append({**x, "pace": pace, "efficiency": round(eff, 3) if eff else None})
    ranked = sorted([i for i in items if i["pace"]], key=lambda i: i["pace"])
    rank = {i["id"]: k + 1 for k, i in enumerate(ranked)}
    for i in items:
        i["rank"] = rank.get(i["id"])
    return {"id": r["id"], "name": r["name"], "track": track[::step], "runs": items,
            "dist_m": db.one("SELECT dist_m FROM route_sigs WHERE activity_id=?", (r["rep_activity_id"],))["dist_m"]}


def rename(uid: int, route_id: int, name: str):
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise RouteError("Pon un nombre de hasta 80 caracteres")
    if not db.one("SELECT 1 x FROM routes WHERE id=? AND user_id=?", (route_id, uid)):
        raise RouteError("Ruta no encontrada")
    db.execute("UPDATE routes SET name=? WHERE id=?", (name, route_id))


def for_activity(uid: int, activity_id: int):
    a = db.one("SELECT route_id FROM activities WHERE id=? AND user_id=?", (activity_id, uid))
    if not a or not a["route_id"]:
        return None
    d = detail(uid, a["route_id"])
    if len(d["runs"]) < 2:
        return None
    me = next((x for x in d["runs"] if x["id"] == activity_id), None)
    return {"id": d["id"], "name": d["name"], "count": len(d["runs"]), "rank": me["rank"] if me else None}

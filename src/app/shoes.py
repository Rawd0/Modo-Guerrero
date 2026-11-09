"""Zapatillas: kilometraje acumulado y aviso de cambio."""
from datetime import datetime

from . import db


class ShoeError(Exception):
    pass


def _check_owner(uid: int, shoe_id: int):
    if not db.one("SELECT 1 FROM shoes WHERE id=? AND user_id=?", (shoe_id, uid)):
        raise ShoeError("Zapatilla no encontrada")


def list_shoes(uid: int):
    rows = db.rows(
        "SELECT s.*, COUNT(a.id) runs, COALESCE(SUM(a.distance_m),0)/1000.0 run_km, MAX(a.date) last_used, "
        "MIN(a.date) first_used FROM shoes s LEFT JOIN activities a ON a.shoe_id=s.id AND a.user_id=s.user_id "
        "WHERE s.user_id=? GROUP BY s.id ORDER BY s.retired, s.is_default DESC, last_used DESC, s.id DESC", (uid,))
    for r in rows:
        r["km"] = round((r["initial_km"] or 0) + r["run_km"], 1)
        r["pct"] = round(100 * r["km"] / r["limit_km"], 1) if r["limit_km"] else None
        r["status"] = ("retired" if r["retired"] else "replace" if r["pct"] and r["pct"] >= 100
                       else "soon" if r["pct"] and r["pct"] >= 85 else "ok")
    return rows


def _clean(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if not name or len(name) > 60:
        raise ShoeError("Pon un nombre a la zapatilla (máximo 60 caracteres)")
    try:
        initial = float(payload.get("initial_km") or 0)
        limit = float(payload.get("limit_km") or 700)
    except (TypeError, ValueError):
        raise ShoeError("Los kilómetros deben ser números")
    if initial < 0 or limit <= 0 or limit > 5000:
        raise ShoeError("Revisa los kilómetros iniciales y el límite")
    start = payload.get("start_date") or None
    if start:
        try:
            datetime.strptime(start, "%Y-%m-%d")
        except ValueError:
            raise ShoeError("Fecha de inicio no válida")
    return {"name": name, "brand": (payload.get("brand") or "").strip()[:60] or None, "start_date": start,
            "initial_km": initial, "limit_km": limit, "notes": (payload.get("notes") or "").strip()[:300] or None}


def create(uid: int, payload: dict) -> int:
    data = _clean(payload)
    with db.tx() as con:
        cur = con.execute("INSERT INTO shoes (user_id, name, brand, start_date, initial_km, limit_km, notes, created) "
                          "VALUES (?,?,?,?,?,?,?,?)", (uid, data["name"], data["brand"], data["start_date"],
                                                      data["initial_km"], data["limit_km"], data["notes"],
                                                      datetime.now().isoformat(timespec="seconds")))
        sid = cur.lastrowid
    if payload.get("is_default"):
        set_default(uid, sid)
    if payload.get("assign_existing") and data["start_date"]:
        assign_since(uid, sid, data["start_date"])
    return sid


def update(uid: int, shoe_id: int, payload: dict):
    _check_owner(uid, shoe_id)
    data = _clean(payload)
    db.execute("UPDATE shoes SET name=?, brand=?, start_date=?, initial_km=?, limit_km=?, notes=? WHERE id=? AND user_id=?",
               (data["name"], data["brand"], data["start_date"], data["initial_km"], data["limit_km"], data["notes"],
                shoe_id, uid))
    if "retired" in payload:
        db.execute("UPDATE shoes SET retired=?, is_default=CASE WHEN ? THEN 0 ELSE is_default END WHERE id=? AND user_id=?",
                   (1 if payload["retired"] else 0, 1 if payload["retired"] else 0, shoe_id, uid))
    if payload.get("is_default") and not payload.get("retired"):
        set_default(uid, shoe_id)
    elif payload.get("is_default") is False:
        db.execute("UPDATE shoes SET is_default=0 WHERE id=? AND user_id=?", (shoe_id, uid))


def set_default(uid: int, shoe_id: int):
    _check_owner(uid, shoe_id)
    with db.tx() as con:
        con.execute("UPDATE shoes SET is_default=0 WHERE user_id=?", (uid,))
        con.execute("UPDATE shoes SET is_default=1, retired=0 WHERE id=? AND user_id=?", (shoe_id, uid))


def assign_since(uid: int, shoe_id: int, start_date: str) -> int:
    """Asigna la zapatilla a las carreras sin zapatilla desde una fecha."""
    _check_owner(uid, shoe_id)
    with db.tx() as con:
        cur = con.execute("UPDATE activities SET shoe_id=? WHERE user_id=? AND is_run=1 AND shoe_id IS NULL AND date>=?",
                          (shoe_id, uid, start_date))
        return cur.rowcount


def delete(uid: int, shoe_id: int):
    _check_owner(uid, shoe_id)
    with db.tx() as con:
        con.execute("UPDATE activities SET shoe_id=NULL WHERE user_id=? AND shoe_id=?", (uid, shoe_id))
        con.execute("DELETE FROM shoes WHERE id=? AND user_id=?", (shoe_id, uid))


def assign_activity(uid: int, activity_id: int, shoe_id):
    if shoe_id is not None:
        _check_owner(uid, int(shoe_id))
    with db.tx() as con:
        cur = con.execute("UPDATE activities SET shoe_id=? WHERE id=? AND user_id=?", (shoe_id, activity_id, uid))
        if not cur.rowcount:
            raise ShoeError("Actividad no encontrada")

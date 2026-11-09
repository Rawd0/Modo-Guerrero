"""Lectura de archivos .FIT (y .zip de Garmin con un .FIT dentro)."""
import io
import zipfile
from datetime import timezone

import fitdecode

SEMI = 180.0 / 2 ** 31


def extract_fit_bytes(blob: bytes) -> list[bytes]:
    """Devuelve los .fit contenidos en un zip, o el propio blob si ya es FIT."""
    if blob[:2] == b"PK":
        out = []
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for n in z.namelist():
                if n.lower().endswith(".fit"):
                    out.append(z.read(n))
        return out
    return [blob]


def _f(frame, *names):
    for n in names:
        if frame.has_field(n):
            v = frame.get_value(n)
            if v is not None:
                return v
    return None


def parse_fit(data: bytes) -> dict:
    """Devuelve {'session': {...}, 'stream': {t,d,hr,alt,cad,spd,lat,lon}}."""
    t0 = None
    s = {k: [] for k in ("t", "d", "hr", "alt", "cad", "spd", "lat", "lon")}
    session = {}
    with fitdecode.FitReader(io.BytesIO(data), check_crc=fitdecode.CrcCheck.DISABLED) as fr:
        for frame in fr:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "record":
                ts = _f(frame, "timestamp")
                if ts is None:
                    continue
                if t0 is None:
                    t0 = ts
                lat = _f(frame, "position_lat")
                lon = _f(frame, "position_long")
                cad = _f(frame, "cadence")
                frac = _f(frame, "fractional_cadence") or 0
                s["t"].append(round((ts - t0).total_seconds(), 1))
                s["d"].append(_f(frame, "distance"))
                s["hr"].append(_f(frame, "heart_rate"))
                s["alt"].append(_round(_f(frame, "enhanced_altitude", "altitude"), 1))
                # La cadencia de carrera en FIT va por pierna: x2 = pasos/min
                s["cad"].append(round((cad + frac) * 2) if cad is not None else None)
                s["spd"].append(_round(_f(frame, "enhanced_speed", "speed"), 3))
                s["lat"].append(round(lat * SEMI, 6) if isinstance(lat, int) else None)
                s["lon"].append(round(lon * SEMI, 6) if isinstance(lon, int) else None)
            elif frame.name == "session" and not session:
                st = _f(frame, "start_time")
                session = {
                    "sport": str(_f(frame, "sport") or ""),
                    "sub_sport": str(_f(frame, "sub_sport") or ""),
                    "start_utc": st.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if st else None,
                    "distance_m": _f(frame, "total_distance"),
                    "moving_s": _f(frame, "total_timer_time"),
                    "duration_s": _f(frame, "total_elapsed_time"),
                    "avg_hr": _f(frame, "avg_heart_rate"),
                    "max_hr": _f(frame, "max_heart_rate"),
                    "calories": _f(frame, "total_calories"),
                    "elev_gain": _f(frame, "total_ascent"),
                    "elev_loss": _f(frame, "total_descent"),
                    "avg_speed": _f(frame, "enhanced_avg_speed", "avg_speed"),
                    "max_speed": _f(frame, "enhanced_max_speed", "max_speed"),
                    "cadence": _cad(_f(frame, "avg_running_cadence", "avg_cadence")),
                    "aerobic_te": _f(frame, "total_training_effect"),
                    "anaerobic_te": _f(frame, "total_anaerobic_training_effect"),
                }
    _fill_distance(s)
    return {"session": session, "stream": s}


def _cad(v):
    return v * 2 if v is not None and v < 120 else v


def _round(v, n):
    return round(v, n) if isinstance(v, (int, float)) else None


def _fill_distance(s):
    """Rellena huecos de distancia arrastrando el último valor conocido."""
    last = 0.0
    for i, v in enumerate(s["d"]):
        if v is None:
            s["d"][i] = last
        else:
            last = v

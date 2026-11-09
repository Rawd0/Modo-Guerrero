"""Genera datos de ejemplo (carreras + salud) para probar Modo Guerrero sin cuenta de Garmin.

Los datos quedan "sin asignar" y pasan al primer administrador que se cree.

Uso:  docker compose exec modo-guerrero python -m scripts.demo_data
      (o, en desarrollo:  DATA_DIR=./data python -m scripts.demo_data)
NO lo ejecutes sobre tus datos reales: borra la base de datos.
"""
import json
import math
import random
from datetime import date, datetime, timedelta

from app import db, metrics
from app.config import DB_PATH

random.seed(7)

BASE_LAT, BASE_LON = 40.4153, -3.6845  # Retiro, Madrid


def make_stream(dist_m, pace_s_km, hr_avg, hilly=False):
    t, d, hr, alt, cad, spd, lat, lon = [], [], [], [], [], [], [], []
    cur_t, cur_d, ang = 0.0, 0.0, random.random() * 6.28
    radius = 0.006 + random.random() * 0.004
    while cur_d < dist_m:
        prog = cur_d / dist_m
        p = pace_s_km * (1 + 0.04 * math.sin(prog * 12) + random.gauss(0, 0.015))
        if prog < 0.05:
            p *= 1.08
        v = 1000 / p
        cur_t += 2
        cur_d = min(cur_d + v * 2, dist_m)
        ang += v * 2 / (radius * 111000)
        t.append(cur_t)
        d.append(round(cur_d, 1))
        hr.append(int(hr_avg - 15 * math.exp(-cur_t / 300) + 6 * prog + random.gauss(0, 2)))
        alt.append(round(650 + (25 if hilly else 6) * math.sin(prog * 9), 1))
        cad.append(int(170 + 6 * (pace_s_km < 300) + random.gauss(0, 2)))
        spd.append(round(v, 3))
        lat.append(round(BASE_LAT + radius * math.sin(ang), 6))
        lon.append(round(BASE_LON + radius * 1.3 * math.cos(ang), 6))
    return {"t": t, "d": d, "hr": hr, "alt": alt, "cad": cad, "spd": spd, "lat": lat, "lon": lon}


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
    db.init()
    today = date.today()
    start = today - timedelta(days=730)
    aid = 10_000_000_000
    fitness = 0.0
    day = start
    while day <= today:
        fitness = min(1.0, fitness + 0.0015)
        wd = day.weekday()
        plan = {1: "easy", 3: "tempo", 5: "easy", 6: "long"}.get(wd)
        if plan and random.random() < 0.88:
            base_pace = 345 - 40 * fitness
            if plan == "easy":
                km, pace, hr, name = random.uniform(6, 10), base_pace + 25, 142, "Rodaje suave"
            elif plan == "tempo":
                km, pace, hr, name = random.uniform(8, 12), base_pace - 20, 162, "Tempo"
            else:
                km, pace, hr, name = random.uniform(14, 22 + 8 * fitness), base_pace + 15, 150, "Tirada larga"
            if day.month == 4 and day.day in (20, 21) and plan == "long":
                km, pace, hr, name = 21.0975, base_pace - 25, 168, "Media Maratón de Madrid"
            stream = make_stream(km * 1000, pace, hr, hilly=(plan == "long"))
            hh = 7 + random.randint(0, 2) if wd >= 5 else 19
            st = datetime(day.year, day.month, day.day, hh, random.randint(0, 59))
            secs = stream["t"][-1]
            aid += 1
            load = round(secs / 60 * (1.3 if plan == "tempo" else 0.9) + random.gauss(0, 5), 1)
            db.upsert("activities", {
                "id": aid, "name": f"Madrid - {name}", "sport": "trail_running" if plan == "long" and random.random() < .2 else "running",
                "is_run": 1, "start_local": st.strftime("%Y-%m-%d %H:%M:%S"),
                "start_utc": (st - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "date": day.isoformat(),
                "distance_m": km * 1000, "duration_s": secs + 60, "moving_s": secs, "avg_speed": km * 1000 / secs,
                "max_speed": max(stream["spd"]), "avg_hr": sum(stream["hr"]) / len(stream["hr"]),
                "max_hr": max(stream["hr"]), "calories": km * 65, "elev_gain": 40 if plan != "long" else 160,
                "elev_loss": 40 if plan != "long" else 160, "cadence": 174, "aerobic_te": 3.1,
                "anaerobic_te": 1.2 if plan != "tempo" else 2.4, "training_load": load,
                "vo2max": round(48 + 6 * fitness), "start_lat": stream["lat"][0], "start_lon": stream["lon"][0],
                "source": "garmin", "fit_status": "ok", "raw": None}, "id")
            db.save_stream(aid, stream)
            metrics.store_derived(aid, stream)
        if (today - day).days < 180:
            sleep = random.gauss(7.2, 0.7) * 3600
            hrv = random.gauss(58 + 6 * fitness, 6)
            db.upsert("daily_health", {
                "user_id": 0, "date": day.isoformat(), "sleep_s": sleep, "sleep_score": int(min(98, max(40, random.gauss(78, 9)))),
                "deep_s": sleep * .18, "rem_s": sleep * .22, "light_s": sleep * .55, "awake_s": sleep * .05,
                "hrv_night": round(hrv), "hrv_weekly": round(58 + 6 * fitness), "hrv_status": "BALANCED",
                "hrv_low": 50, "hrv_high": 70, "rhr": round(random.gauss(50 - 4 * fitness, 1.5)),
                "bb_high": int(random.gauss(85, 8)), "bb_low": int(random.gauss(22, 6)), "bb_last": int(random.gauss(60, 15)),
                "stress_avg": int(random.gauss(30, 6)), "steps": int(random.gauss(11000, 3000)),
                "readiness": int(min(100, max(10, random.gauss(68, 15)))), "readiness_level": "MODERATE", "raw": None}, ("user_id", "date"))
        day += timedelta(days=1)
    db.upsert("snapshots", {"user_id": 0, "date": today.isoformat(), "vo2max": 54.0, "training_status": "PRODUCTIVE",
                            "status_phrase": "PRODUCTIVE_6", "acute_load": 540, "chronic_load": 480, "acwr": 1.1,
                            "race_5k": 1230, "race_10k": 2580, "race_hm": 5700, "race_m": 12100,
                            "raw": json.dumps({})}, ("user_id", "date"))
    db.set_setting(0, "garmin_email", "demo@ejemplo.com")
    print("Datos de demostración creados en", DB_PATH)


if __name__ == "__main__":
    main()

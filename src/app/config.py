"""Configuración general de Modo Guerrero."""
import os
from pathlib import Path

APP_NAME = "Modo Guerrero"
VERSION = os.getenv("APP_VERSION", "dev")

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "modo-guerrero.db"

# Clave para cifrar el token de Garmin. Si no se define, se genera un fichero en DATA_DIR.
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "")

# Pausa entre llamadas a Garmin (segundos) para no provocar bloqueos.
GARMIN_PAUSE = float(os.getenv("GARMIN_PAUSE", "1.0"))

# Valores por defecto de los ajustes editables desde la web.
DEFAULT_SETTINGS = {
    "sync_interval_min": 60,
    "health_backfill_days": 180,
    "fit_per_run": 40,
    "hr_max": None,
    "hr_rest": None,
    "weekly_goal_km": 30,
    "monthly_goal_km": 120,
    "yearly_goal_km": 1200,
    "theme": "auto",
    "accent": "#ff6b2c",
    "widgets": [
        {"id": "week", "visible": True, "wide": False},
        {"id": "fitness", "visible": True, "wide": False},
        {"id": "health", "visible": True, "wide": False},
        {"id": "last", "visible": True, "wide": False},
        {"id": "records", "visible": True, "wide": False},
        {"id": "month", "visible": True, "wide": False},
        {"id": "predictions", "visible": True, "wide": False},
        {"id": "weeks_chart", "visible": True, "wide": True},
    ],
}

# Distancias para mejores esfuerzos / récords (metros, etiqueta)
RECORD_DISTANCES = [
    (400, "400 m"),
    (1000, "1 km"),
    (1609.344, "1 milla"),
    (5000, "5 km"),
    (10000, "10 km"),
    (15000, "15 km"),
    (21097.5, "Media maratón"),
    (42195, "Maratón"),
]

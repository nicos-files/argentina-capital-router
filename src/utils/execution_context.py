from datetime import datetime
from typing import Optional
from pathlib import Path
import json
import os

def get_execution_date(date_str: Optional[str] = None) -> datetime:
    if date_str:
        return datetime.strptime(date_str, "%Y-%m-%d")
    return datetime.utcnow()

def get_execution_hour(hour_str: Optional[str] = None) -> Optional[str]:
    if hour_str:
        return hour_str
    return datetime.utcnow().strftime("%H%M")


def ensure_date_dir(base: Path, date: datetime, hour: Optional[str] = None) -> Path:
    target = base / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}"
    if hour:
        target = target / hour
    target.mkdir(parents=True, exist_ok=True)
    return target

def get_etl_args(log_path: Path = Path("data/logs/data_ready.json")) -> dict:
    try:
        with log_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "date": data.get("execution_date"),
            "hour": data.get("execution_hour")
        }
    except Exception as e:
        print(f"[WARNING] No se pudo leer data_ready.json: {e}")
        return {"date": None, "hour": None}

def get_current_args() -> dict:
    now = datetime.now()
    return {
        "date": now.strftime("%Y-%m-%d"),
        "hour": now.strftime("%H%M")
    }
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
import yaml, os

def now_tz(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))

def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

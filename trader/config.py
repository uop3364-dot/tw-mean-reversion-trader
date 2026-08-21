from __future__ import annotations
from pathlib import Path
import os, yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)

def settings() -> dict:
    load_dotenv(ROOT / ".env")
    cfg = load_yaml(ROOT / "config" / "strategy.yaml")
    cfg["broker"] = load_yaml(ROOT / "config" / "broker.yaml")
    return cfg

def live_enabled() -> bool:
    load_dotenv(ROOT / ".env")
    return os.getenv("LIVE_TRADING_ENABLED", "false").strip().lower() == "true"

def kill_switch() -> bool:
    load_dotenv(ROOT / ".env")
    return os.getenv("TRADING_KILL_SWITCH", "false").strip().lower() == "true"

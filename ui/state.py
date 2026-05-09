"""ui/state.py — Persistent config helpers."""

import os
import json

CONFIG_FILE = "dashboard_config.json"


def _load_config() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_config(data: dict):
    try:
        existing = _load_config()
        existing.update(data)
        with open(CONFIG_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass

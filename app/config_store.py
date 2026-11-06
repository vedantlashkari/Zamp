"""Load/save the editable policy config (thresholds + custom fields)."""
import json
import os

DEFAULT_CONFIG = {
    "tolerance_pass_pct": 2.0,
    "tolerance_flag_upper_pct": 10.0,
    "ocr_confidence_flag_threshold": 70,
    "custom_fields": [],
}


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        save_config(path, DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    with open(path) as f:
        cfg = json.load(f)
    return {**DEFAULT_CONFIG, **cfg}


def save_config(path: str, config: dict):
    with open(path, "w") as f:
        json.dump(config, f, indent=2)

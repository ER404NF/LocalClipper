"""Paths and settings. config.yaml (falls back to config.example.yaml) + toggles saved from the app."""
import json
import os
from pathlib import Path

from . import winenv  # noqa: F401  (must run first: UTF-8, tool paths, quiet subprocesses on Windows)
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("CLIPPERLOCAL_DATA", ROOT / "data"))   # database, logs, logins (private)
ASSETS = ROOT / "assets"                                          # all videos
SOURCES_DIR = ASSETS / "downloads"
CLIPS_DIR = ASSETS / "clips"
EXPORT_DIR = ASSETS / "export"
FILLER_DIR = ASSETS / "filler"                                    # your own background gameplay
BRAIN_DIR = ROOT / "brain"                                        # team memory, Markdown (Obsidian-compatible)
UI_DIR = ROOT / "desktop" / "ui"
PORT = int(os.environ.get("CLIPPERLOCAL_PORT", 8765))
PHONE_PORT = 8766
for d in (DATA, SOURCES_DIR, CLIPS_DIR, EXPORT_DIR, FILLER_DIR, BRAIN_DIR, DATA / "shots"):
    d.mkdir(parents=True, exist_ok=True)

SETTINGS = DATA / "settings.json"  # toggles changed from the app override config.yaml

DEFAULTS = {
    "team": {"model": "qwen3.5:9b", "coding_model": "qwen3-coder:30b", "parallel": 2, "ctx": 12288, "coding_ctx": 32768},
    "autopilot": {"enabled": False, "timezone": "Europe/Istanbul", "window_start": "16:00", "window_end": "22:00",
                  "max_per_account_per_day": 2, "require_italy_box": True, "min_score": 6.0, "gap_minutes": 15},
    "network": {"italy_box_proxy": "", "expect_country": "IT"},
    "phone": {"adb": "adb", "serial": "", "edits_package": ""},
    "research": {"provider": "ddgs", "brave_key": ""},
}


def load() -> dict:
    path = ROOT / "config.yaml"
    if not path.exists():
        path = ROOT / "config.example.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    for section, values in DEFAULTS.items():
        merged = dict(values)
        merged.update(cfg.get(section) or {})
        cfg[section] = merged
    if SETTINGS.exists():
        try:
            over = json.loads(SETTINGS.read_text(encoding="utf-8"))
            for section, values in over.items():
                cfg.setdefault(section, {}).update(values or {})
        except Exception:
            pass
    # the one team model also drives the classic agent + clip scoring
    cfg.setdefault("llm", {})
    cfg["llm"]["model"] = cfg["team"]["model"]
    return cfg


def save_setting(section: str, key: str, value):
    over = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
    over.setdefault(section, {})[key] = value
    SETTINGS.write_text(json.dumps(over, indent=2), encoding="utf-8")


def streamer(cfg: dict, name: str) -> dict | None:
    for s in cfg.get("streamers") or []:
        if s.get("name", "").lower() == (name or "").lower():
            return s
    return None

"""AI models page: what's installed in Ollama, downloads with progress, GPU memory."""
import json
import shutil
import subprocess
import threading

import requests

from . import config

PULLS: dict[str, dict] = {}
SUGGESTED = [
    {"name": "qwen3.5:9b", "note": "Agent + production crew · sees screenshots · fits 8 GB GPUs", "role": "team"},
    {"name": "qwen3.5:4b", "note": "Lighter team model for 4-6 GB GPUs", "role": "team"},
    {"name": "qwen3.6:27b", "note": "Smarter team model · needs a 24 GB GPU", "role": "team"},
    {"name": "qwen3-coder:30b", "note": "Coding crew · 19 GB, runs from GPU + system RAM (needs 32 GB RAM)", "role": "coding"},
]


def recommend(vram_gb: float, ram_gb: float) -> dict:
    """Which models fit this PC. 8 GB GPU + 32 GB RAM -> qwen3.5:9b for the crew, qwen3-coder:30b for coding."""
    team = "qwen3.6:27b" if vram_gb >= 22 else "qwen3.5:9b" if vram_gb >= 7 or (vram_gb == 0 and ram_gb >= 24) else "qwen3.5:4b"
    coding = "qwen3-coder:30b" if ram_gb + vram_gb >= 36 else team
    return {"model": team, "coding_model": coding}


def _url():
    return (config.load().get("llm") or {}).get("ollama_url", "http://127.0.0.1:11434")


def installed() -> list[dict]:
    try:
        r = requests.get(f"{_url()}/api/tags", timeout=3)
        return [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1)} for m in r.json().get("models", [])]
    except Exception:
        return []


def gpu() -> dict:
    if not shutil.which("nvidia-smi"):
        return {}
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip().splitlines()[0]
        name, used, total = [x.strip() for x in out.split(",")]
        return {"name": name, "used_gb": round(int(used) / 1024, 1), "total_gb": round(int(total) / 1024, 1)}
    except Exception:
        return {}


def pull(name: str):
    if PULLS.get(name, {}).get("state") == "downloading":
        return

    def go():
        PULLS[name] = {"state": "downloading", "pct": 0}
        try:
            with requests.post(f"{_url()}/api/pull", json={"name": name, "stream": True}, stream=True, timeout=None) as r:
                for line in r.iter_lines():
                    if not line:
                        continue
                    d = json.loads(line)
                    if d.get("total"):
                        PULLS[name]["pct"] = int(100 * d.get("completed", 0) / d["total"])
                    if d.get("error"):
                        raise RuntimeError(d["error"])
            PULLS[name] = {"state": "installed", "pct": 100}
        except Exception as e:
            PULLS[name] = {"state": "error", "error": str(e)[:200]}
    threading.Thread(target=go, daemon=True).start()


def overview() -> dict:
    from .team import ROLES
    from .tools import ALLOWED
    cfg = config.load()
    return {"team_model": cfg["team"]["model"], "coding_model": cfg["team"].get("coding_model") or cfg["team"]["model"],
            "parallel": cfg["team"].get("parallel", 2), "installed": installed(),
            "suggested": SUGGESTED, "pulls": PULLS, "gpu": gpu(),
            "roles": [{"key": k, "name": r["name"], "team": r["team"], "job": r["job"], "refuses": r["refuses"],
                       "tools": len(ALLOWED[k])} for k, r in ROLES.items()],
            "helpers": {"whisper": (cfg.get("whisper") or {}).get("model", "small"),
                        "vision": bool((cfg.get("browser") or {}).get("use_vision")),
                        "search": (cfg.get("research") or {}).get("provider", "ddgs")}}

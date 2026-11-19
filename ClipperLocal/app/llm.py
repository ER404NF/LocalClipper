"""Talks to the local Ollama server. Everything stays on this computer."""
import json
import re
import requests


def available(cfg) -> bool:
    try:
        url = (cfg.get("llm") or {}).get("ollama_url", "http://127.0.0.1:11434")
        return requests.get(f"{url}/api/tags", timeout=2).ok
    except Exception:
        return False


def ask_json(cfg, system: str, user: str) -> dict:
    llm = cfg.get("llm") or {}
    url = llm.get("ollama_url", "http://127.0.0.1:11434")
    body = {
        "model": llm.get("model", "qwen3:8b"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": "json",
        "stream": False,
        "think": False,
        "options": {"temperature": 0.6},
    }
    r = requests.post(f"{url}/api/chat", json=body, timeout=300)
    if r.status_code == 400 and "think" in r.text:  # model without a thinking switch
        body.pop("think")
        r = requests.post(f"{url}/api/chat", json=body, timeout=300)
    r.raise_for_status()
    text = r.json()["message"]["content"]
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    return json.loads(m.group(0) if m else text)


SCORE_SYSTEM = """You are a short-form video editor who clips GTA 6 livestreams for TikTok, Reels and YouTube Shorts.
You get a transcript window from a stream. Judge if it would make a viral short clip:
funny reactions, rage, shock, hype, chaotic gameplay moments, wild story moments, interactions with chat.
Boring talk, menus, silence, sponsor reads and loading screens score low.
Reply ONLY with JSON:
{"score": 1-10, "hook": "max 8 words of on-screen text that makes people keep watching, no hashtags",
 "title": "catchy post title under 70 chars",
 "description": "1-2 sentence caption with 3-5 relevant hashtags like #gta6",
 "reason": "why it is or isn't clip-worthy, 1 sentence"}"""

COMP_SYSTEM = """You write titles for GTA 6 compilation shorts (several ranked stream moments in one video).
Reply ONLY with JSON: {"title": "under 70 chars", "hook": "max 8 words", "description": "1-2 sentences + 3-5 hashtags"}"""


def score_window(cfg, streamer: str, transcript: str, signals: str) -> dict:
    user = (
        f"Streamer: {streamer}\nSignals: {signals}\n"
        f"Transcript:\n\"\"\"\n{transcript[:3000] or '(no speech detected)'}\n\"\"\""
    )
    try:
        d = ask_json(cfg, SCORE_SYSTEM, user)
        d["score"] = float(d.get("score", 0))
        return d
    except Exception as e:  # LLM offline -> fall back to simple text
        words = transcript.split()
        return {
            "score": 0,
            "hook": " ".join(words[:7]).upper() if words else "WAIT FOR IT...",
            "title": f"{streamer} in GTA 6",
            "description": "#gta6 #gtavi #gaming",
            "reason": f"LLM unavailable ({e.__class__.__name__}), heuristic score only",
        }


def compilation_meta(cfg, items: list[dict]) -> dict:
    listing = "\n".join(f"- {i['streamer']}: {i['hook']} / {i['title']}" for i in items)
    try:
        return ask_json(cfg, COMP_SYSTEM, f"Moments in this compilation:\n{listing}")
    except Exception:
        return {
            "title": f"Top {len(items)} GTA 6 stream moments today",
            "hook": f"TOP {len(items)} GTA 6 MOMENTS",
            "description": "#gta6 #gtavi #gaming #streamers",
        }

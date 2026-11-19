"""The Italy box: an always-on laptop in Turin running a small SOCKS5 proxy, reached through Tailscale.
Account tabs, uploads and the phone go through it so the accounts are always used from Italy."""
import threading
import time

import requests

from . import config

_cache = {"at": 0.0, "data": None}
_lock = threading.Lock()


def proxy_url(cfg=None) -> str:
    cfg = cfg or config.load()
    return (cfg.get("network") or {}).get("italy_box_proxy", "").strip()


def check(cfg=None) -> dict:
    cfg = cfg or config.load()
    p = proxy_url(cfg)
    want = (cfg.get("network") or {}).get("expect_country", "IT")
    out = {"configured": bool(p), "proxy": p, "online": False, "ip": "", "city": "", "country": "", "ok": False,
           "expect": want, "checked_at": time.time(), "error": ""}
    if not p:
        out["error"] = "No Italy box set. Add network.italy_box_proxy in Settings."
        return out
    px = p.replace("socks5://", "socks5h://")
    try:
        r = requests.get("https://ipinfo.io/json", proxies={"http": px, "https": px}, timeout=12)
        j = r.json()
        out.update(online=True, ip=j.get("ip", ""), city=j.get("city", ""), country=j.get("country", ""))
        out["ok"] = out["country"] == want
        if not out["ok"]:
            out["error"] = f"Traffic leaves from {out['country'] or '?'}, expected {want}"
    except Exception as e:
        out["error"] = f"Italy box not reachable: {e.__class__.__name__}"
    with _lock:
        _cache.update(at=time.time(), data=out)
    return out


def status(cached: bool = False) -> dict:
    with _lock:
        fresh = _cache["data"] and time.time() - _cache["at"] < 300
        data = _cache["data"]
    if cached:
        if not fresh:
            threading.Thread(target=check, daemon=True).start()
        return data or {"configured": bool(proxy_url()), "online": False, "ok": False, "error": "checking…"}
    return data if fresh else check()


def safe_to_post() -> tuple[bool, str]:
    cfg = config.load()
    if not cfg["autopilot"].get("require_italy_box", True):
        return True, "check disabled"
    s = check(cfg)
    return s["ok"], s.get("error") or f"{s['city']}, {s['country']}"

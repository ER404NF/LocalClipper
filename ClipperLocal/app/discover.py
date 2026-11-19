"""Find live GTA 6 streams and top clips via the official Twitch API."""
import time
from datetime import datetime, timedelta, timezone
import requests

_token = {"value": None, "exp": 0}
_game_id = {}
HELIX = "https://api.twitch.tv/helix"


def _headers(cfg):
    tw = cfg.get("twitch") or {}
    if not tw.get("client_id") or not tw.get("client_secret"):
        raise RuntimeError("Add twitch.client_id and twitch.client_secret to config.yaml")
    if not _token["value"] or time.time() > _token["exp"]:
        r = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": tw["client_id"],
                "client_secret": tw["client_secret"],
                "grant_type": "client_credentials",
            },
            timeout=20,
        )
        r.raise_for_status()
        j = r.json()
        _token["value"] = j["access_token"]
        _token["exp"] = time.time() + j.get("expires_in", 3600) - 60
    return {"Client-Id": tw["client_id"], "Authorization": f"Bearer {_token['value']}"}


def _get(cfg, path, params):
    r = requests.get(f"{HELIX}/{path}", headers=_headers(cfg), params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("data", [])


def game_id(cfg) -> str:
    name = (cfg.get("twitch") or {}).get("game_name", "Grand Theft Auto VI")
    if name not in _game_id:
        data = _get(cfg, "games", {"name": name})
        if not data:
            raise RuntimeError(f"Twitch has no game called '{name}'. Check twitch.game_name.")
        _game_id[name] = data[0]["id"]
    return _game_id[name]


def _allowed(cfg, login: str) -> bool:
    if not cfg.get("only_listed_streamers", True):
        return True
    names = {s.get("name", "").lower() for s in cfg.get("streamers") or []}
    return login.lower() in names


def live_streams(cfg) -> list[dict]:
    out = []
    for s in _get(cfg, "streams", {"game_id": game_id(cfg), "first": 100}):
        out.append(
            {
                "streamer": s["user_login"],
                "title": s["title"],
                "viewers": s["viewer_count"],
                "url": f"https://www.twitch.tv/{s['user_login']}",
                "kind": "live",
                "listed": _allowed(cfg, s["user_login"]),
                "thumb": s["thumbnail_url"].replace("{width}", "320").replace("{height}", "180"),
            }
        )
    out.sort(key=lambda x: (not x["listed"], -x["viewers"]))
    return out


def top_clips(cfg, hours: int = 24) -> list[dict]:
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for c in _get(cfg, "clips", {"game_id": game_id(cfg), "started_at": start, "first": 100}):
        out.append(
            {
                "streamer": c["broadcaster_name"].lower(),
                "title": c["title"],
                "viewers": c["view_count"],
                "duration": c["duration"],
                "url": c["url"],
                "kind": "clip",
                "listed": _allowed(cfg, c["broadcaster_name"]),
                "thumb": c["thumbnail_url"],
            }
        )
    out.sort(key=lambda x: (not x["listed"], -x["viewers"]))
    return out


def recent_vods(cfg, login: str, n: int = 5) -> list[dict]:
    users = _get(cfg, "users", {"login": login})
    if not users:
        return []
    vids = _get(cfg, "videos", {"user_id": users[0]["id"], "type": "archive", "first": n})
    return [
        {
            "streamer": login,
            "title": v["title"],
            "url": v["url"],
            "duration": v["duration"],
            "kind": "vod",
            "listed": _allowed(cfg, login),
            "thumb": v["thumbnail_url"].replace("%{width}", "320").replace("%{height}", "180"),
        }
        for v in vids
    ]

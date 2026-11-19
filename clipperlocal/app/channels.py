"""Connected accounts ("channels"). Two kinds:
- api:     posts automatically through the official API (after the user confirms)
- browser: has its own login window inside the app; the agent prepares the post,
           opens that account's upload page and shows the file, and the person posts it."""
import json
import time

from . import config, db

UPLOAD_URLS = {
    "youtube": "https://www.youtube.com/upload",
    "instagram": "https://www.instagram.com/",
    "tiktok": "https://www.tiktok.com/tiktokstudio/upload",
}
HOME_URLS = {
    "youtube": "https://studio.youtube.com/",
    "instagram": "https://www.instagram.com/accounts/login/",
    "tiktok": "https://www.tiktok.com/login",
}
PLATFORMS = tuple(UPLOAD_URLS)

# API credential fields per platform (shown as a form in the app)
API_FIELDS = {
    "youtube": ["client_secrets", "privacy"],
    "instagram": ["ig_user_id", "access_token", "graph_url"],
    "tiktok": ["access_token", "mode", "privacy_level"],
}


def _row(r: dict, source="app") -> dict:
    creds = json.loads(r.get("creds") or "{}")
    p = r["platform"]
    ok = r["method"] in ("browser", "phone") or all(
        creds.get(f) for f in API_FIELDS[p] if f not in ("privacy", "graph_url", "mode", "privacy_level")
    )
    return {
        "id": r.get("id"), "key": f"{p}:{r['name']}", "platform": p, "name": r["name"],
        "method": r["method"], "source": source, "ready": ok, "proxy": r.get("proxy") or "italy",
        "upload_url": UPLOAD_URLS[p], "home_url": HOME_URLS[p],
        "fields": {k: ("•••" if "token" in k and creds.get(k) else creds.get(k, "")) for k in API_FIELDS[p]}
        if r["method"] == "api" else {},
    }


def all_channels(cfg=None) -> list[dict]:
    cfg = cfg or config.load()
    out = [_row(r) for r in db.rows("SELECT * FROM channels ORDER BY platform, name")]
    have = {c["key"] for c in out}
    for p, lst in (cfg.get("accounts") or {}).items():
        for a in lst or []:
            if p in PLATFORMS and f"{p}:{a.get('name')}" not in have:
                out.append(_row({"platform": p, "name": a.get("name"), "method": "api",
                                 "creds": json.dumps(a)}, source="config.yaml"))
    return out


def get(key: str, cfg=None) -> dict | None:
    """Full channel incl. secrets, by 'platform:name'."""
    cfg = cfg or config.load()
    p, _, name = key.partition(":")
    r = db.one("SELECT * FROM channels WHERE platform=? AND name=?", (p, name))
    if r:
        return {**json.loads(r["creds"] or "{}"), "name": name, "platform": p, "method": r["method"]}
    for a in (cfg.get("accounts") or {}).get(p) or []:
        if a.get("name") == name:
            return {**a, "platform": p, "method": "api"}
    return None


def save(platform: str, name: str, method: str, creds: dict | None = None, proxy: str = "italy"):
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}")
    name = name.strip()
    if not name:
        raise ValueError("name required")
    old = db.one("SELECT * FROM channels WHERE platform=? AND name=?", (platform, name))
    merged = json.loads(old["creds"]) if old else {}
    for k, v in (creds or {}).items():
        if v not in (None, "", "•••"):
            merged[k] = v
    if platform == "youtube" and method == "api":
        merged.setdefault("client_secrets", "secrets/youtube_client.json")
        merged.setdefault("token_file", f"secrets/youtube_{name}_token.json")
    if method not in ("browser", "api", "phone"):
        raise ValueError("method must be browser, api or phone")
    if old:
        db.set_channel(old["id"], method=method, creds=json.dumps(merged), proxy=proxy)
    else:
        db.q("INSERT INTO channels(platform,name,method,creds,created_at,proxy) VALUES(?,?,?,?,?,?)",
             (platform, name, method, json.dumps(merged), time.time(), proxy))


def delete(cid: int):
    db.q("DELETE FROM channels WHERE id=?", (cid,))

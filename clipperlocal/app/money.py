"""Money: campaign earnings (entered or read by the crew) and progress toward platform payouts.
Platform numbers come from the crew reading each account's dashboard in its tab (or the API)."""
import re
import time

from . import browser_ctl, db, playbooks, team

GOALS = {  # platform: [(metric, goal, label)]
    "tiktok": [("followers", 10000, "Followers"), ("views_30d", 100000, "Views, last 30 days")],
    "youtube": [("subscribers", 1000, "Subscribers"), ("shorts_views_90d", 10_000_000, "Shorts views, last 90 days")],
    "instagram": [("followers", 0, "Followers"), ("plays_30d", 0, "Plays, last 30 days")],
}


def campaigns() -> list[dict]:
    return db.rows("SELECT * FROM campaigns ORDER BY id")


def save_campaign(name: str, streamer: str, rate: float, views: int = 0, earned: float = 0, status: str = "active",
                  cid: int | None = None):
    if cid:
        db.q("UPDATE campaigns SET name=?, streamer=?, rate=?, views=?, earned=?, status=?, updated_at=? WHERE id=?",
             (name, streamer, rate, views, earned, status, time.time(), cid))
    else:
        db.q("INSERT INTO campaigns(name,streamer,rate,views,earned,status,updated_at) VALUES(?,?,?,?,?,?,?)",
             (name, streamer, rate, views, earned, status, time.time()))


def latest(channel: str) -> dict:
    rows = db.rows("SELECT metric, value, goal, created_at FROM stats WHERE channel=? ORDER BY id DESC", (channel,))
    out = {}
    for r in rows:
        out.setdefault(r["metric"], r)
    return out


def summary() -> dict:
    from . import channels
    progress = []
    for ch in channels.all_channels():
        last = latest(ch["key"])
        metrics = [{"metric": m, "label": label, "value": last.get(m, {}).get("value"), "goal": goal}
                   for m, goal, label in GOALS.get(ch["platform"], [])]
        progress.append({"channel": ch["key"], "platform": ch["platform"], "metrics": metrics,
                         "checked_at": max((v["created_at"] for v in last.values()), default=None)})
    camps = campaigns()
    return {"campaigns": camps, "earned": round(sum(c["earned"] or 0 for c in camps), 2),
            "views": sum(c["views"] or 0 for c in camps), "progress": progress}


def _num(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"([\d.,]+)\s*([KkMm]?)", str(s))
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return n * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1)


def check_channel(key: str, who: str = "Clipper A") -> dict:
    t = browser_ctl.tab(key)
    res = browser_ctl.run_task(key, f"Read this account's stats: {', '.join(l for _, _, l in GOALS[t['platform']])}.",
                               who=who, hints=playbooks.tab_hint(t["platform"], "stats"), start_url=None, max_steps=15)
    if not res.get("ok"):
        return res
    wanted = [m for m, _, _ in GOALS[t["platform"]]]
    try:
        d = team.ask_json("Extract numbers from this report. JSON only, keys: " + ", ".join(wanted) +
                          ". Use null when a number isn't in the text. Don't guess.", res.get("result", ""))
    except Exception:
        d = {}
    saved = {}
    for m, goal, _ in GOALS[t["platform"]]:
        v = _num(d.get(m))
        if v is not None:
            db.q("INSERT INTO stats(channel,metric,value,goal,created_at) VALUES(?,?,?,?,?)", (key, m, v, goal, time.time()))
            saved[m] = v
    return {"ok": True, "read": res.get("result", ""), "saved": saved}

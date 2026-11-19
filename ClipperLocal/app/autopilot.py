"""Autopilot: the operator approves tomorrow's plan in the evening, the crew does the rest.

- TikTok / YouTube (browser channels): scheduled INSIDE the platform right after approval, so they go out
  even if the PC is off during school.
- Instagram via phone/Edits or Instagram web, and API channels: posted by the crew at the planned time (PC on).
Rules: posting window, max posts per account per day, never post without the Italy box, ask below a score."""
import json
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import browser_ctl, channels, config, db, network, pipeline, team

_started = False
_exec_lock = threading.Lock()


def tz():
    return ZoneInfo(config.load()["autopilot"].get("timezone", "Europe/Istanbul"))


def now():
    return datetime.now(tz())


def day_str(offset: int = 0) -> str:
    return (now() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _method(ch: dict) -> str:
    if ch["method"] == "api":
        return "api"
    if ch["method"] == "phone" or ch["platform"] == "instagram" and ch["method"] == "phone":
        return "phone"
    if ch["platform"] in ("tiktok", "youtube"):
        return "native"   # scheduled inside the platform tonight
    return "tab"          # posted from the account tab at the time


def build_plan(day: str | None = None) -> list[dict]:
    cfg = config.load()
    ap = cfg["autopilot"]
    day = day or day_str(1)
    db.q("DELETE FROM plan_items WHERE day=? AND status='draft'", (day,))
    clips = db.rows("SELECT c.*, s.streamer FROM clips c LEFT JOIN sources s ON s.id=c.source_id "
                    "WHERE c.status='approved' AND c.render_path IS NOT NULL ORDER BY c.score DESC")
    chans = sorted(channels.all_channels(cfg), key=lambda c: c["key"])
    if not clips or not chans:
        return []
    h, m = map(int, ap.get("window_start", "16:00").split(":"))
    eh, em = map(int, ap.get("window_end", "22:00").split(":"))
    gap = int(ap.get("gap_minutes", 15))
    slot = datetime.strptime(day, "%Y-%m-%d").replace(hour=h, minute=m)
    end = datetime.strptime(day, "%Y-%m-%d").replace(hour=eh, minute=em)
    per = int(ap.get("max_per_account_per_day", 2))
    used = {}
    items = []
    for round_ in range(per):
        for i, ch in enumerate(chans):
            for c in clips:
                if (ch["key"], c["id"]) in used:
                    continue
                camp = config.streamer(cfg, c["streamer"] or "") if c["streamer"] else None
                if camp and camp.get("allowed") and ch["platform"] not in camp["allowed"]:
                    continue
                if json.loads(c["posts"] or "{}").get(ch["key"], {}).get("ok"):
                    continue
                if slot > end:
                    break
                crew = "Clipper A" if i % 2 == 0 else "Clipper B"
                pid = db.q("INSERT INTO plan_items(day,at,channel,clip_id,method,crew,status,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                           (day, slot.strftime("%H:%M"), ch["key"], c["id"], _method(ch), crew, "draft", time.time())).lastrowid
                used[(ch["key"], c["id"])] = pid
                items.append(pid)
                slot += timedelta(minutes=gap)
                break
    return plan(day)


def plan(day: str | None = None) -> list[dict]:
    day = day or day_str(1)
    return db.rows("SELECT p.*, c.title, c.hook, c.score FROM plan_items p LEFT JOIN clips c ON c.id=p.clip_id "
                   "WHERE p.day=? ORDER BY p.at", (day,))


def approve(day: str | None = None) -> dict:
    day = day or day_str(1)
    items = plan(day)
    if not items:
        return {"error": "nothing planned for that day"}
    db.q("UPDATE plan_items SET status='waiting', updated_at=? WHERE day=? AND status IN ('draft','waiting')", (time.time(), day))
    team.post("clipper_a", f"Plan for {day} approved: {len(items)} posts. Scheduling the TikTok and YouTube ones inside the apps now.",
              room="production")
    threading.Thread(target=_schedule_natively, args=(day,), daemon=True).start()
    return {"ok": True, "items": len(items)}


def _caption(cfg, c):
    return pipeline.caption(cfg, c)


def _run_item(item: dict, schedule_for: str | None = None):
    cfg = config.load()
    c = db.one("SELECT * FROM clips WHERE id=?", (item["clip_id"],))
    key, who = item["channel"], item["crew"]
    db.q("UPDATE plan_items SET status='working', updated_at=? WHERE id=?", (time.time(), item["id"]))
    min_score = float(cfg["autopilot"].get("min_score", 0) or 0)
    if c and (c["score"] or 0) < min_score:
        db.q("UPDATE plan_items SET status='needs_you', message=? WHERE id=?", (f"score {c['score']:.1f} is under {min_score}", item["id"]))
        return
    ok, why = network.safe_to_post()
    if not ok and item["method"] != "api":
        db.q("UPDATE plan_items SET status='waiting', message=? WHERE id=?", (f"held: {why}", item["id"]))
        return
    caption, title = _caption(cfg, c), c["title"]
    try:
        if item["method"] == "api":
            pipeline.post(c["id"], key)
            fresh = json.loads(db.one("SELECT posts FROM clips WHERE id=?", (c["id"],))["posts"])
            res = {"ok": fresh.get(key, {}).get("ok"), "error": fresh.get(key, {}).get("msg")}
        elif item["method"] == "phone":
            from . import android
            ch = channels.get(key, cfg) or {}
            res = android.post_reel(browser_ctl.clip_file(c["id"], "reels"), caption, ch.get("name", key), None, who)
        else:
            res = browser_ctl.post(key, c["id"], caption, title, schedule_for, who)
    except Exception as e:
        res = {"ok": False, "error": str(e)}
    if res.get("ok"):
        status = "scheduled" if schedule_for else "posted"
        db.q("UPDATE plan_items SET status=?, message=?, updated_at=? WHERE id=?", (status, res.get("result", "")[:300], time.time(), item["id"]))
        pipeline.mark_posted(c["id"], key, f"{status} by {who}")
    elif res.get("needs_human"):
        db.q("UPDATE plan_items SET status='needs_you', message=? WHERE id=?", (res["needs_human"][:300], item["id"]))
    else:
        db.q("UPDATE plan_items SET status='failed', message=? WHERE id=?", ((res.get("error") or "failed")[:300], item["id"]))


def _schedule_natively(day: str):
    items = [i for i in plan(day) if i["method"] == "native" and i["status"] == "waiting"]
    by_crew = {"Clipper A": [], "Clipper B": []}
    for i in items:
        by_crew.setdefault(i["crew"], []).append(i)

    def go(lst):
        for i in lst:
            if browser_ctl.PAUSED.is_set():
                return
            when = f"{day} {i['at']} ({config.load()['autopilot'].get('timezone')})"
            _run_item(i, schedule_for=when)

    ts = [threading.Thread(target=go, args=(lst,), daemon=True) for lst in by_crew.values() if lst]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    team.post("clipper_a", "Native scheduling done. The rest goes out at its time.", room="production")


def _loop():
    while True:
        time.sleep(30)
        try:
            cfg = config.load()
            if not cfg["autopilot"].get("enabled") or browser_ctl.PAUSED.is_set():
                continue
            t = now()
            due = db.rows("SELECT * FROM plan_items WHERE day=? AND status='waiting' AND method!='native' AND at<=?",
                          (t.strftime("%Y-%m-%d"), t.strftime("%H:%M")))
            for item in due:
                with _exec_lock:
                    _run_item(item)
            if t.strftime("%H:%M") >= "22:15" and not db.one("SELECT day FROM reports WHERE day=?", (t.strftime("%Y-%m-%d"),)):
                write_report(t.strftime("%Y-%m-%d"))
        except Exception as e:
            print("autopilot loop:", e)


def start():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True).start()


def pause_all(paused: bool = True):
    (browser_ctl.PAUSED.set if paused else browser_ctl.PAUSED.clear)()


def summary() -> dict:
    cfg = config.load()
    return {"enabled": bool(cfg["autopilot"].get("enabled")), "paused": browser_ctl.PAUSED.is_set(),
            "timezone": cfg["autopilot"].get("timezone"), "today": plan(day_str(0)), "tomorrow": plan(day_str(1)),
            "italy_box": network.status(cached=True)}


def write_report(day: str | None = None) -> dict:
    from . import money
    day = day or day_str(0)
    items = plan(day)
    done = [i for i in items if i["status"] in ("posted", "scheduled")]
    data = {"day": day, "planned": len(items), "posted": len(done), "items": items,
            "failed": [i for i in items if i["status"] in ("failed", "needs_you")],
            "italy_box": network.status(cached=True), "money": money.summary(),
            "notes": [r["content"] for r in db.rows("SELECT content FROM chat WHERE room='production' AND role='assistant' "
                                                    "AND created_at>? ORDER BY id DESC LIMIT 6", (time.time() - 86400,))]}
    db.q("INSERT OR REPLACE INTO reports(day,data,created_at) VALUES(?,?,?)", (day, json.dumps(data, default=str), time.time()))
    return data


def report(day: str | None = None) -> dict:
    day = day or day_str(0)
    r = db.one("SELECT data FROM reports WHERE day=?", (day,))
    return json.loads(r["data"]) if r else write_report(day)


def publish_now(clip_ids: list[int], keys: list[str]) -> dict:
    """Operator-confirmed publish outside the plan: runs right away, crews split the accounts."""
    cfg = config.load()
    known = {c["key"]: c for c in channels.all_channels(cfg)}
    day, at = day_str(0), now().strftime("%H:%M")
    started = []
    for n, key in enumerate(keys):
        ch = known.get(key)
        if not ch:
            continue
        crew = "Clipper A" if n % 2 == 0 else "Clipper B"
        method = _method(ch)
        for cid in clip_ids:
            pid = db.q("INSERT INTO plan_items(day,at,channel,clip_id,method,crew,status,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                       (day, at, key, cid, "tab" if method == "native" else method, crew, "waiting", time.time())).lastrowid
            started.append(pid)

    def go(ids):
        for pid in ids:
            item = db.one("SELECT * FROM plan_items WHERE id=?", (pid,))
            with _exec_lock:
                _run_item(item)
    threading.Thread(target=go, args=(started,), daemon=True).start()
    return {"ok": True, "started": len(started)}

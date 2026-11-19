"""ClipperLocal engine API (used by the desktop app; also works in a normal browser).
Run: python -m app.server   ->  http://127.0.0.1:8765"""
import json
import os
import subprocess
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (autopilot, brain, browser_ctl, channels, codecrew, config, crew, db, discover, llm, models, money,
               network, phone, pipeline, team, tools)

app = FastAPI(title="ClipperLocal engine")
TRUSTED_ORIGINS = {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
                   f"http://127.0.0.1:{config.PORT}", f"http://localhost:{config.PORT}", "http://127.0.0.1:8798", "null"}
app.add_middleware(CORSMiddleware, allow_origins=sorted(TRUSTED_ORIGINS - {"null"}), allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def only_our_screens(request, call_next):
    """Websites open in a normal browser can't drive the engine: requests that change things must come from the app."""
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in TRUSTED_ORIGINS:
        return Response("Forbidden", status_code=403)
    return await call_next(request)
app.mount("/media", StaticFiles(directory=config.CLIPS_DIR), name="media")


def _cfg():
    return config.load()


# ------------------------------------------------------------------ status
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status():
    cfg = _cfg()
    tw = cfg.get("twitch") or {}
    return {"config_file": "config.yaml" if (config.ROOT / "config.yaml").exists() else "config.example.yaml",
            "ffmpeg": bool(shutil.which("ffmpeg")), "ollama": llm.available(cfg), "model": cfg["team"]["model"],
            "coding_model": cfg["team"].get("coding_model") or cfg["team"]["model"],
            "preview": os.environ.get("CLIPPERLOCAL_PREVIEW") == "1", "git": codecrew.git_ok(),
            "twitch": bool(tw.get("client_id") and tw.get("client_secret")),
            "monetization_mode": bool((cfg.get("clipping") or {}).get("monetization_mode")),
            "layout": (cfg.get("render") or {}).get("layout", "blur"), "queue": pipeline.queue_size(),
            "channels": channels.all_channels(cfg), "streamers": [s.get("name") for s in cfg.get("streamers") or []],
            "assets": str(config.ASSETS), "italy_box": network.status(cached=True),
            "autopilot": {"enabled": bool(cfg["autopilot"].get("enabled")), "paused": browser_ctl.PAUSED.is_set()},
            "accent": (cfg.get("ui") or {}).get("accent", "#2F7BFF"),
            "review_count": db.one("SELECT COUNT(*) n FROM clips WHERE status IN ('ready','edited')")["n"]}


@app.get("/api/board")
def board():
    return pipeline.board()


SETTABLE = {("clipping", "monetization_mode"), ("clipping", "clips_per_source"), ("render", "layout"), ("render", "watermark"),
            ("render", "captions"), ("team", "model"), ("team", "coding_model"), ("team", "parallel"), ("network", "italy_box_proxy"),
            ("network", "expect_country"), ("phone", "serial"), ("phone", "edits_package"), ("research", "provider"),
            ("research", "brave_key"), ("browser", "use_vision"), ("browser", "mode"), ("ui", "accent"),
            ("autopilot", "enabled"), ("autopilot", "timezone"), ("autopilot", "window_start"), ("autopilot", "window_end"),
            ("autopilot", "max_per_account_per_day"), ("autopilot", "require_italy_box"), ("autopilot", "min_score"),
            ("autopilot", "gap_minutes")}


class Setting(BaseModel):
    section: str
    key: str
    value: bool | str | int | float


@app.post("/api/settings")
def set_setting(s: Setting):
    if (s.section, s.key) not in SETTABLE:
        raise HTTPException(400, "not changeable from the app")
    config.save_setting(s.section, s.key, s.value)
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    cfg = _cfg()
    return {sec: {k: cfg.get(sec, {}).get(k) for (s2, k) in SETTABLE if s2 == sec} for sec in {s for s, _ in SETTABLE}}


# ------------------------------------------------------------------ chat rooms
def _chat_rows(room: str, after: int = 0):
    rows = db.rows("SELECT * FROM chat WHERE room=? AND id>? ORDER BY id", (room, after))
    actions = {a["id"]: a for a in db.rows("SELECT * FROM actions")}
    for r in rows:
        r["data"] = json.loads(r["data"] or "{}")
        aid = r["data"].get("action_id")
        if aid and aid in actions:
            a = actions[aid]
            r["action"] = {"id": aid, "status": a["status"], "summary": a["summary"]}
    return rows


@app.get("/api/chat")
def get_chat(room: str = "agent", after: int = 0):
    return _chat_rows(room, after)


class Msg(BaseModel):
    text: str
    room: str = "agent"


@app.post("/api/chat")
def post_chat(m: Msg):
    if m.room not in team.TEAM_OF_ROOM or not m.text.strip():
        raise HTTPException(400, "bad room or empty message")
    first = team.say(m.room, m.text.strip())
    return {"ok": True, "id": first}


@app.delete("/api/chat")
def clear_chat(room: str = "agent"):
    db.q("DELETE FROM chat WHERE room=?", (room,))
    return {"ok": True}


@app.post("/api/actions/{aid}/confirm")
def confirm(aid: int):
    a = db.one("SELECT * FROM actions WHERE id=?", (aid,))
    if not a or a["status"] != "pending":
        raise HTTPException(400, "already handled")
    p = json.loads(a["payload"])
    db.q("UPDATE actions SET status='confirmed' WHERE id=?", (aid,))
    db.add_chat("event", f"Operator confirmed publish request {aid}.", room="production")
    return autopilot.publish_now(p["clip_ids"], p["channels"])


@app.post("/api/actions/{aid}/cancel")
def cancel(aid: int):
    db.q("UPDATE actions SET status='cancelled' WHERE id=? AND status='pending'", (aid,))
    db.add_chat("event", f"Operator cancelled publish request {aid}.", room="production")
    return {"ok": True}


# ------------------------------------------------------------------ production crew
class Hunt(BaseModel):
    request: str = ""
    streamers: list[str] = []


@app.post("/api/crew/hunt")
def crew_hunt(h: Hunt):
    threading.Thread(target=crew.hunt, args=(h.request, h.streamers), daemon=True).start()
    return {"ok": True}


class Ids(BaseModel):
    clip_ids: list[int]


@app.post("/api/crew/edit")
def crew_edit(i: Ids):
    threading.Thread(target=crew.edit_parallel, args=(i.clip_ids,), daemon=True).start()
    return {"ok": True}


class Feedback(BaseModel):
    text: str
    clip_id: int | None = None
    target: str = ""


@app.post("/api/crew/feedback")
def crew_feedback(f: Feedback):
    if f.clip_id:
        threading.Thread(target=crew.feedback, args=(f.clip_id, f.text), daemon=True).start()
    else:
        db.q("INSERT INTO feedback(target,text,created_at) VALUES(?,?,?)", (f.target, f.text, time.time()))
        team.say("production", f"Feedback{' on ' + f.target if f.target else ''}: {f.text}")
    return {"ok": True}


# ------------------------------------------------------------------ discovery + sources
@app.get("/api/discover/{what}")
def find(what: str, streamer: str = ""):
    cfg = _cfg()
    try:
        return {"live": discover.live_streams, "clips": discover.top_clips}[what](cfg) if what != "vods" \
            else discover.recent_vods(cfg, streamer)
    except KeyError:
        raise HTTPException(404)
    except Exception as e:
        raise HTTPException(400, str(e))


class NewSource(BaseModel):
    url: str
    kind: str = "vod"
    streamer: str = ""
    title: str = ""
    start: float | None = None
    end: float | None = None
    minutes: int | None = None


@app.post("/api/sources")
def add_source(s: NewSource):
    cfg = _cfg()
    if cfg.get("only_listed_streamers", True) and s.kind != "file" and not config.streamer(cfg, s.streamer):
        raise HTTPException(400, f"'{s.streamer}' isn't in your streamers list in config.yaml")
    sid = db.add_source(s.url, s.kind, s.streamer.lower(), s.title, {"start": s.start, "end": s.end, "minutes": s.minutes})
    pipeline.submit(pipeline.process_source, sid)
    return {"id": sid}


@app.post("/api/sources/{sid}/retry")
def retry(sid: int):
    db.set_source(sid, status="queued", message="")
    pipeline.submit(pipeline.process_source, sid)
    return {"ok": True}


# ------------------------------------------------------------------ clips
@app.get("/api/clips")
def list_clips(status: str = ""):
    sql = "SELECT c.*, s.streamer FROM clips c LEFT JOIN sources s ON s.id=c.source_id"
    statuses = [x for x in status.split(",") if x]
    r = (db.rows(sql + f" WHERE c.status IN ({','.join('?' * len(statuses))}) ORDER BY c.score DESC, c.id DESC", tuple(statuses))
         if statuses else db.rows(sql + " ORDER BY c.id DESC LIMIT 300"))
    for c in r:
        c["posts"] = json.loads(c["posts"] or "{}")
        c["review"] = json.loads(c["review"] or "{}")
        variants = json.loads(c["variants"] or "{}")
        c["variants"] = {k: f"/media/{c['id']}/{Path(v).name}" for k, v in variants.items()}
        c["video"] = f"/media/{c['id']}/{Path(c['render_path']).name}" if c["render_path"] else None
        c["length"] = round((c["end"] or 0) - (c["start"] or 0), 1)
    return r


class ClipEdit(BaseModel):
    hook: str | None = None
    title: str | None = None
    description: str | None = None
    status: str | None = None
    start: float | None = None
    end: float | None = None
    layout: str | None = None


@app.patch("/api/clips/{cid}")
def edit_clip(cid: int, e: ClipEdit):
    old = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    if not old:
        raise HTTPException(404)
    changes = {k: v for k, v in e.model_dump().items() if v is not None}
    db.set_clip(cid, **changes)
    needs = any(k in changes and changes[k] != old[k] for k in ("hook", "start", "end", "layout"))
    if needs and not old["is_compilation"]:
        if old["editor"]:
            role = crew.ROLE_OF.get(old["editor"], crew.A)
            threading.Thread(target=crew.edit_one, args=(cid, role, changes.get("layout") or old["layout"] or None),
                             daemon=True).start()
        else:
            pipeline.submit(pipeline.rerender, cid)
    return {"ok": True, "rerender": needs}


@app.post("/api/compilation")
def compile_(i: Ids):
    if len(i.clip_ids) < 2:
        raise HTTPException(400, "Pick at least 2 clips")
    pipeline.submit(pipeline.make_compilation, i.clip_ids)
    return {"ok": True}


class Publish(BaseModel):
    channels: list[str]


@app.post("/api/clips/{cid}/publish")
def publish(cid: int, p: Publish):
    res = tools.publish_request(_cfg(), [cid], p.channels)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    db.q("UPDATE actions SET status='confirmed' WHERE id=?", (res["action_id"],))
    return autopilot.publish_now([cid], p.channels)


class Posted(BaseModel):
    key: str
    link: str = ""


@app.post("/api/clips/{cid}/mark_posted")
def mark_posted(cid: int, p: Posted):
    pipeline.mark_posted(cid, p.key, p.link)
    return {"ok": True}


@app.post("/api/clips/{cid}/export")
def export(cid: int):
    return {"path": str(pipeline.export(cid))}


@app.post("/api/clips/{cid}/phone")
def to_phone(cid: int):
    c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    if not c or not c["render_path"]:
        raise HTTPException(400, "clip not rendered yet")
    return phone.share(pipeline.export(cid), f"{c['title']}\n\n{pipeline.caption(_cfg(), c)}")


# ------------------------------------------------------------------ channels + tabs (browser)
@app.get("/api/channels")
def list_channels():
    out = channels.all_channels()
    for c in out:
        c["stats"] = money.latest(c["key"])
    return out


class Channel(BaseModel):
    platform: str
    name: str
    method: str = "browser"
    creds: dict = {}
    proxy: str = "italy"


@app.post("/api/channels")
def save_channel(c: Channel):
    try:
        channels.save(c.platform, c.name, c.method, c.creds, c.proxy)
    except ValueError as e:
        raise HTTPException(400, str(e))
    browser_ctl.APP_COMMANDS.append({"cmd": "reload_tabs"})
    return {"ok": True}


@app.delete("/api/channels/{cid}")
def delete_channel(cid: int):
    channels.delete(cid)
    browser_ctl.APP_COMMANDS.append({"cmd": "reload_tabs"})
    return {"ok": True}


@app.get("/api/tabs")
def tabs():
    busy = {r["place"][4:]: r for r in db.rows(
        "SELECT * FROM activity WHERE id IN (SELECT MAX(id) FROM activity WHERE place LIKE 'tab:%' GROUP BY place)")}
    out = browser_ctl.tabs()
    for t in out:
        last = busy.get(t["key"])
        t["agent"] = last["who"] if last and last["state"] in ("now", "done", "retry") and time.time() - last["created_at"] < 120 else ""
        t["last"] = last
    return out


@app.get("/api/tabs/{key}/shot")
def tab_shot(key: str):
    f = config.DATA / "shots" / f"tab_{key.replace(':', '_')}.jpg"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "no-store"})


@app.get("/api/tabs/{key}/activity")
def tab_activity(key: str):
    return browser_ctl.activity(key)


@app.post("/api/tabs/{key}/takeover")
def tab_takeover(key: str):
    browser_ctl.take_over(key)
    return {"ok": True}


class Task(BaseModel):
    goal: str
    who: str = "Clipper A"


@app.post("/api/tabs/{key}/task")
def tab_task(key: str, t: Task):
    threading.Thread(target=browser_ctl.run_task, args=(key, t.goal), kwargs={"who": t.who}, daemon=True).start()
    return {"ok": True}


@app.get("/api/app/commands")
def app_commands():
    out = list(browser_ctl.APP_COMMANDS)
    browser_ctl.APP_COMMANDS.clear()
    return out


# ------------------------------------------------------------------ phone
_phone_cache = {"at": 0, "data": None}


@app.get("/api/phone/status")
def phone_status():
    from . import android
    if time.time() - _phone_cache["at"] > 10:
        _phone_cache.update(at=time.time(), data=android.status())
    return _phone_cache["data"]


@app.get("/api/phone/shot")
def phone_shot(fresh: bool = False):
    from . import android
    f = config.DATA / "shots" / "phone.png"
    if fresh:
        try:
            f = android.screenshot()
        except Exception:
            pass
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "no-store"})


@app.get("/api/phone/activity")
def phone_activity():
    return db.rows("SELECT * FROM activity WHERE place='phone' ORDER BY id DESC LIMIT 25")


@app.post("/api/phone/task")
def phone_task(t: Task):
    from . import android
    threading.Thread(target=android.run_task, args=(t.goal,), kwargs={"who": t.who, "open_edits": False}, daemon=True).start()
    return {"ok": True}


# ------------------------------------------------------------------ network
@app.get("/api/network")
def network_check():
    return network.check()


# ------------------------------------------------------------------ autopilot + report
@app.get("/api/autopilot")
def ap_summary():
    return autopilot.summary()


class Day(BaseModel):
    day: str | None = None


@app.post("/api/autopilot/plan")
def ap_plan(d: Day):
    return autopilot.build_plan(d.day)


@app.post("/api/autopilot/approve")
def ap_approve(d: Day):
    return autopilot.approve(d.day)


class Flag(BaseModel):
    on: bool


@app.post("/api/autopilot/pause")
def ap_pause(f: Flag):
    autopilot.pause_all(f.on)
    db.add_chat("event", "Operator paused everything." if f.on else "Operator resumed.", room="production")
    return {"ok": True, "paused": f.on}


@app.post("/api/autopilot/enabled")
def ap_enabled(f: Flag):
    config.save_setting("autopilot", "enabled", f.on)
    return {"ok": True}


class PlanEdit(BaseModel):
    at: str | None = None
    status: str | None = None


@app.patch("/api/autopilot/items/{pid}")
def ap_item(pid: int, e: PlanEdit):
    ch = {k: v for k, v in e.model_dump().items() if v is not None}
    if "status" in ch and ch["status"] not in ("skipped", "waiting", "draft"):
        raise HTTPException(400, "status can be skipped, waiting or draft")
    db._set("plan_items", pid, ch)
    return {"ok": True}


@app.get("/api/report")
def get_report(day: str | None = None, refresh: bool = False):
    return autopilot.write_report(day) if refresh else autopilot.report(day)


# ------------------------------------------------------------------ trends + money
@app.get("/api/trends")
def get_trends():
    r = db.rows("SELECT * FROM trends ORDER BY id DESC LIMIT 40")
    for t in r:
        t["sources"] = json.loads(t["sources"] or "[]")
    return r


class Q(BaseModel):
    question: str = ""


@app.post("/api/trends/research")
def research_now(q: Q):
    ask = q.question or ("Research how the biggest GTA 6 clip accounts are editing and posting short clips this week "
                         "(formats, hooks, captions, sounds, timing). Search the web, read 3-5 good sources, then save each "
                         "useful finding with save_trend including source links. Report briefly.")
    team.say("production", "@ClipperB " + ask)
    return {"ok": True}


@app.post("/api/trends/{tid}/use")
def trend_use(tid: int):
    t = db.one("SELECT * FROM trends WHERE id=?", (tid,))
    db.q("UPDATE trends SET status='used' WHERE id=?", (tid,))
    if t:
        brain.append("Formats", f"Trying: {t['title']} - {t['body'][:160]}", "production", "Clipper A", "production")
    return {"ok": True}


@app.get("/api/money")
def get_money():
    return money.summary()


class Camp(BaseModel):
    name: str
    streamer: str = ""
    rate: float = 0
    views: int = 0
    earned: float = 0
    status: str = "active"
    id: int | None = None


@app.post("/api/money/campaigns")
def save_campaign(c: Camp):
    money.save_campaign(c.name, c.streamer, c.rate, c.views, c.earned, c.status, c.id)
    return {"ok": True}


class ChanKey(BaseModel):
    channel: str


@app.post("/api/money/check")
def money_check(c: ChanKey):
    threading.Thread(target=money.check_channel, args=(c.channel,), daemon=True).start()
    return {"ok": True}


# ------------------------------------------------------------------ brain
@app.get("/api/brain/graph")
def brain_graph():
    return brain.graph()


@app.get("/api/brain/note/{slug}")
def brain_note(slug: str):
    n = brain.get(slug)
    if not n:
        raise HTTPException(404)
    return n


class Note(BaseModel):
    title: str
    body: str
    team: str = "shared"


@app.post("/api/brain/note")
def brain_save(n: Note):
    try:
        return brain.write(n.title, n.body, n.team, "Operator", n.team)  # the operator may edit any area
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, str(e))


@app.delete("/api/brain/note/{slug}")
def brain_forget(slug: str):
    brain.forget(slug)
    return {"ok": True}


@app.post("/api/brain/note/{slug}/pin")
def brain_pin(slug: str, f: Flag):
    brain.pin(slug, f.on)
    return {"ok": True}


# ------------------------------------------------------------------ models + formats
@app.get("/api/models")
def get_models():
    return models.overview()


class Name(BaseModel):
    name: str


@app.post("/api/models/pull")
def pull_model(n: Name):
    models.pull(n.name)
    return {"ok": True}


@app.get("/api/formats")
def formats():
    from .edit import SAFE
    return {"platforms": {"tiktok": {"size": "1080x1920", "safe": SAFE["tiktok"]}, "reels": {"size": "1080x1920", "safe": SAFE["reels"]},
                          "shorts": {"size": "1080x1920", "safe": SAFE["shorts"]}},
            "layouts": ["blur", "facecam", "split", "crop", "bubble"],
            "filler": [p.name for p in config.FILLER_DIR.glob("*") if p.is_file()], "filler_dir": str(config.FILLER_DIR)}


# ------------------------------------------------------------------ coding crew
@app.get("/api/changes")
def list_changes():
    return [codecrew.get(r["id"]) for r in db.rows("SELECT id FROM changes ORDER BY id DESC LIMIT 30")]


@app.get("/api/changes/{cid}")
def get_change(cid: int):
    c = codecrew.get(cid)
    if not c:
        raise HTTPException(404)
    return c


@app.get("/api/changes/{cid}/concept/{i}", response_class=HTMLResponse)
def concept(cid: int, i: int, accent: str = "#2F7BFF"):
    body = codecrew.concept_html(cid, i)
    return f"""<!doctype html><meta charset=utf-8><style>:root{{--accent:{accent}}}body{{margin:0;background:#0A0A0A;color:#F2EEE3;
font:14px/1.45 Inter,system-ui,sans-serif}}</style>{body}"""


class Choose(BaseModel):
    concept: int | None = None


@app.post("/api/changes/{cid}/build")
def change_build(cid: int, c: Choose):
    db.add_chat("user", f"Build change #{cid}" + (f" with concept {c.concept + 1}" if c.concept is not None else ""), room="coding")
    threading.Thread(target=codecrew.build, args=(cid, c.concept), daemon=True).start()
    return {"ok": True}


@app.post("/api/changes/{cid}/apply")
def change_apply(cid: int):
    return codecrew.apply(cid)


@app.post("/api/changes/{cid}/undo")
def change_undo(cid: int):
    return codecrew.undo(cid)


@app.post("/api/changes/{cid}/discard")
def change_discard(cid: int):
    return codecrew.discard(cid)


@app.post("/api/changes/{cid}/preview")
def change_preview(cid: int):
    return codecrew.preview_start(cid)


@app.delete("/api/changes/preview")
def change_preview_stop():
    codecrew.preview_stop()
    return {"ok": True}


@app.post("/api/restart")
def restart():
    """Restart the engine (used when the app runs without the desktop shell). The new engine waits for the port."""
    if os.environ.get("CLIPPERLOCAL_PREVIEW") == "1":
        return {"error": "preview engines don't restart"}
    codecrew.preview_stop()
    args = [a for a in sys.argv[1:] if a != "--no-browser"] + ["--no-browser"]
    subprocess.Popen([sys.executable, "-m", "app.server", *args], cwd=config.ROOT, env={**os.environ, "CLIPPERLOCAL_WAIT_PORT": "1"})
    threading.Timer(0.6, lambda: os._exit(0)).start()
    return {"ok": True}


@app.post("/api/shutdown")
def shutdown():
    codecrew.preview_stop()
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return {"ok": True}


@app.get("/api/changes/{cid}/diff", response_class=Response)
def change_diff(cid: int):
    return Response(codecrew.diff(cid), media_type="text/plain")


# UI last, so it doesn't shadow the API
app.mount("/", StaticFiles(directory=config.UI_DIR, html=True), name="ui")


def _wait_for_port(port: int, seconds: float = 15):
    import socket
    end = time.time() + seconds
    while time.time() < end:
        with socket.socket() as sk:
            if sk.connect_ex(("127.0.0.1", port)) != 0:
                return
        time.sleep(0.3)


def main():
    import uvicorn
    if os.environ.pop("CLIPPERLOCAL_WAIT_PORT", None):
        _wait_for_port(config.PORT)
    cfg = config.load()
    if os.environ.get("CLIPPERLOCAL_PREVIEW") != "1":
        from . import winenv
        threading.Thread(target=winenv.ensure_ollama, kwargs={"url": cfg["llm"].get("ollama_url", "http://127.0.0.1:11434"),
                                                             "parallel": int(cfg["team"].get("parallel") or 2)},
                         daemon=True).start()
        threading.Thread(target=codecrew.ensure_repo, daemon=True).start()
    if "--no-workers" not in sys.argv:
        pipeline.start()
        phone.start()
        autopilot.start()
    url = f"http://127.0.0.1:{config.PORT}"
    print(f"\n  ClipperLocal engine running at {url}\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()

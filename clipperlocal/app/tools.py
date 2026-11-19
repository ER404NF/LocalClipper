"""Every tool the agents can use, and which agent may use which (job boundaries live here)."""
import json
import threading
import time

from . import brain, channels, config, db, discover, phone, pipeline
from .team import ROLES

_found: dict[str, dict] = {}

S = lambda **props: {"type": "object", "properties": props}
STR, INT, NUM, BOOL = {"type": "string"}, {"type": "integer"}, {"type": "number"}, {"type": "boolean"}
ARR = lambda t: {"type": "array", "items": t}

SCHEMAS = {
    # --- shared
    "status": ("Overview: AI/Twitch/Italy box health, streamers, channels, clip counts, settings.", S()),
    "pipeline": ("What is in Finding, Clipping, Editing and Publishing right now.", S()),
    "list_clips": ("List clips. status: ready (needs review), approved, posted, rejected, all.",
                   S(status={"type": "string", "enum": ["ready", "approved", "posted", "rejected", "all"]}, limit=INT)),
    "handoff": ("Pass a request that isn't your job to the right crew (production or coding) or the agent.",
                {**S(to={"type": "string", "enum": ["agent", "production", "coding"]}, request=STR), "required": ["to", "request"]}),
    "brain_search": ("Search the shared brain (team memory).", {**S(query=STR), "required": ["query"]}),
    "brain_read": ("Read one brain note by its title.", {**S(title=STR), "required": ["title"]}),
    "brain_write": ("Create or replace a brain note in your team's area. Use [[Other note]] to link notes.",
                    {**S(title=STR, body=STR), "required": ["title", "body"]}),
    "brain_learn": ("Save a short lesson learned (goes in 'Hooks that worked' or another learning note).",
                    {**S(lesson=STR, note=STR), "required": ["lesson"]}),
    # --- production
    "find_videos": ("Search Twitch for GTA 6 content: live, clips (top 24h) or vods (one streamer). Returns refs v1, v2...",
                    {**S(kind={"type": "string", "enum": ["live", "clips", "vods"]}, streamer=STR, limit=INT), "required": ["kind"]}),
    "start_processing": ("Download search results into assets and cut candidate clips.",
                         {**S(refs=ARR(STR), vod_from_min=NUM, vod_to_min=NUM, live_minutes=INT), "required": ["refs"]}),
    "process_link": ("Process a pasted Twitch/Kick/YouTube link.",
                     {**S(url=STR, streamer=STR, kind={"type": "string", "enum": ["vod", "clip", "live"]},
                          vod_from_min=NUM, vod_to_min=NUM, live_minutes=INT), "required": ["url", "streamer", "kind"]}),
    "start_hunt": ("Start a crew hunt: both clippers search their share of the streamers, cut candidates and cross-review.",
                   S(request=STR, streamers=ARR(STR))),
    "review_clip": ("Give your verdict on a teammate's clip.",
                    {**S(clip_id=INT, verdict={"type": "string", "enum": ["keep", "fix", "drop"]}, note=STR), "required": ["clip_id", "verdict"]}),
    "edit_clip": ("Change a clip's hook, title, caption or cut points (seconds in source). Hook/cut changes re-render.",
                  {**S(clip_id=INT, hook=STR, title=STR, description=STR, start=NUM, end=NUM), "required": ["clip_id"]}),
    "set_clip_status": ("Approve or reject clips.", {**S(clip_ids=ARR(INT), status={"type": "string", "enum": ["approved", "rejected", "ready"]}),
                                                      "required": ["clip_ids", "status"]}),
    "choose_layout": ("Pick a clip's layout: blur, facecam, split (our own filler footage below), crop, bubble.",
                      {**S(clip_id=INT, layout={"type": "string", "enum": ["blur", "facecam", "split", "crop", "bubble"]}, why=STR),
                       "required": ["clip_id", "layout"]}),
    "start_editing": ("Start parallel editing of chosen clips: each clipper edits one clip at a time and renders TikTok/Reels/Shorts versions.",
                      {**S(clip_ids=ARR(INT)), "required": ["clip_ids"]}),
    "make_compilation": ("Countdown compilation (#N..#1) from 2+ clips.", {**S(clip_ids=ARR(INT)), "required": ["clip_ids"]}),
    "publish_request": ("Ask the operator to confirm publishing clips to channels like 'tiktok:main'. Nothing is posted before Confirm.",
                        {**S(clip_ids=ARR(INT), channels=ARR(STR)), "required": ["clip_ids", "channels"]}),
    "send_to_phone_qr": ("QR code so the operator can download a clip on his own phone.", {**S(clip_id=INT), "required": ["clip_id"]}),
    "browser_task": ("Do a task in an account's browser tab (signed in, Italy box): open pages, click, type, drop a clip file, "
                     "schedule, read stats. Give a clear goal.",
                     {**S(channel=STR, goal=STR, clip_id=INT, platform_version={"type": "string", "enum": ["tiktok", "reels", "shorts"]}),
                      "required": ["channel", "goal"]}),
    "phone_task": ("Do a task on the Android phone (e.g. in Edits): copy a clip to it, tap through the app, post.",
                   {**S(goal=STR, clip_id=INT), "required": ["goal"]}),
    "check_stats": ("Open an account's dashboard in its tab and read followers / views / monetization progress.",
                    {**S(channel=STR), "required": ["channel"]}),
    "web_search": ("Search the web.", {**S(query=STR), "required": ["query"]}),
    "web_read": ("Read a web page's text.", {**S(url=STR), "required": ["url"]}),
    "save_trend": ("Save a trend finding for the Trends page.",
                   {**S(kind={"type": "string", "enum": ["format", "hook", "series", "captions", "sound", "timing"]},
                        title=STR, body=STR, sources=ARR(STR)), "required": ["kind", "title", "body"]}),
    "say_to_teammate": ("Tell your crew teammate something in the crew room.", {**S(text=STR), "required": ["text"]}),
    "set_mode": ("Clip length mode (monetization=true -> 61-90s) and default layout.", S(monetization=BOOL, layout=STR)),
    "autopilot_status": ("Tomorrow's plan, today's posts, autopilot on/off, Italy box status.", S()),
    # --- coding
    "start_change": ("Start a change to the app: the Planner plans, the Designer makes concepts if it's visual, the Coder builds on a safe copy.",
                     {**S(request=STR), "required": ["request"]}),
    "list_changes": ("Recent app changes and their status.", S()),
    "app_overview": ("FACTS about the app: every agent with its job and exact tools, every Python module with its functions "
                     "(name:line), every screen file. Use this first for 'can the app/crew do X?' questions.", S()),
    "search_code": ("Search the app's code (like grep). Returns file:line: text for each match. pattern = words or regex; "
                    "folder optional, e.g. 'app/' or 'desktop/ui/'.", {**S(pattern=STR, folder=STR), "required": ["pattern"]}),
    "list_files": ("List the app's code files.", S(folder=STR)),
    "read_file": ("Read a code file with line numbers (300 lines at a time; use start/end for other parts).",
                  {**S(path=STR, start=INT, end=INT), "required": ["path"]}),
}

COMMON = ["status", "pipeline", "list_clips", "handoff", "brain_search", "brain_read", "brain_write", "brain_learn"]
PRODUCTION = ["find_videos", "start_processing", "process_link", "start_hunt", "review_clip", "edit_clip", "set_clip_status",
              "choose_layout", "start_editing", "make_compilation", "publish_request", "send_to_phone_qr", "browser_task",
              "phone_task", "check_stats", "web_search", "web_read", "save_trend", "say_to_teammate", "set_mode", "autopilot_status"]
ALLOWED = {
    "agent": COMMON + ["autopilot_status", "set_mode", "send_to_phone_qr", "web_search"],
    "clipper_a": COMMON + PRODUCTION,
    "clipper_b": COMMON + PRODUCTION,
    "planner": COMMON + ["start_change", "list_changes", "app_overview", "search_code", "list_files", "read_file"],
    "coder": COMMON + ["start_change", "list_changes", "app_overview", "search_code", "list_files", "read_file"],
    "designer": COMMON + ["start_change", "list_changes", "app_overview", "search_code", "list_files", "read_file"],
}
OWNER_TEAM = {t: "production" for t in PRODUCTION}
OWNER_TEAM.update({t: "coding" for t in ("start_change", "list_changes", "app_overview", "search_code", "list_files", "read_file")})


def schemas_for(role: str) -> list[dict]:
    return [{"name": n, "description": SCHEMAS[n][0], "parameters": SCHEMAS[n][1]} for n in ALLOWED[role]]


def context_for(role: str) -> str:
    counts = {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM clips GROUP BY status")}
    busy = db.rows("SELECT status, COUNT(*) n FROM sources WHERE status NOT IN ('done','error') GROUP BY status")
    return json.dumps({"clips": counts, "sources_in_progress": {r["status"]: r["n"] for r in busy}})


# ------------------------------------------------------------------ implementations
def _status(cfg):
    from . import llm, network
    tw = cfg.get("twitch") or {}
    counts = {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM clips GROUP BY status")}
    return {"ai_online": llm.available(cfg), "twitch_keys": bool(tw.get("client_id") and tw.get("client_secret")),
            "italy_box": network.status(cached=True),
            "allowed_streamers": [{"name": s.get("name"), "campaign": s.get("campaign"), "allowed": s.get("allowed")}
                                  for s in cfg.get("streamers") or []],
            "channels": [{"key": c["key"], "method": c["method"], "ready": c["ready"]} for c in channels.all_channels(cfg)],
            "clips_by_status": counts, "monetization_mode": bool((cfg.get("clipping") or {}).get("monetization_mode")),
            "autopilot": bool(cfg["autopilot"].get("enabled"))}


def find(cfg, kind, streamer="", limit=10):
    if kind == "vods" and not streamer:
        return {"error": "need a streamer name for vods"}
    fn = {"live": discover.live_streams, "clips": discover.top_clips}.get(kind)
    items = fn(cfg) if fn else discover.recent_vods(cfg, streamer, n=10)
    if streamer:
        items = [i for i in items if i["streamer"].lower() == streamer.lower()]
    out = []
    for i in items[: max(1, min(int(limit or 10), 25))]:
        ref = f"v{len(_found) + 1}"
        _found[ref] = i
        out.append({"ref": ref, "streamer": i["streamer"], "kind": i["kind"], "title": i["title"][:90],
                    "views": i.get("viewers"), "duration": i.get("duration"), "allowed": i["listed"]})
    return {"results": out, "note": "allowed=false: not on the campaign list, don't process"}


def queue(cfg, url, kind, streamer, title="", vod_from_min=None, vod_to_min=None, live_minutes=None, crew=""):
    if cfg.get("only_listed_streamers", True) and not config.streamer(cfg, streamer):
        return {"error": f"{streamer} is not on the allowed streamer list"}
    opts = {"start": vod_from_min * 60 if vod_from_min is not None else None,
            "end": vod_to_min * 60 if vod_to_min is not None else None,
            "minutes": live_minutes or (20 if kind == "live" else None)}
    sid = db.add_source(url, kind, streamer.lower(), title, opts, crew=crew)
    pipeline.submit(pipeline.process_source, sid)
    return {"queued_source_id": sid, "streamer": streamer, "kind": kind}


def clips_list(status="ready", limit=15):
    sql = "SELECT c.*, s.streamer FROM clips c LEFT JOIN sources s ON s.id=c.source_id"
    rows = (db.rows(sql + " ORDER BY c.id DESC LIMIT ?", (limit or 15,)) if status in (None, "", "all")
            else db.rows(sql + " WHERE c.status=? ORDER BY c.score DESC LIMIT ?", (status, limit or 15)))
    return [{"id": c["id"], "streamer": c["streamer"] or "compilation", "status": c["status"], "found_by": c["found_by"],
             "seconds": round((c["end"] or 0) - (c["start"] or 0), 1) if not c["is_compilation"] else None,
             "score": round(c["score"] or 0, 1), "hook": c["hook"], "title": c["title"], "why": c["reason"],
             "review": json.loads(c["review"] or "{}"), "layout": c["layout"], "posts": json.loads(c["posts"] or "{}")}
            for c in rows]


def publish_request(cfg, clip_ids, chans):
    known = {c["key"]: c for c in channels.all_channels(cfg)}
    bad = [k for k in chans if k not in known]
    if bad:
        return {"error": f"unknown channels {bad}. Known: {list(known)}"}
    unready = [k for k in chans if not known[k]["ready"]]
    if unready:
        return {"error": f"{unready} are missing API keys - fill them in on the Channels page"}
    clips = []
    for cid in clip_ids:
        c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
        if not c or not c["render_path"]:
            return {"error": f"clip {cid} doesn't exist or isn't rendered"}
        clips.append(c)
    how = {"api": "API", "browser": "crew in the account tab", "phone": "crew on the phone"}
    lines = [f"#{c['id']} \"{c['title']}\" → " + ", ".join(f"{k} ({how.get(known[k]['method'], known[k]['method'])})" for k in chans)
             for c in clips]
    aid = db.q("INSERT INTO actions(kind,payload,summary,created_at) VALUES(?,?,?,?)",
               ("publish", json.dumps({"clip_ids": clip_ids, "channels": chans}), "\n".join(lines), time.time())).lastrowid
    return {"action_id": aid, "waiting_for": "operator to click Confirm", "plan": lines}


def _in_background(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def run(role: str, name: str, args: dict) -> tuple[dict, dict]:
    """Runs a tool for an agent. Returns (result for the model, extra data for the UI)."""
    me = ROLES[role]
    if name not in SCHEMAS:
        return {"error": f"unknown tool {name}"}, {}
    if name not in ALLOWED[role]:
        team = OWNER_TEAM.get(name, "another")
        return {"error": f"Not your job: '{name}' belongs to the {team} crew. Tell the operator and use handoff."}, {}
    cfg = config.load()
    try:
        if name == "status":
            return _status(cfg), {}
        if name == "pipeline":
            b = pipeline.board()
            return {k: [f"{i['label']}: {i['status']} {i.get('detail') or ''}"[:120] for i in v][:15] for k, v in b.items()}, {}
        if name == "list_clips":
            return {"clips": clips_list(args.get("status", "ready"), args.get("limit", 15))}, {}
        if name == "handoff":
            from . import team
            to, req = args["to"], args["request"]
            text = f"Handoff from {me['name']}: {req}"
            db.add_chat("event", text, room=to)
            responder = team.TEAM_OF_ROOM[to][0]
            _in_background(lambda: team.run(responder, None, room=to))
            return {"ok": True, "sent_to": to}, {}
        if name == "brain_search":
            return {"notes": [{"title": n["title"], "team": n["team"], "excerpt": n["body"][:300]}
                              for n in brain.search(args["query"], 6)]}, {}
        if name == "brain_read":
            n = brain.get(brain.slugify(args["title"]))
            return (n or {"error": "no such note"}), {}
        if name == "brain_write":
            team_area = "shared" if me["team"] == "manager" else me["team"]
            n = brain.write(args["title"], args["body"], team_area, me["name"], me["team"])
            return {"ok": True, "saved": n["title"], "team": n["team"]}, {}
        if name == "brain_learn":
            n = brain.append(args.get("note") or "Hooks that worked", f"{args['lesson']} ({me['name']}, {time.strftime('%d %b')})",
                             "learning", me["name"], me["team"])
            return {"ok": True, "note": n["title"]}, {}
        if name == "find_videos":
            return find(cfg, args.get("kind", "clips"), args.get("streamer", ""), args.get("limit", 10)), {}
        if name == "start_processing":
            out = []
            for ref in args.get("refs") or []:
                it = _found.get(ref)
                out.append({"ref": ref, "error": "unknown ref - search again"} if not it else
                           queue(cfg, it["url"], it["kind"], it["streamer"], it["title"], args.get("vod_from_min"),
                                 args.get("vod_to_min"), args.get("live_minutes"), crew=me["name"]))
            return {"queued": out}, {}
        if name == "process_link":
            return queue(cfg, args["url"], args.get("kind", "vod"), args.get("streamer", ""), "", args.get("vod_from_min"),
                         args.get("vod_to_min"), args.get("live_minutes"), crew=me["name"]), {}
        if name == "start_hunt":
            from . import crew
            _in_background(crew.hunt, args.get("request", ""), args.get("streamers") or [])
            return {"ok": True, "note": "hunt started; both clippers will report in the crew room"}, {}
        if name == "review_clip":
            from . import crew
            return crew.review(int(args["clip_id"]), me["name"], args["verdict"], args.get("note", "")), {}
        if name == "edit_clip":
            cid = int(args.pop("clip_id"))
            old = db.one("SELECT * FROM clips WHERE id=?", (cid,))
            if not old:
                return {"error": "no such clip"}, {}
            ch = {k: v for k, v in args.items() if k in ("hook", "title", "description", "start", "end") and v is not None}
            db.set_clip(cid, **ch)
            if any(k in ch for k in ("hook", "start", "end")) and not old["is_compilation"]:
                pipeline.submit(pipeline.rerender, cid)
                return {"ok": True, "rerendering": True}, {}
            return {"ok": True}, {}
        if name == "set_clip_status":
            for cid in args.get("clip_ids") or []:
                db.set_clip(int(cid), status=args["status"])
            return {"ok": True}, {}
        if name == "choose_layout":
            db.set_clip(int(args["clip_id"]), layout=args["layout"])
            return {"ok": True, "layout": args["layout"]}, {}
        if name == "start_editing":
            from . import crew
            ids = [int(i) for i in args.get("clip_ids") or []]
            _in_background(crew.edit_parallel, ids)
            return {"ok": True, "editing": ids}, {}
        if name == "make_compilation":
            ids = [int(i) for i in args.get("clip_ids") or []]
            if len(ids) < 2:
                return {"error": "need 2+ clips"}, {}
            pipeline.submit(pipeline.make_compilation, ids)
            return {"ok": True, "note": "building, appears as a new clip when done"}, {}
        if name == "publish_request":
            res = publish_request(cfg, [int(i) for i in args.get("clip_ids") or []], args.get("channels") or [])
            return res, ({"action_id": res["action_id"]} if res.get("action_id") else {})
        if name == "send_to_phone_qr":
            cid = int(args["clip_id"])
            c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
            if not c or not c["render_path"]:
                return {"error": "clip not rendered"}, {}
            s = phone.share(pipeline.export(cid), f"{c['title']}\n\n{pipeline.caption(cfg, c)}")
            return {"qr_for_clip": cid, "url": s["url"]}, {"qr": s["qr_svg"], "url": s["url"]}
        if name == "browser_task":
            from . import browser_ctl
            files = [browser_ctl.clip_file(int(args["clip_id"]), args.get("platform_version"))] if args.get("clip_id") else []
            return browser_ctl.run_task(args["channel"], args["goal"], files, who=me["name"]), {}
        if name == "phone_task":
            from . import android
            files = [browser_ctl_clip(int(args["clip_id"]), "reels")] if args.get("clip_id") else []
            return android.run_task(args["goal"], files, who=me["name"]), {}
        if name == "check_stats":
            from . import money
            return money.check_channel(args["channel"], who=me["name"]), {}
        if name == "web_search":
            from . import research
            return {"results": research.search(args["query"])}, {}
        if name == "web_read":
            from . import research
            return {"text": research.read(args["url"])}, {}
        if name == "save_trend":
            tid = db.q("INSERT INTO trends(kind,title,body,sources,created_at) VALUES(?,?,?,?,?)",
                       (args["kind"], args["title"], args["body"], json.dumps(args.get("sources") or []), time.time())).lastrowid
            return {"ok": True, "trend_id": tid}, {}
        if name == "say_to_teammate":
            db.add_chat("assistant", args["text"], {"to_teammate": True}, room="production", author=me["name"])
            return {"ok": True}, {}
        if name == "set_mode":
            if args.get("monetization") is not None:
                config.save_setting("clipping", "monetization_mode", bool(args["monetization"]))
            if args.get("layout"):
                config.save_setting("render", "layout", args["layout"])
            return {"ok": True, "applies_to": "videos processed from now on"}, {}
        if name == "autopilot_status":
            from . import autopilot
            return autopilot.summary(), {}
        if name == "start_change":
            from . import codecrew
            cid = codecrew.create(args["request"])
            _in_background(codecrew.plan_and_design, cid)
            return {"ok": True, "change_id": cid}, {}
        if name == "list_changes":
            return {"changes": db.rows("SELECT id, request, status, created_at FROM changes ORDER BY id DESC LIMIT 10")}, {}
        if name == "list_files":
            from . import codecrew
            return {"files": codecrew.list_files(args.get("folder", ""))}, {}
        if name == "read_file":
            from . import codecrew
            return codecrew.read_lines(args["path"], args.get("start", 1), args.get("end", 0)), {}
        if name == "search_code":
            from . import codecrew
            return codecrew.search_code(args["pattern"], args.get("folder", "")), {}
        if name == "app_overview":
            from . import codecrew
            return codecrew.overview(), {}
    except PermissionError as e:
        return {"error": str(e)}, {}
    except Exception as e:
        return {"error": f"{e.__class__.__name__}: {e}"[:400]}, {}
    return {"error": f"unhandled tool {name}"}, {}


def browser_ctl_clip(cid, version):
    from . import browser_ctl
    return browser_ctl.clip_file(cid, version)

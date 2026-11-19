"""Background worker: download -> transcribe -> find moments -> render. Plus posting."""
import json
import queue
import re
import shutil
import threading
import traceback
from pathlib import Path

from . import config, db, download, edit, highlights, llm, transcribe

_q: "queue.Queue[tuple]" = queue.Queue()


def submit(fn, *args):
    _q.put((fn, args))


def _worker():
    while True:
        fn, args = _q.get()
        try:
            fn(*args)
        except Exception:
            traceback.print_exc()
        finally:
            _q.task_done()


def start():
    # Anything left mid-way by a previous run gets re-queued.
    for s in db.rows("SELECT id FROM sources WHERE status NOT IN ('done','error')"):
        submit(process_source, s["id"])
    threading.Thread(target=_worker, daemon=True).start()


def queue_size() -> int:
    return _q.qsize()


# ---------------------------------------------------------------- processing
def credit_for(cfg, streamer: str) -> str:
    s = config.streamer(cfg, streamer)
    return (s or {}).get("credit") or (f"twitch.tv/{streamer}" if streamer else "")


def process_source(sid: int):
    cfg = config.load()
    src = db.one("SELECT * FROM sources WHERE id=?", (sid,))
    if not src:
        return
    opts = json.loads(src["options"] or "{}")
    folder = config.SOURCES_DIR / str(sid)
    say = lambda m: db.set_source(sid, message=m)
    try:
        db.set_source(sid, status="downloading", message="downloading video")
        video = download.fetch(src["url"], src["kind"], folder, opts)
        db.set_source(sid, path=str(video))
        dur = download.duration(video)

        db.set_source(sid, status="transcribing", message=f"transcribing {dur / 60:.0f} min of audio")
        try:
            segs = transcribe.transcribe(cfg, video)
        except Exception as e:
            segs = []
            say(f"transcription failed ({e}); continuing without captions")

        db.set_source(sid, status="finding", message="finding best moments")
        moments = highlights.find(cfg, video, dur, segs, src["streamer"] or "", say)

        db.set_source(sid, status="rendering")
        credit = credit_for(cfg, src["streamer"])
        for i, m in enumerate(moments):
            say(f"rendering clip {i + 1}/{len(moments)}")
            cid = db.add_clip(source_id=sid, start=m["start"], end=m["end"], score=m["score"],
                              hook=m.get("hook", ""), title=m.get("title", ""),
                              description=m.get("description", ""), reason=m.get("reason", ""),
                              status="rendering", found_by=src.get("crew") or "")
            _render_clip(cfg, cid, video, segs, credit)
        db.set_source(sid, status="done", message=f"{len(moments)} clips ready for review")
    except Exception as e:
        traceback.print_exc()
        db.set_source(sid, status="error", message=str(e)[:500])


def _render_clip(cfg, cid, video: Path, segs, credit):
    c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    try:
        words = transcribe.words_between(segs, c["start"], c["end"])
        out = edit.render(cfg, video, c["start"], c["end"], config.CLIPS_DIR / str(cid),
                          c["hook"], words, credit)
        db.set_clip(cid, render_path=str(out), status="ready")
    except Exception as e:
        db.set_clip(cid, status="error", reason=f"render failed: {e}"[:500])


def rerender(cid: int):
    cfg = config.load()
    c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    src = db.one("SELECT * FROM sources WHERE id=?", (c["source_id"],))
    if not src or not src["path"]:
        return
    video = Path(src["path"])
    cache = video.with_name("transcript.json")
    segs = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else []
    db.set_clip(cid, status="rendering")
    _render_clip(cfg, cid, video, segs, credit_for(cfg, src["streamer"]))


def make_compilation(clip_ids: list[int]):
    """Countdown compilation from several clips (best one last)."""
    cfg = config.load()
    clips = [db.one("SELECT * FROM clips WHERE id=?", (i,)) for i in clip_ids]
    clips = [c for c in clips if c and not c["is_compilation"]]
    if len(clips) < 2:
        return
    clips.sort(key=lambda c: c["score"] or 0)  # weakest first, best = #1 at the end
    items, parts, streamers = [], [], []
    for c in clips:
        src = db.one("SELECT * FROM sources WHERE id=?", (c["source_id"],))
        items.append({"streamer": src["streamer"], "hook": c["hook"], "title": c["title"]})
        streamers.append(src["streamer"])
    meta = llm.compilation_meta(cfg, items)
    cid = db.add_clip(source_id=None, start=0, end=0, score=max(c["score"] or 0 for c in clips),
                      hook=meta.get("hook", ""), title=meta.get("title", ""),
                      description=meta.get("description", ""),
                      reason="compilation of clips " + ", ".join(str(c["id"]) for c in clips),
                      status="rendering", is_compilation=1)
    out_dir = config.CLIPS_DIR / str(cid)
    try:
        for i, c in enumerate(clips):
            src = db.one("SELECT * FROM sources WHERE id=?", (c["source_id"],))
            video = Path(src["path"])
            cache = video.with_name("transcript.json")
            segs = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else []
            words = transcribe.words_between(segs, c["start"], c["end"])
            parts.append(edit.render(cfg, video, c["start"], c["end"], out_dir / f"part{i}", "",
                                     words, credit_for(cfg, src["streamer"])))
        footer = (cfg.get("render") or {}).get("watermark", "")
        out = edit.compilation(parts, out_dir, meta.get("hook", ""), footer)
        credits = " / ".join(dict.fromkeys(credit_for(cfg, s) for s in streamers))
        db.set_clip(cid, render_path=str(out), status="ready",
                    description=f"{meta.get('description', '')}\n\nClips from: {credits}")
    except Exception as e:
        db.set_clip(cid, status="error", reason=f"compilation failed: {e}"[:500])


# ---------------------------------------------------------------- posting
def caption(cfg, c: dict) -> str:
    text = c["description"] or ""
    if c["source_id"]:
        src = db.one("SELECT streamer FROM sources WHERE id=?", (c["source_id"],))
        credit = credit_for(cfg, src["streamer"]) if src else ""
        if credit and credit not in text:
            text = f"{text}\n\n{credit}"
    return text.strip()


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", s or "clip").strip("-")[:50] or "clip"


def export(cid: int) -> Path:
    cfg = config.load()
    c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    base = config.EXPORT_DIR / f"{cid:04d}-{_slug(c['title'])}"
    shutil.copy(c["render_path"], base.with_suffix(".mp4"))
    base.with_suffix(".txt").write_text(f"{c['title']}\n\n{caption(cfg, c)}\n", encoding="utf-8")
    return base.with_suffix(".mp4")


def _record(cid, key, result):
    c = db.one("SELECT posts FROM clips WHERE id=?", (cid,))
    posts = json.loads(c["posts"] or "{}")
    posts[key] = result
    status = "posted" if any(v.get("ok") for v in posts.values()) else None
    db.set_clip(cid, posts=json.dumps(posts), **({"status": status} if status else {}))


def check_allowed(cfg, c: dict, platform: str):
    """Campaign rules: some campaigns only pay on certain platforms."""
    if c["source_id"]:
        src = db.one("SELECT streamer FROM sources WHERE id=?", (c["source_id"],))
        s = config.streamer(cfg, src["streamer"]) if src else None
        if s and s.get("allowed") and platform not in s["allowed"]:
            raise RuntimeError(f"Campaign for {src['streamer']} doesn't allow {platform}")


def post(cid: int, key: str):
    """Uploads through the official API of an api-type channel."""
    from . import channels

    cfg = config.load()
    c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    platform = key.split(":")[0]
    _record(cid, key, {"ok": False, "msg": "uploading..."})
    try:
        acct = channels.get(key, cfg)
        if acct is None:
            raise RuntimeError(f"No channel {key}")
        if acct["method"] != "api":
            raise RuntimeError("browser channel - use handoff")
        check_allowed(cfg, c, platform)
        video = Path(c["render_path"])
        text = caption(cfg, c)
        if platform == "youtube":
            from .publish import youtube
            res = youtube.upload(acct, video, c["title"], text)
        elif platform == "instagram":
            from .publish import instagram
            res = instagram.upload(acct, video, f"{c['title']}\n\n{text}")
        elif platform == "tiktok":
            from .publish import tiktok
            res = tiktok.upload(acct, video, f"{c['title']} {text}")
        else:
            raise RuntimeError(f"unknown platform {platform}")
        _record(cid, key, {"ok": True, "msg": res})
    except Exception as e:
        traceback.print_exc()
        _record(cid, key, {"ok": False, "msg": str(e)[:400]})


def handoff(cid: int, key: str) -> dict:
    """Browser channel: export the file + caption so the person can drag it into
    the account's upload page (which the app opens)."""
    from . import channels

    cfg = config.load()
    c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    ch = channels.get(key, cfg) or {}
    platform = key.split(":")[0]
    check_allowed(cfg, c, platform)
    path = export(cid)
    text = f"{c['title']}\n\n{caption(cfg, c)}"
    _record(cid, key, {"ok": False, "handoff": True,
                       "msg": "ready - drag the file into the upload page, paste the caption, post, then mark as posted"})
    return {"clip_id": cid, "key": key, "file": str(path), "caption": text,
            "url": channels.UPLOAD_URLS.get(platform), "title": f"{key} - upload",
            "edits_tip": platform == "instagram"}


def mark_posted(cid: int, key: str, link: str = ""):
    _record(cid, key, {"ok": True, "msg": link or "posted by hand"})


# ---------------------------------------------------------------- pipeline board
STAGE_OF_SOURCE = {"queued": "finding", "downloading": "finding", "transcribing": "clipping",
                   "finding": "clipping", "rendering": "editing"}


def board() -> dict:
    """Finding -> Clipping -> Editing -> Publishing, for the live pipeline view."""
    stages = {"finding": [], "clipping": [], "editing": [], "publishing": []}
    for s in db.rows("SELECT * FROM sources WHERE status NOT IN ('done') ORDER BY id DESC LIMIT 60"):
        st = "error" if s["status"] == "error" else STAGE_OF_SOURCE.get(s["status"], "finding")
        item = {"type": "source", "id": s["id"], "label": f"{s['streamer'] or 'video'} · {s['kind']}",
                "detail": s["message"], "status": s["status"], "title": s["title"]}
        stages["finding" if st == "error" else st].append(item)
    for c in db.rows("SELECT c.*, s.streamer FROM clips c LEFT JOIN sources s ON s.id=c.source_id "
                     "WHERE c.status IN ('rendering','ready','approved','posted','error','queued_edit','editing','edited') "
                     "ORDER BY c.id DESC LIMIT 120"):
        label = f"#{c['id']} {c['streamer'] or 'compilation'}"
        item = {"type": "clip", "id": c["id"], "label": label, "status": c["status"], "who": c["editor"] or c["found_by"],
                "detail": c["hook"] or c["title"], "score": c["score"],
                "posts": json.loads(c["posts"] or "{}")}
        if c["status"] in ("rendering", "error", "queued_edit", "editing"):
            stages["editing"].append(item)
        else:
            stages["publishing"].append(item)
    return stages

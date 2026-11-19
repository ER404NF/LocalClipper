"""Production crew workflows: two clippers hunting in parallel, reviewing each other, editing in parallel.

hunt -> cross-review -> shortlist (operator picks) -> edit_parallel -> operator feedback -> publish plan"""
import json
import queue
import threading
import time
from pathlib import Path

from . import brain, config, db, discover, pipeline, team, transcribe
from .edit import render

A, B = "clipper_a", "clipper_b"
NAMES = {A: "Clipper A", B: "Clipper B"}
OTHER = {"Clipper A": "Clipper B", "Clipper B": "Clipper A"}
ROLE_OF = {"Clipper A": A, "Clipper B": B}
_hunt_lock = threading.Lock()


def _say(role, text, data=None):
    team.post(role, text, data, room="production")


def _clip_text(c: dict) -> str:
    src = db.one("SELECT * FROM sources WHERE id=?", (c["source_id"],)) if c["source_id"] else None
    words = ""
    if src and src["path"]:
        cache = Path(src["path"]).with_name("transcript.json")
        if cache.exists():
            segs = json.loads(cache.read_text(encoding="utf-8"))
            words = transcribe.text_between(segs, c["start"], c["end"])
    return words[:1500]


# ------------------------------------------------------------------ hunt
def hunt(request: str = "", streamers: list[str] | None = None, per_streamer: int = 2, wait_minutes: int = 45):
    if not _hunt_lock.acquire(blocking=False):
        _say(A, "We're already on a hunt. I'll report when it's done.")
        return
    try:
        cfg = config.load()
        names = [s.lower() for s in (streamers or [x.get("name") for x in cfg.get("streamers") or []]) if s]
        if not names:
            _say(A, "There are no streamers on the campaign list yet. Add them in config.yaml first.")
            return
        split = {A: names[0::2], B: names[1::2] or names[:1]}
        _say(A, f"Splitting the hunt: I take {', '.join(split[A])}. Clipper B takes {', '.join(split[B])}."
             + (f" Brief: {request}" if request else ""))
        try:
            top = discover.top_clips(cfg)
        except Exception as e:
            _say(A, f"I can't search Twitch right now: {e}")
            return
        queued: dict[str, list[int]] = {A: [], B: []}
        for role, mine in split.items():
            picks = []
            for s in mine:
                picks += [c for c in top if c["streamer"].lower() == s][:per_streamer]
            for c in picks:
                sid = db.add_source(c["url"], "clip", c["streamer"].lower(), c["title"], {}, crew=NAMES[role])
                pipeline.submit(pipeline.process_source, sid)
                queued[role].append(sid)
            _say(role, f"Found {len(picks)} top clips for {', '.join(mine)}. Downloading and cutting them now."
                 if picks else f"Nothing strong from {', '.join(mine)} in the last 24h.")
        all_ids = queued[A] + queued[B]
        deadline = time.time() + wait_minutes * 60
        while all_ids and time.time() < deadline:
            left = db.one(f"SELECT COUNT(*) n FROM sources WHERE id IN ({','.join('?' * len(all_ids))}) "
                          "AND status NOT IN ('done','error')", tuple(all_ids))["n"]
            if not left:
                break
            time.sleep(5)
        cross_review(all_ids)
    finally:
        _hunt_lock.release()


# ------------------------------------------------------------------ review
REVIEW_SYS = """You are {me} from a GTA 6 clipping crew, reviewing a clip your teammate {other} cut.
Be honest and specific. Reply with JSON only:
{{"verdict": "keep|fix|drop", "note": "one short sentence, e.g. what to fix"}}
keep = strong as is. fix = good moment but needs a change (say which). drop = boring, duplicate or weak."""


def review(clip_id: int, reviewer: str, verdict: str, note: str = "") -> dict:
    c = db.one("SELECT * FROM clips WHERE id=?", (clip_id,))
    if not c:
        return {"error": "no such clip"}
    if c["found_by"] == reviewer:
        return {"error": "review your teammate's clips, not your own"}
    rev = json.loads(c["review"] or "{}")
    rev[reviewer] = {"verdict": verdict, "note": note}
    db.set_clip(clip_id, review=json.dumps(rev))
    return {"ok": True}


def cross_review(source_ids: list[int]):
    if not source_ids:
        return
    clips = db.rows(f"SELECT * FROM clips WHERE source_id IN ({','.join('?' * len(source_ids))}) AND status='ready'",
                    tuple(source_ids))
    if not clips:
        _say(A, "The hunt didn't produce any usable clips this time.")
        return
    lessons = brain.context_for("hooks that worked review")
    results = {"keep": [], "fix": [], "drop": []}
    for c in clips:
        finder = c["found_by"] or "Clipper A"
        reviewer = OTHER.get(finder, "Clipper B")
        try:
            v = team.ask_json(REVIEW_SYS.format(me=reviewer, other=finder) + "\n\nLessons so far:\n" + lessons,
                              f"Clip #{c['id']} ({c['end'] - c['start']:.0f}s). Hook: {c['hook']}\nTitle: {c['title']}\n"
                              f"AI score: {c['score']:.1f}. Why it was picked: {c['reason']}\nTranscript: {_clip_text(c)}")
            verdict = v.get("verdict", "keep") if v.get("verdict") in ("keep", "fix", "drop") else "keep"
            note = v.get("note", "")
        except Exception as e:
            verdict, note = "keep", f"(couldn't review: {e.__class__.__name__})"
        review(c["id"], reviewer, verdict, note)
        results[verdict].append((c, reviewer, note))
        if verdict == "drop":
            db.set_clip(c["id"], status="rejected")
    for who in ("Clipper A", "Clipper B"):
        mine = [(c["id"], v, n) for v in ("keep", "fix", "drop") for c, r, n in results[v] if r == who]
        if mine:
            lines = "; ".join(f"#{cid} {v}" + (f" ({n})" if n else "") for cid, v, n in mine)
            _say(ROLE_OF[who], f"Reviewed {OTHER[who]}'s clips: {lines}")
    short = [c["id"] for v in ("keep", "fix") for c, _, _ in results[v]]
    if short:
        _say(A, f"Shortlist ready: {len(short)} clips. Pick the ones to edit.", {"shortlist": short})


# ------------------------------------------------------------------ editing
LAYOUT_SYS = """You edit GTA 6 stream clips for TikTok, Reels and Shorts. Choose the layout for this clip.
Layouts: blur (gameplay centered on blurred background, safe default), facecam (streamer cam on top, use when the
reaction IS the moment), split (stream on top + our own background gameplay below, good when the clip has slow parts),
crop (zoomed full-screen action, loses the sides), bubble (gameplay full screen + face in a corner).
{filler}
Reply with JSON only: {{"layout": "...", "why": "one short sentence", "hook": "better hook if needed (max 8 words) or empty"}}"""


def _choose_layout(c: dict, editor: str) -> dict:
    from .edit import filler_file
    filler = "Filler footage is available." if filler_file() else "No filler footage yet: don't pick split."
    try:
        d = team.ask_json(LAYOUT_SYS.format(filler=filler) + "\n\nTeam notes:\n" + brain.context_for("formats layout"),
                          f"Hook: {c['hook']}\nTitle: {c['title']}\nWhy picked: {c['reason']}\n"
                          f"Reviews: {c['review']}\nTranscript: {_clip_text(c)}")
    except Exception:
        d = {}
    if d.get("layout") not in ("blur", "facecam", "split", "crop", "bubble"):
        d["layout"] = (config.load().get("render") or {}).get("layout", "blur")
    return d


def edit_one(clip_id: int, editor_role: str, layout: str | None = None, why: str = ""):
    cfg = config.load()
    c = db.one("SELECT * FROM clips WHERE id=?", (clip_id,))
    if not c or not c["source_id"]:
        return
    name = NAMES[editor_role]
    src = db.one("SELECT * FROM sources WHERE id=?", (c["source_id"],))
    video = Path(src["path"])
    cache = video.with_name("transcript.json")
    segs = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else []
    if not layout:
        d = _choose_layout(c, name)
        layout, why = d["layout"], d.get("why", "")
        if d.get("hook"):
            db.set_clip(clip_id, hook=d["hook"])
            c["hook"] = d["hook"]
    db.set_clip(clip_id, status="editing", editor=name, layout=layout)
    words = transcribe.words_between(segs, c["start"], c["end"])
    credit = pipeline.credit_for(cfg, src["streamer"])
    out_dir = config.CLIPS_DIR / str(clip_id)
    variants = {}
    try:
        for platform in ("tiktok", "reels", "shorts"):
            variants[platform] = str(render(cfg, video, c["start"], c["end"], out_dir, c["hook"], words, credit,
                                            layout=layout, platform=platform, out_name=f"{platform}.mp4"))
        db.set_clip(clip_id, variants=json.dumps(variants), render_path=variants["tiktok"], status="edited")
        _say(editor_role, f"#{clip_id} edited: {layout} layout" + (f", {why}" if why else "") + ". TikTok, Reels and Shorts versions ready.",
             {"edited": clip_id})
    except Exception as e:
        db.set_clip(clip_id, status="ready")
        _say(editor_role, f"Couldn't edit #{clip_id}: {str(e)[:200]}")


def edit_parallel(clip_ids: list[int]):
    """Each clipper takes the next clip from the pile: two clips are edited at the same time."""
    work: "queue.Queue[int]" = queue.Queue()
    for cid in clip_ids:
        work.put(cid)
        db.set_clip(cid, status="queued_edit")
    _say(A, f"Editing {len(clip_ids)} clips. Clipper B and I take one each at a time.")

    def worker(role):
        while True:
            try:
                cid = work.get_nowait()
            except queue.Empty:
                return
            edit_one(cid, role)

    ts = [threading.Thread(target=worker, args=(r,), daemon=True) for r in (A, B)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    _say(A, "All edits done. Review them on the Edit & review page and tell us what to change.")


FEEDBACK_SYS = """You are {me}, you edited this GTA 6 clip. The operator gave feedback. Turn it into changes.
Reply with JSON only: {{"hook": "new hook or empty", "start_delta": seconds to move the start (negative = earlier, 0 = no change),
"end_delta": seconds to move the end, "layout": "blur|facecam|split|crop|bubble or empty", "reply": "one short sentence to the operator"}}"""


def feedback(clip_id: int, text: str):
    c = db.one("SELECT * FROM clips WHERE id=?", (clip_id,))
    if not c:
        return
    role = ROLE_OF.get(c["editor"] or "", A)
    db.add_chat("user", f"Feedback on #{clip_id}: {text}", room="production")
    try:
        d = team.ask_json(FEEDBACK_SYS.format(me=NAMES[role]),
                          f"Feedback: {text}\nCurrent hook: {c['hook']}\nCut: {c['start']:.1f}s to {c['end']:.1f}s\nLayout: {c['layout']}")
    except Exception as e:
        _say(role, f"I couldn't read that feedback ({e.__class__.__name__}). Try saying it differently?")
        return
    changes = {}
    if d.get("hook"):
        changes["hook"] = d["hook"]
    if d.get("start_delta"):
        changes["start"] = max(0.0, c["start"] + float(d["start_delta"]))
    if d.get("end_delta"):
        changes["end"] = c["end"] + float(d["end_delta"])
    if changes:
        db.set_clip(clip_id, **changes)
    _say(role, d.get("reply") or "On it.")
    edit_one(clip_id, role, layout=d.get("layout") or c["layout"] or None)
    brain.append("Hooks that worked", f"Operator feedback on #{clip_id}: {text}", "learning", NAMES[role], "production")

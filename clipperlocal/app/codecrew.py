"""The coding crew: Planner, Designer, Coder change the app on a safe copy (a git worktree).

request -> Planner plan -> Designer concepts (if visual) -> operator picks -> Coder builds on a copy
-> checks run (compile, engine starts, pages load) -> Designer reviews -> operator Apply (or Discard) -> Undo anytime.
The crew may only touch app/ (Python engine) and desktop/ui/ (screens). The Rust shell is off-limits."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import requests

from . import brain, config, db, team

ROOT = config.ROOT
ALLOWED = ("app/", "desktop/ui/")
WT_DIR = config.DATA / "worktrees"
CONCEPT_DIR = config.DATA / "concepts"
GIT = ["git", "-c", "user.name=ClipperLocal coding crew", "-c", "user.email=crew@clipperlocal.local"]
_build_lock = threading.Lock()


def _git(*args, cwd=ROOT, check=True) -> str:
    p = subprocess.run(GIT + list(args), cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {(p.stderr or p.stdout).strip()[:400]}")
    return p.stdout


def _ok_path(path: str) -> str:
    p = path.replace("\\", "/").lstrip("./")
    if ".." in p.split("/") or not p.startswith(ALLOWED):
        raise PermissionError(f"The coding crew can only change {', '.join(ALLOWED)} (asked for {path})")
    return p


READABLE = ALLOWED + ("desktop/src-tauri/src/", "desktop/src-tauri/tauri.conf.json", "installer/", "italy-box/",
                      "README.md", "config.example.yaml", "requirements.txt")
TEXT_EXT = {".py", ".js", ".html", ".css", ".md", ".yaml", ".yml", ".json", ".rs", ".toml", ".txt", ".ps1", ".sh", ".nsi"}


def _read_ok(path: str) -> str:
    p = path.replace("\\", "/").strip().lstrip("/")
    while p.startswith("./"):
        p = p[2:]
    if ".." in p.split("/") or not p.startswith(READABLE):
        raise PermissionError(f"Not part of the app's code: {path}")
    return p


def _readable_files() -> list[Path]:
    out = []
    for base in READABLE:
        f = ROOT / base
        items = [f] if f.is_file() else (sorted(f.rglob("*")) if f.is_dir() else [])
        for x in items:
            rel = x.relative_to(ROOT).as_posix()
            if x.is_file() and x.suffix in TEXT_EXT and "__pycache__" not in rel and "/target/" not in rel:
                out.append(x)
    return out


def search_code(pattern: str, folder: str = "", max_hits: int = 60) -> dict:
    """grep through the app's code. pattern = plain words or a regex. Returns file:line: text."""
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        rx = re.compile(re.escape(pattern), re.I)
    hits, files = [], set()
    for f in _readable_files():
        rel = f.relative_to(ROOT).as_posix()
        if folder and not rel.startswith(folder.replace("\\", "/")):
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if rx.search(line):
                hits.append(f"{rel}:{i}: {line.strip()[:160]}")
                files.add(rel)
                if len(hits) >= max_hits:
                    return {"hits": hits, "files": sorted(files), "more": True}
    return {"hits": hits, "files": sorted(files), "more": False}


def read_lines(path: str, start: int = 1, end: int = 0) -> dict:
    """A file with line numbers (so answers can cite file:line). Long files come in parts."""
    p = _read_ok(path)
    f = ROOT / p
    if not f.is_file():
        return {"error": f"no such file: {p}", "hint": "use search_code or app_overview to find the right file"}
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(start or 1))
    end = int(end or 0) or min(len(lines), start + 299)
    end = min(end, len(lines), start + 399)
    body = "\n".join(f"{i:>4}  {lines[i - 1]}" for i in range(start, end + 1))
    return {"path": p, "lines": f"{start}-{end} of {len(lines)}", "text": body,
            "more": f"call read_file with start={end + 1} for the rest" if end < len(lines) else ""}


def overview() -> dict:
    """Facts about what the app is made of: every agent with its job and exact tools, every module and screen."""
    import ast
    from . import tools as T
    agents = {k: {"name": r["name"], "crew": r["team"], "job": r["job"], "not_my_job": r["refuses"],
                  "tools": T.ALLOWED.get(k, [])} for k, r in team.ROLES.items()}
    tool_help = {name: spec[0] for name, spec in T.SCHEMAS.items()} if hasattr(T, "SCHEMAS") else {}
    modules = {}
    for f in sorted((ROOT / "app").glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        doc = (ast.get_docstring(tree) or "").split("\n")[0]
        funcs = [f"{n.name}:{n.lineno}" for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and not n.name.startswith("_")]
        modules[f"app/{f.name}"] = {"about": doc, "functions": funcs[:40]}
    screens = {}
    for f in sorted((ROOT / "desktop" / "ui").glob("*.js")):
        names = re.findall(r"^(?:export )?(?:async )?function (\w+)", f.read_text(encoding="utf-8"), re.M)
        screens[f"desktop/ui/{f.name}"] = names[:40]
    return {"agents": agents, "tool_help": tool_help, "python_modules": modules, "screen_files": screens,
            "writable_by_coding_crew": list(ALLOWED)}


def list_files(folder: str = "") -> list[str]:
    out = []
    for base in ALLOWED:
        for f in sorted((ROOT / base).rglob("*")):
            rel = f.relative_to(ROOT).as_posix()
            if f.is_file() and "__pycache__" not in rel and rel.startswith(folder or ""):
                out.append(rel)
    return out


def read_file(path: str, root: Path = ROOT) -> str:
    p = _read_ok(path)
    f = root / p
    return f.read_text(encoding="utf-8") if f.exists() else ""


def _say(role, text, data=None):
    team.post(role, text, data, room="coding")


def _set(cid, **kw):
    for k in ("plan", "concepts", "checks", "files"):
        if k in kw and not isinstance(kw[k], str):
            kw[k] = json.dumps(kw[k])
    db._set("changes", cid, kw)


def get(cid: int) -> dict:
    c = db.one("SELECT * FROM changes WHERE id=?", (cid,))
    if c:
        for k in ("plan", "concepts", "checks", "files"):
            c[k] = json.loads(c[k] or ("{}" if k == "plan" else "[]"))
    return c


def create(request: str) -> int:
    return db.q("INSERT INTO changes(request,created_at) VALUES(?,?)", (request, time.time())).lastrowid


# ------------------------------------------------------------------ plan + design
PLAN_SYS = """You are the Planner of a 3-agent coding crew (Planner, Designer, Coder) that changes a desktop app.
The app: Python engine in app/ (FastAPI server.py, SQLite db.py, many modules) and screens in desktop/ui/
(index.html, style.css, app.js: plain JS, no build step). You may only plan changes inside app/ and desktop/ui/.
Keep changes small and safe. Reply with JSON only:
{"summary": "one sentence", "steps": ["short step", ...], "files": ["app/x.py", "desktop/ui/app.js", ...],
 "visual": true/false (does it change what the screens look like?), "questions": ["only if truly unclear"]}"""

DESIGN_SYS = """You are the Designer of the app's coding crew. Make {n} different screen-mockup concepts for this change,
in the app's style: ink black #0A0A0A background, paper white #F2EEE3 text, warm greys (#B5B0A4, #8F8A7E),
borders #2A2926, cards #141413 with 12px radius, accent var(--accent) (lightning blue), Inter font.
Each concept is a self-contained HTML fragment (no <html>/<body>, inline styles only, no scripts, no images),
about 900x560px, showing the new or changed screen with realistic sample content.
Reply with JSON only: {{"concepts": [{{"name": "A · short name", "description": "one sentence", "html": "..."}}]}}"""


def plan_and_design(cid: int):
    ch = get(cid)
    try:
        code_map = "\n".join(list_files())
        plan = team.ask_json(PLAN_SYS, role="planner", user= f"Request: {ch['request']}\n\nFiles:\n{code_map}\n\nTeam notes:\n"
                             + brain.context_for(ch["request"] + " app code"))
    except Exception as e:
        _say("planner", f"I couldn't plan that ({e.__class__.__name__}). Can you say it another way?")
        _set(cid, status="failed")
        return
    plan["files"] = [f for f in plan.get("files", []) if f.replace("\\", "/").startswith(ALLOWED)][:6]
    _set(cid, plan=plan, status="planned")
    if plan.get("questions"):
        _say("planner", "Before we start: " + " ".join(plan["questions"]), {"change": cid})
        _set(cid, status="needs_answer")
        return
    steps = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(plan.get("steps", [])))
    _say("planner", f"Plan: {plan.get('summary', '')}\n{steps}\nFiles: {', '.join(plan['files']) or 'none'}")
    if plan.get("visual"):
        design(cid)
    else:
        _say("planner", "No screen changes needed, so no concepts. Want us to build it?", {"change": cid, "build_button": True})
        _set(cid, status="waiting_ok")


def design(cid: int, n: int = 2):
    ch = get(cid)
    try:
        d = team.ask_json(DESIGN_SYS.format(n=n), role="designer", user=f"Change: {ch['request']}\nPlan: {json.dumps(ch['plan'])}\n\n"
                          f"Current screens (excerpt):\n{read_file('desktop/ui/index.html')[:3000]}")
        concepts = d.get("concepts", [])[:3]
    except Exception as e:
        _say("designer", f"My mockups didn't come out ({e.__class__.__name__}). I'll describe it instead: {ch['plan'].get('summary', '')}")
        concepts = []
    folder = CONCEPT_DIR / str(cid)
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, c in enumerate(concepts):
        html = re.sub(r"<script.*?</script>", "", c.get("html", ""), flags=re.S | re.I)
        (folder / f"{i}.html").write_text(html, encoding="utf-8")
        saved.append({"i": i, "name": c.get("name", f"Concept {i + 1}"), "description": c.get("description", "")})
    _set(cid, concepts=saved, status="concepts")
    if saved:
        _say("designer", f"{len(saved)} concepts, both in the app's current style:", {"change": cid, "concepts": saved})
        try:
            opinion = team.ask_json(role="coder", system="You are the Coder. Compare the concepts for effort and risk. JSON only: "
                                    "{\"pick\": index, \"why\": \"one or two sentences\"}",
                                    user=json.dumps({"plan": ch["plan"], "concepts": saved}))
            _say("coder", f"I'd build {saved[int(opinion.get('pick', 0))]['name']}: {opinion.get('why', '')}")
        except Exception:
            pass
        _say("planner", "Which one should we build?", {"change": cid, "choose": True})


def concept_html(cid: int, i: int) -> str:
    f = CONCEPT_DIR / str(cid) / f"{int(i)}.html"
    return f.read_text(encoding="utf-8") if f.exists() else ""


# ------------------------------------------------------------------ build on a copy
CODE_SYS = """You are the Coder. Change the app as planned. Output ONLY edit blocks, nothing else, in this exact format:

FILE: path/relative/to/repo
<<<<<<< SEARCH
exact existing lines to replace (copy them exactly, enough to be unique)
=======
new lines
>>>>>>> REPLACE

For a NEW file, leave SEARCH empty. Several blocks per file are fine. Only edit files under app/ or desktop/ui/.
Match the existing code style. Don't remove features. Keep the app's look (ink/paper/accent)."""

BLOCK = re.compile(r"FILE:\s*(\S+)\s*\n<<<<<<< SEARCH\n(.*?)\n?=======\n(.*?)\n?>>>>>>> REPLACE", re.S)


def _apply_blocks(text: str, wt: Path) -> tuple[list[str], list[str]]:
    changed, errors = [], []
    for path, search, replace in BLOCK.findall(text):
        try:
            rel = _ok_path(path)
        except PermissionError as e:
            errors.append(str(e))
            continue
        f = wt / rel
        if not search.strip():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(replace + "\n", encoding="utf-8")
        else:
            cur = f.read_text(encoding="utf-8") if f.exists() else ""
            if cur.count(search) != 1:
                errors.append(f"{rel}: SEARCH text found {cur.count(search)} times (must be exactly once)")
                continue
            f.write_text(cur.replace(search, replace), encoding="utf-8")
        if rel not in changed:
            changed.append(rel)
    if not BLOCK.findall(text):
        errors.append("no edit blocks found")
    return changed, errors


def _checks(wt: Path, changed: list[str]) -> list[dict]:
    out = []
    py = [c for c in changed if c.endswith(".py")]
    for c in py:
        p = subprocess.run([sys.executable, "-m", "py_compile", str(wt / c)], capture_output=True, text=True)
        out.append({"name": f"{c} compiles", "ok": p.returncode == 0, "detail": p.stderr[-300:]})
    js = [c for c in changed if c.endswith(".js")]
    if js and shutil.which("node"):
        for c in js:
            p = subprocess.run(["node", "--check", str(wt / c)], capture_output=True, text=True)
            out.append({"name": f"{c} has no syntax errors", "ok": p.returncode == 0, "detail": p.stderr[-300:]})
    tmp = tempfile.mkdtemp(prefix="cl_check_")
    env = {**os.environ, "CLIPPERLOCAL_DATA": tmp, "CLIPPERLOCAL_PORT": "8799"}
    proc = subprocess.Popen([sys.executable, "-m", "app.server", "--no-browser", "--no-workers"], cwd=wt, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    ok, detail = False, ""
    try:
        for _ in range(50):
            time.sleep(0.5)
            if proc.poll() is not None:
                detail = proc.stdout.read().decode(errors="ignore")[-400:]
                break
            try:
                r = requests.get("http://127.0.0.1:8799/api/health", timeout=1)
                ok = r.ok
                if ok:
                    ui = requests.get("http://127.0.0.1:8799/", timeout=3)
                    out.append({"name": "Screens load", "ok": ui.ok, "detail": ""})
                    break
            except Exception:
                pass
    finally:
        proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    out.insert(0, {"name": "Engine starts", "ok": ok, "detail": detail})
    return out


def build(cid: int, concept: int | None = None):
    with _build_lock:
        ch = get(cid)
        branch = f"change-{cid}"
        wt = WT_DIR / branch
        _set(cid, status="building", branch=branch, chosen="" if concept is None else str(concept))
        if not ensure_repo():
            _say("coder", "I can't make safe copies: Git isn't installed. Run the ClipperLocal installer again to add it.")
            _set(cid, status="failed")
            return
        save_local("Saved local edits before a coding crew change")
        try:
            WT_DIR.mkdir(parents=True, exist_ok=True)
            if wt.exists():
                _git("worktree", "remove", "--force", str(wt), check=False)
            _git("branch", "-D", branch, check=False)
            _git("worktree", "add", "-b", branch, str(wt), "HEAD")
        except Exception as e:
            _say("coder", f"I couldn't make a safe copy of the app: {e}")
            _set(cid, status="failed")
            return
        _say("coder", "Building it on a copy of the app. Nothing changes for you until you press Apply.")
        files = {f: read_file(f, wt) for f in ch["plan"].get("files", [])}
        design = concept_html(cid, concept) if concept is not None else ""
        prompt = (f"Request: {ch['request']}\nPlan: {json.dumps(ch['plan'])}\n"
                  + (f"\nApproved design (match it):\n{design[:6000]}\n" if design else "")
                  + "".join(f"\n===== {f} =====\n{t[:14000]}\n" for f, t in files.items()))
        changed, errors, checks = [], [], []
        for attempt in range(3):
            try:
                m = team.call_model([{"role": "system", "content": CODE_SYS}, {"role": "user", "content": prompt}], temperature=0.2,
                                     role="coder")
            except Exception as e:
                errors = [str(e)]
                break
            got, errors = _apply_blocks(m["content"], wt)
            changed += [g for g in got if g not in changed]
            checks = _checks(wt, changed) if changed else []
            bad = [c for c in checks if not c["ok"]]
            if changed and not errors and not bad:
                break
            prompt += ("\n\nYour last edits had problems. Fix them with new edit blocks against the CURRENT files:\n"
                       + "\n".join(errors + [f"{c['name']}: {c['detail']}" for c in bad])
                       + "".join(f"\n===== {f} (current) =====\n{read_file(f, wt)[:14000]}\n" for f in changed))
            _say("coder", f"First try had problems ({len(errors) + len(bad)}). Fixing them.")
        if not changed:
            _say("coder", "I couldn't produce a working change. " + "; ".join(errors)[:300])
            _set(cid, status="failed", checks=checks)
            return
        _git("add", "-A", cwd=wt)
        _git("commit", "-m", f"Coding crew: {ch['request'][:70]}", cwd=wt)
        stats = []
        for line in _git("diff", "--numstat", "HEAD~1", "HEAD", cwd=wt).splitlines():
            a, d, f = line.split("\t")
            stats.append({"file": f, "added": a, "removed": d})
        try:
            rv = team.ask_json(role="designer", system="You are the Designer. Review this change for the app's style and obvious problems. "
                               "JSON only: {\"ok\": true/false, \"note\": \"one sentence\"}",
                               user=_git("show", "--stat", "-p", "HEAD", cwd=wt)[:12000])
            checks.append({"name": "Designer review", "ok": bool(rv.get("ok", True)), "detail": rv.get("note", "")})
        except Exception:
            pass
        all_ok = all(c["ok"] for c in checks)
        _set(cid, status="review", files=stats, checks=checks)
        _say("planner", ("Done and checked. " if all_ok else "Done, but some checks failed. ")
             + "Press Preview to try the changed app live next to this one, then Apply (or Discard).",
             {"change": cid, "review": True})


# ------------------------------------------------------------------ repo, saving, live preview
def git_ok() -> bool:
    return bool(shutil.which("git"))


def ensure_repo() -> bool:
    """The coding crew works with git (safe copies, apply, undo). Installed copies start as a fresh repo."""
    if not git_ok():
        return False
    if not (ROOT / ".git").exists():
        _git("init", "-q", check=False)
        _git("add", "-A", check=False)
        _git("commit", "-q", "-m", "ClipperLocal installed", check=False)
    return (ROOT / ".git").exists()


def save_local(reason: str) -> bool:
    """Commit anything edited by hand (or by an update) so applying/undoing never loses it."""
    if _git("status", "--porcelain", check=False).strip():
        _git("add", "-A", check=False)
        _git("commit", "-q", "-m", reason, check=False)
        return True
    return False


PREVIEW_PORT = 8798
_preview = {"cid": None, "proc": None, "dir": None}


def preview_start(cid: int) -> dict:
    """Run the changed app (from its safe copy) next to the real one, with a snapshot of today's data,
    so the operator can click around the new screens before applying. The real app keeps running."""
    ch = get(cid)
    wt = WT_DIR / (ch.get("branch") or "-")
    if not wt.exists():
        return {"error": "This change has no copy to preview."}
    preview_stop()
    snap = config.DATA / "preview"
    shutil.rmtree(snap, ignore_errors=True)
    snap.mkdir(parents=True, exist_ok=True)
    for name in ("clipper.db", "settings.json"):
        if (config.DATA / name).exists():
            if name.endswith(".db"):
                import sqlite3
                with sqlite3.connect(config.DATA / name) as src, sqlite3.connect(snap / name) as dst:
                    src.backup(dst)
            else:
                shutil.copy2(config.DATA / name, snap / name)
    if (ROOT / "config.yaml").exists():
        shutil.copy2(ROOT / "config.yaml", wt / "config.yaml")
    env = {**os.environ, "CLIPPERLOCAL_DATA": str(snap), "CLIPPERLOCAL_PORT": str(PREVIEW_PORT), "CLIPPERLOCAL_PREVIEW": "1"}
    log = open(snap / "preview.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "app.server", "--no-browser", "--no-workers"], cwd=wt, env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    _preview.update(cid=cid, proc=proc, dir=snap)
    for _ in range(60):
        time.sleep(0.5)
        if proc.poll() is not None:
            return {"error": "The changed app didn't start: " + (snap / "preview.log").read_text(errors="ignore")[-400:]}
        try:
            if requests.get(f"http://127.0.0.1:{PREVIEW_PORT}/api/health", timeout=1).ok:
                return {"ok": True, "url": f"http://127.0.0.1:{PREVIEW_PORT}/"}
        except Exception:
            pass
    return {"error": "The preview took too long to start."}


def preview_stop():
    p = _preview.get("proc")
    if p and p.poll() is None:
        p.kill()
        try:
            p.wait(5)
        except Exception:
            pass
    _preview.update(cid=None, proc=None)


# ------------------------------------------------------------------ apply / undo / discard
def _what_changed(rev_range: str) -> dict:
    files = [f for f in _git("diff", "--name-only", *rev_range.split(), check=False).splitlines() if f]
    return {"files": files, "restart": any(f.endswith(".py") for f in files),
            "reload": any(f.startswith("desktop/ui/") for f in files)}


def apply(cid: int) -> dict:
    ch = get(cid)
    if ch["status"] != "review":
        return {"error": f"change is {ch['status']}, not ready"}
    branch = ch["branch"]
    if _preview.get("cid") == cid:
        preview_stop()
    save_local(f"Saved local edits before applying change #{cid}")
    try:
        _git("merge", "--no-edit", "--no-ff", branch, "-m", f"Apply change #{cid}: {ch['request'][:60]}")
    except RuntimeError as e:
        _git("merge", "--abort", check=False)
        return {"error": f"Couldn't apply: {e}"}
    sha = _git("rev-parse", "HEAD").strip()
    _git("worktree", "remove", "--force", str(WT_DIR / branch), check=False)
    _set(cid, status="applied", commit_sha=sha)
    what = _what_changed("HEAD^1 HEAD")
    brain.append("Past changes", f"#{cid} {ch['request']} ({time.strftime('%d %b')}) [applied] files: {', '.join(what['files'])}",
                 "coding", "Coder", "coding")
    how = ("The engine restarts by itself in a few seconds to load the new code." if what["restart"]
           else "Only screens changed, so they just reload. No restart needed.")
    _say("planner", f"Applied and saved change #{cid}. {how} You can undo it anytime.")
    return {"ok": True, **what}


def undo(cid: int) -> dict:
    ch = get(cid)
    if ch["status"] != "applied":
        return {"error": "only applied changes can be undone"}
    save_local(f"Saved local edits before undoing change #{cid}")
    try:
        _git("revert", "--no-edit", "-m", "1", ch["commit_sha"])
    except RuntimeError as e:
        _git("revert", "--abort", check=False)
        return {"error": f"Couldn't undo: {e}"}
    _set(cid, status="undone")
    brain.append("Past changes", f"#{cid} undone ({time.strftime('%d %b')})", "coding", "Coder", "coding")
    _say("planner", f"Undid change #{cid}.")
    return {"ok": True, **_what_changed("HEAD~1 HEAD")}


def discard(cid: int) -> dict:
    ch = get(cid)
    if _preview.get("cid") == cid:
        preview_stop()
    if ch.get("branch"):
        _git("worktree", "remove", "--force", str(WT_DIR / ch["branch"]), check=False)
        _git("branch", "-D", ch["branch"], check=False)
    _set(cid, status="discarded")
    _say("planner", f"Discarded change #{cid}. Nothing was changed.")
    return {"ok": True}


def diff(cid: int) -> str:
    ch = get(cid)
    wt = WT_DIR / (ch.get("branch") or "")
    return _git("show", "HEAD", cwd=wt) if wt.exists() else ""

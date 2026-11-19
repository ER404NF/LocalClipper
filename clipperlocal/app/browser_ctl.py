"""The crew's hands in the account tabs.

Windows desktop app: every account tab is a WebView2 inside the app's Browser window, started with its own
profile, the Italy box proxy and a private DevTools port on 127.0.0.1. The engine attaches to that port with
Playwright, so the crew works in the SAME signed-in tab the operator sees.
Elsewhere (Mac/Linux or app closed): a separate Chromium window per account, same profile idea, same proxy."""
import base64
import json
import os
import random
import shutil
import sys
import threading
import time
from pathlib import Path

from . import channels, config, db, network, pipeline, playbooks, uiagent

TAB_BASE_PORT = 9301
_locks: dict[str, threading.Lock] = {}
_stop: set[str] = set()          # tabs the operator took over
PAUSED = threading.Event()       # global "Pause everything"
APP_COMMANDS: list[dict] = []    # read by the desktop app (it polls /api/app/commands)

SNAPSHOT_JS = r"""
() => {
  const sel = 'a,button,input,textarea,select,[role=button],[role=tab],[role=menuitem],[role=option],[role=checkbox],' +
              '[role=switch],[role=radio],[role=textbox],[role=combobox],[contenteditable=true],[contenteditable=""]';
  const out = []; let n = 0;
  document.querySelectorAll('[data-cl-id]').forEach(e => e.removeAttribute('data-cl-id'));
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    const isFile = el.tagName === 'INPUT' && el.type === 'file';
    const visible = r.width > 2 && r.height > 2 && st.visibility !== 'hidden' && st.display !== 'none' &&
                    r.bottom > 0 && r.top < innerHeight * 1.5;
    if (!visible && !isFile) continue;
    n += 1; el.setAttribute('data-cl-id', String(n));
    const label = (el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('title') ||
                   (el.labels && el.labels[0] && el.labels[0].innerText) || el.innerText || el.value || '').trim().replace(/\s+/g, ' ');
    out.push({id: n, tag: el.tagName.toLowerCase(), kind: isFile ? 'file-input' : (el.getAttribute('role') || el.tagName.toLowerCase()),
              label: label.slice(0, 90), type: el.type || '', value: (el.type === 'password') ? '' : String(el.value || '').slice(0, 40),
              state: [el.disabled ? 'disabled' : '', el.checked ? 'checked' : '', el.getAttribute('aria-checked') === 'true' ? 'on' : '',
                      el.getAttribute('aria-selected') === 'true' ? 'selected' : ''].filter(Boolean).join(',')});
    if (n >= 200) break;
  }
  return {url: location.href, title: document.title, elements: out, text: (document.body ? document.body.innerText : '').slice(0, 4000)};
}
"""

DROP_JS = r"""
async ([id, name, b64]) => {
  const el = document.querySelector(`[data-cl-id="${id}"]`) || document.body;
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const file = new File([bytes], name, {type: 'video/mp4'});
  const dt = new DataTransfer(); dt.items.add(file);
  for (const t of ['dragenter', 'dragover', 'drop']) {
    el.dispatchEvent(new DragEvent(t, {bubbles: true, cancelable: true, dataTransfer: dt}));
  }
  return true;
}
"""


# ------------------------------------------------------------------ tabs registry (shared with the desktop app)
def tabs() -> list[dict]:
    cfg = config.load()
    proxy = network.proxy_url(cfg)
    out = []
    for i, ch in enumerate(sorted(channels.all_channels(cfg), key=lambda c: c["key"])):
        out.append({"key": ch["key"], "platform": ch["platform"], "name": ch["name"], "home_url": ch["home_url"],
                    "upload_url": ch["upload_url"], "cdp_port": TAB_BASE_PORT + i,
                    "proxy": proxy if ch.get("proxy", "italy") == "italy" else (ch.get("proxy") if ch.get("proxy") not in ("", "direct") else ""),
                    "profile": str(config.DATA / "profiles" / ch["key"].replace(":", "_"))})
    return out


def tab(key: str) -> dict:
    for t in tabs():
        if t["key"] == key:
            return t
    raise ValueError(f"No account tab called {key}. Known: {[t['key'] for t in tabs()]}")


def clip_file(clip_id: int, version: str | None = None) -> str:
    c = db.one("SELECT * FROM clips WHERE id=?", (clip_id,))
    if not c or not c["render_path"]:
        raise ValueError(f"clip {clip_id} isn't rendered")
    variants = json.loads(c["variants"] or "{}")
    src = variants.get(version or "", c["render_path"])
    dst = config.EXPORT_DIR / f"{clip_id:04d}_{version or 'main'}.mp4"
    if not dst.exists() or dst.stat().st_mtime < Path(src).stat().st_mtime:
        shutil.copy(src, dst)
    return str(dst)


def _chrome_path() -> str | None:
    for p in [os.environ.get("CLIPPERLOCAL_CHROME", ""), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium"]:
        if p and Path(p).exists():
            return p
    return None


def _cdp_up(port: int) -> bool:
    import socket
    s = socket.socket()
    s.settimeout(0.4)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


class Session:
    """Context manager giving a Playwright page for one account tab."""

    def __init__(self, key: str, headless: bool = False):
        self.t = tab(key)
        self.headless = headless
        self.pw = self.browser = self.ctx = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        t = self.t
        mode = (config.load().get("browser") or {}).get("mode", "auto")
        if mode in ("auto", "app") and sys.platform == "win32":
            if not _cdp_up(t["cdp_port"]):
                APP_COMMANDS.append({"cmd": "open_browser", "tab": t["key"]})
                for _ in range(40):
                    time.sleep(0.5)
                    if _cdp_up(t["cdp_port"]):
                        break
            if _cdp_up(t["cdp_port"]):
                self.browser = self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{t['cdp_port']}")
                self.ctx = self.browser.contexts[0]
                self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
                self.page.bring_to_front()
                return self
            if mode == "app":
                raise RuntimeError("The app's Browser window isn't open. Open ClipperLocal and try again.")
        # standalone window, own profile folder
        kw = {"headless": self.headless, "viewport": {"width": 1280, "height": 860}}
        exe = _chrome_path()
        if exe:
            kw["executable_path"] = exe
        if t["proxy"]:
            kw["proxy"] = {"server": t["proxy"]}
        if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0:
            kw["args"] = ["--no-sandbox"]
        self.ctx = self.pw.chromium.launch_persistent_context(t["profile"] + "_standalone", **kw)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def __exit__(self, *exc):
        try:
            if self.browser is None and self.ctx is not None:
                self.ctx.close()          # standalone: close our own window
        finally:
            if self.pw:
                self.pw.stop()            # attached (app) tabs stay open; we only disconnect


def _shot(page, key: str):
    try:
        page.screenshot(path=str(config.DATA / "shots" / f"tab_{key.replace(':', '_')}.jpg"), type="jpeg", quality=55)
    except Exception:
        pass


def _domain_ok(platform: str, url: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    return any(host == d or host.endswith("." + d) for d in playbooks.ALLOWED_DOMAINS.get(platform, []))


def run_task(key: str, goal: str, files: list[str] | None = None, who: str = "Clipper A", hints: str = "",
             start_url: str | None = None, max_steps: int = 30, headless: bool = False) -> dict:
    """Agent loop in one account tab. Returns {ok, result | error | question, steps}."""
    files = files or []
    t = tab(key)
    if t["proxy"]:
        ok, why = network.safe_to_post()
        if not ok:
            return {"ok": False, "error": f"Stopped: {why}. The tabs only work through the Italy box."}
    lock = _locks.setdefault(key, threading.Lock())
    if not lock.acquire(timeout=5):
        return {"ok": False, "error": f"{key} is busy with another task"}
    place = f"tab:{key}"
    _stop.discard(key)
    db.log(place, who, goal, "Started", "now")
    history, scrolls = [], 0
    try:
        with Session(key, headless=headless) as s:
            page = s.page
            if start_url:
                page.goto(start_url, wait_until="domcontentloaded", timeout=45000)
            for step in range(max_steps):
                if PAUSED.is_set() or key in _stop:
                    db.log(place, who, goal, "Paused by you", "paused")
                    return {"ok": False, "error": "paused by the operator", "steps": step}
                time.sleep(random.uniform(0.7, 1.8))  # human pace
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                snap = page.evaluate(SNAPSHOT_JS)
                _shot(page, key)
                shot = None
                if (config.load().get("browser") or {}).get("use_vision"):
                    shot = base64.b64encode(page.screenshot(type="jpeg", quality=50)).decode()
                act = uiagent.decide(who, f"the {t['platform']} account tab '{key}' (url {snap['url']})", goal, hints,
                                     snap["elements"], snap["text"], history, files, shot)
                a = act.get("action")
                desc = f"{a} {act.get('id', '')} {act.get('text', '') or act.get('key', '') or act.get('url', '')}".strip()
                el = page.locator(f'[data-cl-id="{act.get("id")}"]').first
                try:
                    if a == "done":
                        db.log(place, who, goal, act.get("result", "Done"), "done")
                        return {"ok": True, "result": act.get("result", ""), "steps": step + 1}
                    if a == "fail":
                        db.log(place, who, goal, act.get("result", "Failed"), "failed")
                        return {"ok": False, "error": act.get("result", "couldn't finish"), "steps": step + 1}
                    if a == "ask":
                        db.log(place, who, goal, "Needs you: " + act.get("result", ""), "waiting")
                        return {"ok": False, "needs_human": act.get("result", ""), "steps": step + 1}
                    if a == "click":
                        el.click(timeout=8000)
                    elif a == "type":
                        tag = (el.evaluate("e => e.tagName") or "").lower()
                        if tag in ("input", "textarea"):
                            el.fill(act.get("text", ""), timeout=8000)
                        else:  # rich editors (TikTok/Instagram captions)
                            el.click(timeout=8000)
                            page.keyboard.press("Control+A")
                            page.keyboard.type(act.get("text", ""), delay=15)
                    elif a == "upload":
                        path = files[int(act.get("file") or 0)]
                        is_input = el.count() and el.evaluate("e => e.tagName === 'INPUT' && e.type === 'file'")
                        target = el if is_input else page.locator("input[type=file]").first
                        if target.count():
                            target.set_input_files(path, timeout=20000)
                        else:  # no file input: drop the file onto the area like a drag from the desktop
                            data = base64.b64encode(Path(path).read_bytes()).decode()
                            page.evaluate(DROP_JS, [act.get("id"), Path(path).name, data])
                        desc = f"Dropped {Path(path).name}"
                    elif a == "press":
                        page.keyboard.press(act.get("key") or "Enter")
                    elif a == "scroll":
                        scrolls += 1
                        if scrolls > 6:
                            history.append("scroll refused: stop scrolling, act on what you see or ask")
                            continue
                        page.mouse.wheel(0, 650)
                    elif a == "wait":
                        time.sleep(4)
                    elif a == "goto":
                        url = act.get("url", "")
                        if not _domain_ok(t["platform"], url):
                            history.append(f"goto {url} refused: stay on {t['platform']}")
                            continue
                        page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    else:
                        history.append(f"unknown action {a}")
                        continue
                    history.append(f"OK: {desc} ({act.get('thought', '')[:80]})")
                    db.log(place, who, goal, desc, "done")
                except Exception as e:
                    history.append(f"FAILED: {desc}: {str(e)[:120]}")
                    db.log(place, who, goal, f"Couldn't {desc}", "retry")
            return {"ok": False, "error": "too many steps without finishing", "steps": max_steps}
    except Exception as e:
        db.log(place, who, goal, f"Error: {e}", "failed")
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"[:300]}
    finally:
        lock.release()


def post(key: str, clip_id: int, caption: str, title: str, when: str | None, who: str) -> dict:
    """Upload + post or schedule one clip in an account tab, following the platform playbook."""
    t = tab(key)
    version = {"tiktok": "tiktok", "instagram": "reels", "youtube": "shorts"}[t["platform"]]
    f = clip_file(clip_id, version)
    goal = (f"Post the video file as a new {t['platform']} post. Title: {title!r}. Caption: {caption!r}. "
            + (f"Schedule it for {when}." if when else "Post it now."))
    return run_task(key, goal, [f], who=who, hints=playbooks.tab_hint(t["platform"], "post"), start_url=t["upload_url"])


def take_over(key: str):
    _stop.add(key)
    APP_COMMANDS.append({"cmd": "open_browser", "tab": key})


def activity(key: str, limit: int = 20) -> list[dict]:
    return db.rows("SELECT * FROM activity WHERE place=? ORDER BY id DESC LIMIT ?", (f"tab:{key}", limit))

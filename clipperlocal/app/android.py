"""The crew's hands on the dedicated Android phone (USB, ADB). Used for Instagram's Edits app.

Setup once: Developer options -> USB debugging on, plug into the PC, tap "Allow" on the phone.
The phone's internet goes through the Italy box with the Tailscale app (exit node = the Italy box)."""
import random
import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from . import config, db, playbooks, uiagent

_lock = threading.Lock()
PHONE_DIR = "/sdcard/DCIM/ClipperLocal"


def _adb_bin() -> str:
    cfg = config.load()
    b = (cfg.get("phone") or {}).get("adb") or "adb"
    if shutil.which(b):
        return b
    for p in [Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe", Path("C:/platform-tools/adb.exe"),
              Path.home() / "platform-tools/adb"]:
        if p.exists():
            return str(p)
    return b


def adb(*args, binary: bool = False, timeout: int = 60):
    cfg = config.load()
    serial = (cfg.get("phone") or {}).get("serial")
    cmd = [_adb_bin()] + (["-s", serial] if serial else []) + list(args)
    p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).decode(errors="ignore").strip()[:300] or f"adb {args[0]} failed")
    return p.stdout if binary else p.stdout.decode(errors="ignore")


def shell(cmd: str, timeout: int = 60) -> str:
    return adb("shell", cmd, timeout=timeout)


def status() -> dict:
    out = {"connected": False, "model": "", "battery": "", "charging": False, "free": "", "vpn": False,
           "edits": "", "error": ""}
    try:
        devs = [l for l in adb("devices", "-l").splitlines()[1:] if l.strip()]
        if not devs:
            out["error"] = "No phone found. Plug it in and allow USB debugging."
            return out
        if "unauthorized" in devs[0]:
            out["error"] = "Tap 'Allow' on the phone's USB debugging prompt."
            return out
        out["connected"] = True
        m = re.search(r"model:(\S+)", devs[0])
        out["model"] = m.group(1).replace("_", " ") if m else "Android"
        bat = shell("dumpsys battery")
        lvl = re.search(r"level: (\d+)", bat)
        out["battery"] = f"{lvl.group(1)}%" if lvl else ""
        out["charging"] = bool(re.search(r"(AC|USB) powered: true", bat))
        df = shell("df -h /sdcard | tail -1").split()
        out["free"] = df[3] if len(df) > 3 else ""
        out["vpn"] = "VPN" in shell("dumpsys connectivity | grep -m 3 -i 'type: VPN\\|VPN CONNECTED' || true")
        out["edits"] = edits_package() or ""
    except FileNotFoundError:
        out["error"] = "adb isn't installed. Run the setup script again."
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def edits_package() -> str | None:
    cfg = config.load()
    pkg = (cfg.get("phone") or {}).get("edits_package")
    if pkg:
        return pkg
    pk = [l.replace("package:", "").strip() for l in shell("pm list packages").splitlines()]
    hits = [p for p in pk if "edits" in p and ("instagram" in p or "facebook" in p or "meta" in p)] or [p for p in pk if p.endswith(".edits")]
    return hits[0] if hits else None


def push_to_gallery(path: str) -> str:
    name = Path(path).name
    shell(f"mkdir -p {PHONE_DIR}")
    adb("push", path, f"{PHONE_DIR}/{name}", timeout=300)
    target = f"{PHONE_DIR}/{name}"
    for cmd in (f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{target}",
                "content call --uri content://media/external/file --method scan_volume --arg external_primary"):
        try:
            shell(cmd)
        except Exception:
            pass
    return target


def screenshot() -> Path:
    png = adb("exec-out", "screencap", "-p", binary=True)
    p = config.DATA / "shots" / "phone.png"
    p.write_bytes(png)
    return p


BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def parse_ui(xml_text: str) -> list[dict]:
    """uiautomator XML -> numbered list of things on screen (with tap centers)."""
    start = xml_text.find("<?xml")
    end = xml_text.rfind("</hierarchy>")
    if start < 0 or end < 0:
        return []
    root = ET.fromstring(xml_text[start:end + len("</hierarchy>")])
    out, n = [], 0
    for node in root.iter("node"):
        a = node.attrib
        text, desc = a.get("text", "").strip(), a.get("content-desc", "").strip()
        clickable = a.get("clickable") == "true" or a.get("long-clickable") == "true"
        editable = "EditText" in a.get("class", "")
        if not (clickable or editable or text or desc):
            continue
        m = BOUNDS.match(a.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        n += 1
        rid = a.get("resource-id", "").split("/")[-1]
        out.append({"id": n, "kind": ("input" if editable else "button" if clickable else "text"),
                    "label": (text or desc or rid)[:90], "type": a.get("class", "").split(".")[-1],
                    "state": ",".join(s for s, k in (("checked", "checked"), ("selected", "selected")) if a.get(k) == "true"),
                    "x": (x1 + x2) // 2, "y": (y1 + y2) // 2, "box": [x1, y1, x2, y2]})
    return out


def dump_ui() -> list[dict]:
    try:
        xml = adb("exec-out", "uiautomator", "dump", "/dev/tty", timeout=30)
        if "<hierarchy" not in xml:
            raise RuntimeError("empty")
    except Exception:
        shell("uiautomator dump /sdcard/cl_ui.xml", timeout=30)
        xml = shell("cat /sdcard/cl_ui.xml")
    return parse_ui(xml)


def _type(text: str):
    safe = re.sub(r"[^\x20-\x7E\n]", "", text)  # adb 'input text' only takes plain ASCII
    for line_i, line in enumerate(safe.split("\n")):
        if line_i:
            shell("input keyevent 66")
        if line:
            esc = re.sub(r"([\\\"'`$&|;<>()*?!#~^{}\[\]])", r"\\\1", line).replace(" ", "%s")
            shell(f"input text \"{esc}\"")


def run_task(goal: str, files: list[str] | None = None, who: str = "Clipper B", hints: str = "",
             open_edits: bool = True, max_steps: int = 35) -> dict:
    from .browser_ctl import PAUSED
    files = files or []
    if not _lock.acquire(timeout=5):
        return {"ok": False, "error": "the phone is busy with another task"}
    place = "phone"
    db.log(place, who, goal, "Started", "now")
    history = []
    try:
        st = status()
        if not st["connected"]:
            return {"ok": False, "error": st["error"]}
        if config.load()["autopilot"].get("require_italy_box", True) and not st["vpn"]:
            return {"ok": False, "error": "The phone isn't on the Italy box. Turn on the Tailscale exit node on the phone."}
        shell("svc power stayon usb")
        for f in files:
            push_to_gallery(f)
            db.log(place, who, goal, f"Copied {Path(f).name} to the gallery", "done")
        if open_edits:
            pkg = edits_package()
            if not pkg:
                return {"ok": False, "error": "Edits isn't installed on the phone"}
            shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
            time.sleep(3)
        hints = hints or playbooks.PHONE["edits_post"]
        for step in range(max_steps):
            if PAUSED.is_set():
                db.log(place, who, goal, "Paused by you", "paused")
                return {"ok": False, "error": "paused by the operator"}
            time.sleep(random.uniform(0.8, 1.6))
            els = dump_ui()
            try:
                screenshot()
            except Exception:
                pass
            act = uiagent.decide(who, "the Android phone", goal, hints, els,
                                 " | ".join(e["label"] for e in els if e["kind"] == "text")[:2500], history,
                                 [f"(already in the gallery) {Path(f).name}" for f in files])
            a = act.get("action")
            el = next((e for e in els if e["id"] == act.get("id")), None)
            desc = f"{a} {el['label'] if el else ''} {act.get('text', '')}".strip()
            try:
                if a == "done":
                    db.log(place, who, goal, act.get("result", "Done"), "done")
                    return {"ok": True, "result": act.get("result", ""), "steps": step + 1}
                if a in ("fail", "ask"):
                    db.log(place, who, goal, act.get("result", ""), "waiting" if a == "ask" else "failed")
                    return {"ok": False, ("needs_human" if a == "ask" else "error"): act.get("result", "")}
                if a in ("click", "upload"):
                    if not el:
                        raise ValueError("no such element")
                    shell(f"input tap {el['x']} {el['y']}")
                elif a == "type":
                    if el:
                        shell(f"input tap {el['x']} {el['y']}")
                    _type(act.get("text", ""))
                elif a == "press":
                    key = {"enter": 66, "back": 4, "home": 3}.get((act.get("key") or "enter").lower(), 66)
                    shell(f"input keyevent {key}")
                elif a == "scroll":
                    shell("input swipe 540 1500 540 700 300")
                elif a == "wait":
                    time.sleep(4)
                else:
                    history.append(f"unknown action {a}")
                    continue
                history.append(f"OK: {desc}")
                db.log(place, who, goal, desc, "done")
            except Exception as e:
                history.append(f"FAILED: {desc}: {str(e)[:100]}")
                db.log(place, who, goal, f"Couldn't {desc}", "retry")
        return {"ok": False, "error": "too many steps without finishing"}
    except Exception as e:
        db.log(place, who, goal, f"Error: {e}", "failed")
        return {"ok": False, "error": str(e)[:300]}
    finally:
        _lock.release()


def post_reel(clip_file: str, caption: str, account: str, sound: str | None, who: str) -> dict:
    goal = (f"Post the newest video in the gallery as an Instagram Reel on the account '{account}' using Edits. "
            + (f"Add the sound '{sound}' at low volume. " if sound else "") + f"Caption: {caption!r}")
    return run_task(goal, [clip_file], who=who)

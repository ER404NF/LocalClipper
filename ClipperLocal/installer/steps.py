"""ClipperLocal installer steps (run by ClipperLocal-Setup.exe after it has set up Python with uv).

Every step is safe to run again: finished steps are skipped, half-finished downloads resume.
Downloads go straight from the official sources (no winget, no Microsoft Store, no admin needed):
  ffmpeg (BtbN/gyan), adb (Google), Git (git-for-windows MinGit), Ollama (GitHub release), the AI models (Ollama).
Run:  .venv\\Scripts\\python.exe installer\\steps.py            (everything)
      .venv\\Scripts\\python.exe installer\\steps.py models     (one step)
      .venv\\Scripts\\python.exe installer\\steps.py admin      (firewall + Tailscale, needs admin)"""
import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
DL = TOOLS / "downloads"
LOG = ROOT / "data" / "install.log"
WINDOWS = os.name == "nt"
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONUTF8", "1")
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

import requests  # noqa: E402  (installed into .venv just before this runs)

UA = {"User-Agent": "ClipperLocal-installer"}


# ------------------------------------------------------------------ output
def say(msg: str):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(msg, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


class StepFailed(Exception):
    pass


# ------------------------------------------------------------------ downloads
def download(url: str, dest: Path, what: str, tries: int = 5) -> Path:
    """Resumable download with retries and progress every ~5%."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, tries + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {**UA, **({"Range": f"bytes={have}-"} if have else {})}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(20, 60), allow_redirects=True) as r:
                if r.status_code == 416:  # already complete
                    break
                if have and r.status_code == 200:  # server ignored the resume: start over
                    have = 0
                    part.unlink(missing_ok=True)
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0) + have
                done, shown = have, -5
                mode = "ab" if have else "wb"
                with open(part, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            pct = int(100 * done / total)
                            if pct >= shown + 5:
                                shown = pct
                                say(f"    {what}: {pct}%  ({done / 1e6:.0f} of {total / 1e6:.0f} MB)")
                if total and done < total:
                    raise IOError(f"connection dropped at {done}/{total} bytes")
            break
        except Exception as e:
            if attempt == tries:
                raise StepFailed(f"Couldn't download {what}: {e}")
            wait = 5 * attempt
            say(f"    {what}: {e.__class__.__name__}, trying again in {wait}s (attempt {attempt + 1}/{tries})")
            time.sleep(wait)
    part.replace(dest)
    return dest


def github_asset(repo: str, match, what: str) -> str:
    """URL of the newest release asset whose name passes match(name)."""
    r = requests.get(f"https://api.github.com/repos/{repo}/releases/latest", headers=UA, timeout=30)
    r.raise_for_status()
    for a in r.json().get("assets", []):
        if match(a["name"]):
            return a["browser_download_url"]
    raise StepFailed(f"No {what} download found in the latest {repo} release")


def unzip_into(zip_path: Path, target: Path, strip_top: bool = True):
    """Extract a zip to target. strip_top: if everything sits in one top folder, drop that folder."""
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    inner = tmp
    kids = list(tmp.iterdir())
    if strip_top and len(kids) == 1 and kids[0].is_dir():
        inner = kids[0]
    shutil.rmtree(target, ignore_errors=True)
    shutil.move(str(inner), str(target))
    shutil.rmtree(tmp, ignore_errors=True)


def _have(cmd: str, local: Path) -> bool:
    return local.exists() or bool(shutil.which(cmd))


# ------------------------------------------------------------------ steps
def step_webview2():
    """The app's window and account tabs run on Microsoft WebView2 (built into Windows 11, sometimes missing on 10)."""
    if not WINDOWS:
        return
    import winreg
    key = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, key), (winreg.HKEY_CURRENT_USER, key.replace("WOW6432Node\\", ""))):
        try:
            with winreg.OpenKey(hive, path) as k:
                if winreg.QueryValueEx(k, "pv")[0] not in ("", "0.0.0.0"):
                    return say("  WebView2 (app window): already installed")
        except OSError:
            pass
    say("  WebView2 (app window): installing")
    exe = download("https://go.microsoft.com/fwlink/p/?LinkId=2124703", DL / "webview2setup.exe", "WebView2")
    subprocess.run([str(exe), "/silent", "/install"], timeout=900)
    say("  WebView2: ready")


def step_ffmpeg():
    local = TOOLS / "ffmpeg" / "bin" / ("ffmpeg.exe" if WINDOWS else "ffmpeg")
    if _have("ffmpeg", local):
        return say("  ffmpeg: already installed")
    if not WINDOWS:
        raise StepFailed("Install ffmpeg with your package manager (brew install ffmpeg / apt install ffmpeg)")
    say("  ffmpeg: downloading (video editing, ~150 MB)")
    z = DL / "ffmpeg.zip"
    try:
        download("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip", z, "ffmpeg")
    except StepFailed:
        download("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", z, "ffmpeg (mirror)")
    unzip_into(z, TOOLS / "ffmpeg")
    z.unlink(missing_ok=True)
    if not local.exists():
        raise StepFailed("ffmpeg download didn't contain bin/ffmpeg.exe")
    say("  ffmpeg: ready")


def step_adb():
    local = TOOLS / "platform-tools" / ("adb.exe" if WINDOWS else "adb")
    if _have("adb", local):
        return say("  adb (phone control): already installed")
    if not WINDOWS:
        return say("  adb: skipped (install android-platform-tools if you use the phone)")
    say("  adb (phone control): downloading")
    z = DL / "platform-tools.zip"
    download("https://dl.google.com/android/repository/platform-tools-latest-windows.zip", z, "adb")
    unzip_into(z, TOOLS / "platform-tools")
    z.unlink(missing_ok=True)
    say("  adb: ready")


def step_git():
    local = TOOLS / "git" / "cmd" / "git.exe"
    if _have("git", local):
        return say("  Git (coding crew safe copies): already installed")
    if not WINDOWS:
        raise StepFailed("Install git with your package manager")
    say("  Git: downloading MinGit (coding crew safe copies)")
    try:
        url = github_asset("git-for-windows/git", lambda n: n.startswith("MinGit-") and n.endswith("-64-bit.zip")
                           and "busybox" not in n, "MinGit")
    except Exception:
        url = "https://github.com/git-for-windows/git/releases/download/v2.51.0.windows.1/MinGit-2.51.0-64-bit.zip"
    z = DL / "mingit.zip"
    download(url, z, "Git")
    unzip_into(z, TOOLS / "git", strip_top=False)
    z.unlink(missing_ok=True)
    say("  Git: ready")


def _ollama_found() -> str | None:
    from app import winenv
    return winenv.ollama_exe()


def _download_ollama():
    say("  Ollama: downloading (runs the AI, ~1.5 GB with GPU support)")
    url = github_asset("ollama/ollama", lambda n: n == "ollama-windows-amd64.zip", "Ollama")
    z = DL / "ollama.zip"
    download(url, z, "Ollama")
    say("  Ollama: unpacking")
    unzip_into(z, TOOLS / "ollama", strip_top=False)
    z.unlink(missing_ok=True)
    os.environ["PATH"] = str(TOOLS / "ollama") + os.pathsep + os.environ.get("PATH", "")


def step_ollama():
    from app import winenv
    found = _ollama_found()
    if found:
        say(f"  Ollama (runs the AI): found at {found}")
    elif not WINDOWS:
        raise StepFailed("Install Ollama from https://ollama.com/download, then run this again")
    else:
        _download_ollama()
    if WINDOWS:  # lets two agents think at once, also for the Ollama tray app after its next start
        subprocess.run(["setx", "OLLAMA_NUM_PARALLEL", "2"], capture_output=True)
    if not winenv.ensure_ollama(wait=40):
        own = TOOLS / "ollama" / "ollama.exe"
        if WINDOWS and not own.exists():
            # an older Ollama install (e.g. from a half-finished setup) didn't start: use our own copy instead
            say("  Ollama: the installed copy didn't start, getting a fresh one")
            _download_ollama()
            if winenv.ensure_ollama(wait=40):
                return say("  Ollama: running")
        raise StepFailed("Ollama is installed but didn't start. Restart the PC and run the installer again.")
    say("  Ollama: running")


def _hardware() -> tuple[float, float]:
    vram = 0.0
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15).stdout
        vram = max(float(x) for x in out.split()) / 1024 if out.strip() else 0.0
    except Exception:
        pass
    ram = 0.0
    if WINDOWS:
        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        ram = m.ullTotalPhys / 1024 ** 3
    else:
        try:
            ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
        except Exception:
            pass
    return round(vram, 1), round(ram, 1)


def step_config():
    if not (ROOT / "config.yaml").exists():
        shutil.copy2(ROOT / "config.example.yaml", ROOT / "config.yaml")
        say("  config.yaml created (add Twitch keys + streamers later)")
    from app import config, models
    vram, ram = _hardware()
    rec = models.recommend(vram, ram)
    say(f"  This PC: {str(vram) + ' GB GPU memory' if vram else 'no NVIDIA GPU found'}, {ram:.0f} GB RAM")
    saved = json.loads(config.SETTINGS.read_text(encoding="utf-8")) if config.SETTINGS.exists() else {}
    for key in ("model", "coding_model"):
        if not (saved.get("team") or {}).get(key):  # never override a model the user picked in the app
            config.save_setting("team", key, rec[key])
    cfg = config.load()
    say(f"  AI models: {cfg['team']['model']} (Agent + production crew), {cfg['team']['coding_model']} (coding crew)")


def step_repo():
    from app import codecrew
    if not codecrew.git_ok():
        raise StepFailed("Git is missing")
    first = not (ROOT / ".git").exists()
    codecrew.ensure_repo()
    if not first:
        if codecrew.save_local("ClipperLocal updated by the installer"):
            say("  App code: saved this update as a version (coding crew can undo past it)")
    say("  App code: ready for the coding crew")


def _pull(name: str):
    url = "http://127.0.0.1:11434"
    have = {m["name"] for m in requests.get(f"{url}/api/tags", timeout=10).json().get("models", [])}
    if name in have or (":" not in name and f"{name}:latest" in have):
        return say(f"  {name}: already downloaded")
    say(f"  {name}: downloading (this is the big one, keep the window open)")
    for attempt in range(1, 6):
        try:
            shown, last = -2, ""
            with requests.post(f"{url}/api/pull", json={"name": name, "stream": True}, stream=True, timeout=(20, 600)) as r:
                for raw in r.iter_lines():
                    if not raw:
                        continue
                    d = json.loads(raw)
                    if d.get("error"):
                        raise RuntimeError(d["error"])
                    if d.get("total") and d.get("completed") is not None and d["total"] > 50e6:
                        pct = int(100 * d["completed"] / d["total"])
                        if pct >= shown + 2:
                            shown = pct
                            say(f"    {name}: {pct}%  ({d['completed'] / 1e9:.1f} of {d['total'] / 1e9:.1f} GB)")
                    elif d.get("status") and d["status"] != last and not d.get("total"):
                        last = d["status"]
                        if last in ("verifying sha256 digest", "writing manifest", "success"):
                            say(f"    {name}: {last}")
            return say(f"  {name}: ready")
        except Exception as e:
            if attempt == 5:
                raise StepFailed(f"Couldn't download {name}: {e}")
            say(f"    {name}: {str(e)[:120]}, resuming in {10 * attempt}s")
            time.sleep(10 * attempt)


def step_models():
    from app import config, winenv
    if not winenv.ensure_ollama(wait=40):
        raise StepFailed("Ollama isn't running")
    t = config.load()["team"]
    for name in dict.fromkeys([t["model"], t.get("coding_model") or t["model"]]):
        _pull(name)


def step_whisper():
    try:
        from faster_whisper.utils import download_model
        from app import config
        size = (config.load().get("whisper") or {}).get("model", "small")
        say(f"  Captions model (Whisper {size}): downloading")
        download_model(size)
        say("  Captions model: ready")
    except Exception as e:
        say(f"  Captions model: will download on first use ({str(e)[:100]})")


def step_admin():
    """Needs admin (the installer asks once): firewall rule for the phone share + Tailscale for the Italy box."""
    if not WINDOWS:
        return
    py = sys.executable
    subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", "name=ClipperLocal phone share"], capture_output=True)
    subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule", "name=ClipperLocal phone share", "dir=in",
                    "action=allow", "protocol=TCP", "localport=8766", "profile=private"], capture_output=True)
    base = getattr(sys, "_base_executable", py)  # the real python.exe behind the .venv launcher
    subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", "name=ClipperLocal engine"], capture_output=True)
    subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule", "name=ClipperLocal engine", "dir=in", "action=allow",
                    f"program={base}", "profile=private"], capture_output=True)
    say("  Firewall: phone share allowed on home Wi-Fi only")
    if Path(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tailscale", "tailscale.exe").exists():
        return say("  Tailscale (Italy box link): already installed")
    say("  Tailscale (Italy box link): downloading")
    msi = DL / "tailscale.msi"
    try:
        download("https://pkgs.tailscale.com/stable/tailscale-setup-latest-amd64.msi", msi, "Tailscale")
        p = subprocess.run(["msiexec", "/i", str(msi), "/quiet", "/norestart"], capture_output=True)
        say("  Tailscale: installed (log in from its tray icon)" if p.returncode in (0, 3010)
            else f"  Tailscale: installer returned {p.returncode}, install it from tailscale.com later")
    except StepFailed as e:
        say(f"  Tailscale: {e} (install it from tailscale.com later)")


def step_check():
    from app import winenv  # noqa: F401  (puts tools/ on PATH)
    problems = []
    for cmd in ("ffmpeg", "git"):
        if not shutil.which(cmd):
            problems.append(cmd)
    if not (ROOT / ("ClipperLocal.exe" if WINDOWS else "clipperlocal-app")).exists() and WINDOWS:
        problems.append("ClipperLocal.exe")
    if problems:
        raise StepFailed("Still missing: " + ", ".join(problems))
    say("  Everything is in place.")


STEPS = [("App window (WebView2)", step_webview2), ("Video tools", step_ffmpeg), ("Phone tools", step_adb), ("Git", step_git), ("AI engine", step_ollama),
         ("Settings", step_config), ("App code", step_repo), ("AI models", step_models), ("Captions", step_whisper),
         ("Final check", step_check)]


def main(argv: list[str]) -> int:
    say(f"ClipperLocal setup · {platform.platform()} · Python {platform.python_version()} · {ROOT}")
    if argv and argv[0] == "admin":
        step_admin()
        return 0
    chosen = [s for s in STEPS if not argv or s[1].__name__.replace("step_", "") in argv]
    for i, (title, fn) in enumerate(chosen, 1):
        say(f"[{i}/{len(chosen)}] {title}")
        try:
            fn()
        except StepFailed as e:
            say(f"PROBLEM: {e}")
            say(f"Details are in {LOG}. Run the installer again to continue where it stopped.")
            return 1
        except Exception as e:
            say(f"PROBLEM in '{title}': {e.__class__.__name__}: {e}")
            say(f"Details are in {LOG}. Run the installer again to continue where it stopped.")
            import traceback
            with open(LOG, "a", encoding="utf-8") as f:
                traceback.print_exc(file=f)
            return 1
    shutil.rmtree(DL, ignore_errors=True)
    say("DONE. Open ClipperLocal from the Desktop icon.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

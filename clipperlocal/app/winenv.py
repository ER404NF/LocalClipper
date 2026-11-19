"""Makes the engine behave on Windows. Imported first (by config.py), so it runs before anything else.

- UTF-8 everywhere (Turkish/Italian text, emoji in captions) instead of the old Windows code page
- the tools the installer put in tools/ (ffmpeg, adb, git, ollama) are found without touching the system PATH
- ffmpeg/git/adb don't flash a black console window every time they run
- Ollama gets started if it isn't running yet"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
WINDOWS = os.name == "nt"

# --- UTF-8 -----------------------------------------------------------------------
os.environ.setdefault("PYTHONUTF8", "1")           # child Python processes (checks, previews)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# --- bundled tools on PATH ----------------------------------------------------------
_TOOL_DIRS = [TOOLS / "ffmpeg" / "bin", TOOLS / "platform-tools", TOOLS / "git" / "cmd", TOOLS / "ollama", TOOLS]
if WINDOWS:
    _TOOL_DIRS.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama")
_extra = [str(d) for d in _TOOL_DIRS if d.is_dir()]
if _extra:
    os.environ["PATH"] = os.pathsep.join(_extra + [os.environ.get("PATH", "")])

# --- no console windows for child processes ------------------------------------------
if WINDOWS:
    _NO_WINDOW = 0x08000000
    _orig_init = subprocess.Popen.__init__

    def _quiet_init(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = _NO_WINDOW
        _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _quiet_init


# --- Ollama -----------------------------------------------------------------------------
def ollama_exe() -> str | None:
    own = TOOLS / "ollama" / "ollama.exe"
    if own.exists():  # the installer's own copy wins (it replaces a broken system install)
        return str(own)
    found = shutil.which("ollama")
    if found:
        return found
    for p in (own,
              Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"):
        if p.exists():
            return str(p)
    return None


def _ollama_up(url: str) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_ollama(url: str = "http://127.0.0.1:11434", parallel: int = 2, wait: float = 25) -> bool:
    """Start `ollama serve` in the background if nothing answers. Returns True when Ollama is reachable."""
    if _ollama_up(url):
        return True
    exe = ollama_exe()
    if not exe:
        return False
    env = {**os.environ, "OLLAMA_NUM_PARALLEL": str(parallel), "OLLAMA_HOST": "127.0.0.1:11434"}
    kw = {"creationflags": 0x08000000 | 0x00000200} if WINDOWS else {"start_new_session": True}  # no window, own group
    try:
        subprocess.Popen([exe, "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, **kw)
    except OSError:
        return False
    end = time.time() + wait
    while time.time() < end:
        if _ollama_up(url):
            return True
        time.sleep(0.5)
    return False

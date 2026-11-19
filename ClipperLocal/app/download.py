"""Downloads clips/VOD sections and records live streams with yt-dlp."""
import shutil
import subprocess
import sys
from pathlib import Path


def _ytdlp() -> list[str]:
    return [sys.executable, "-m", "yt_dlp"]


def fetch(url: str, kind: str, out_dir: Path, options: dict) -> Path:
    """kind: clip | vod | live | file.
    options: vod -> start/end (seconds) ; live -> minutes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "source.mp4"
    if target.exists():
        return target

    if kind == "file":  # local file path (for testing or your own recordings)
        shutil.copy(url, target)
        return target

    cmd = _ytdlp() + [
        "-f", "best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "-o", str(target),
        "--no-part", "--quiet", "--no-warnings",
    ]
    if kind == "vod" and (options.get("start") is not None or options.get("end") is not None):
        start = int(options.get("start") or 0)
        end = options.get("end")
        cmd += ["--download-sections", f"*{start}-{int(end) if end else 'inf'}"]
    if kind == "live":
        minutes = int(options.get("minutes") or 20)
        cmd += ["--downloader", "ffmpeg", "--downloader-args", f"ffmpeg:-t {minutes * 60}"]
    cmd.append(url)

    p = subprocess.run(cmd, capture_output=True, text=True)
    if not target.exists():
        # yt-dlp sometimes picks another extension
        found = sorted(out_dir.glob("source.*"))
        if found:
            found[0].rename(target)
        else:
            raise RuntimeError(f"Download failed: {(p.stderr or p.stdout)[-800:]}")
    return target


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out or 0)


def video_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)

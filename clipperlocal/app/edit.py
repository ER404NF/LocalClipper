"""Turns a moment into a finished vertical 1080x1920 video with ffmpeg:
layout (blurred background or facecam-on-top), word captions, hook text, credit."""
import subprocess
from pathlib import Path

from .download import duration as probe_duration

W, H = 1080, 1920


def _has_audio(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    return bool(out)


def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return (text or "").replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _ass_header(hook_margin: int, cap_margin: int) -> str:
    # Colours are &HAABBGGRR
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial,84,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,2,2,60,60,{cap_margin},1
Style: Hook,Arial,62,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,14,0,8,80,80,{hook_margin},1
Style: Small,Arial,34,&H40FFFFFF,&H00FFFFFF,&H80000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,70,1
Style: Num,Arial,120,&H0000E5FF,&H00000000,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,8,3,7,50,50,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _caption_lines(words: list[dict], offset: float, max_words=3) -> list[tuple[float, float, str]]:
    """Groups words into short punchy chunks (TikTok style)."""
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or w["word"].strip().endswith((".", "!", "?", ",")):
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    out = []
    for i, c in enumerate(chunks):
        start = c[0]["start"] - offset
        end = c[-1]["end"] - offset
        if i + 1 < len(chunks):  # keep text on screen until the next chunk (no flicker)
            end = max(end, min(chunks[i + 1][0]["start"] - offset, end + 0.6))
        text = " ".join(w["word"].strip() for w in c).upper()
        out.append((start, end, text))
    return out


# Where text can safely go on each app (pixels from top for the hook, from bottom for captions),
# keeping clear of each app's buttons and caption area. Reels also keeps the hook inside the 3:4 grid crop.
SAFE = {"tiktok": (230, 520), "reels": (270, 560), "shorts": (230, 470), None: (230, 420)}


def write_ass(path: Path, length: float, hook: str, words: list[dict], offset: float,
              footer: str, layout: str, captions: bool, platform: str | None = None):
    hook_margin, cap_margin = SAFE.get(platform, SAFE[None])
    if layout == "facecam":
        hook_margin = max(hook_margin, 680)
    if layout == "split":
        cap_margin = 990  # captions sit on the seam between stream and filler
    lines = [_ass_header(hook_margin, cap_margin)]
    if hook:
        lines.append(f"Dialogue: 2,{_ts(0)},{_ts(min(length, 4.5))},Hook,,0,0,0,,{_esc(hook)}")
    if captions:
        for s, e, t in _caption_lines(words, offset):
            if e > 0 and s < length:
                lines.append(f"Dialogue: 1,{_ts(s)},{_ts(min(e, length))},Cap,,0,0,0,,{_esc(t)}")
    if footer:
        lines.append(f"Dialogue: 0,{_ts(0)},{_ts(length)},Small,,0,0,0,,{_esc(footer)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _filter(layout: str, fc: dict) -> str:
    x, y, w, h = (float(fc.get(k, d)) for k, d in (("x", 0), ("y", 0), ("w", .25), ("h", .28)))
    cam = f"crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}"
    if layout == "facecam":
        return (
            "[0:v]split=2[a][b];"
            f"[a]{cam},scale={W}:640:force_original_aspect_ratio=increase,crop={W}:640,setsar=1[cam];"
            f"[b]crop='min(iw,ih*27/32)':ih,scale={W}:1280,setsar=1[game];"
            "[cam][game]vstack,ass=subs.ass[v]"
        )
    if layout == "split":  # stream on top, our own filler gameplay below (input 1)
        return (
            f"[0:v]crop='min(iw,ih*9/8)':ih,scale={W}:960,setsar=1[top];"
            f"[1:v]scale={W}:960:force_original_aspect_ratio=increase,crop={W}:960,setsar=1[bot];"
            "[top][bot]vstack,ass=subs.ass[v]"
        )
    if layout == "crop":
        return f"[0:v]crop='min(iw,ih*9/16)':ih,scale={W}:{H},setsar=1,ass=subs.ass[v]"
    if layout == "bubble":  # gameplay full screen, facecam in a corner
        return (
            "[0:v]split=2[a][b];"
            f"[a]crop='min(iw,ih*9/16)':ih,scale={W}:{H},setsar=1[bg];"
            f"[b]{cam},scale=340:340:force_original_aspect_ratio=increase,crop=340:340,"
            "pad=352:352:6:6:color=white,setsar=1[face];"
            "[bg][face]overlay=W-w-40:150,ass=subs.ass[v]"
        )
    return (
        "[0:v]split=2[a][b];"
        f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:2,"
        "eq=brightness=-0.10,setsar=1[bg];"
        f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,ass=subs.ass[v]"
    )


def filler_file() -> Path | None:
    from .config import FILLER_DIR
    files = [p for p in FILLER_DIR.glob("*") if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")]
    import random
    return random.choice(files) if files else None


ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
          "-r", "30", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
          "-movflags", "+faststart"]


def render(cfg, source: Path, start: float, end: float, out_dir: Path, hook: str,
           words: list[dict], credit: str = "", layout: str | None = None, platform: str | None = None,
           out_name: str = "final.mp4") -> Path:
    r = cfg.get("render") or {}
    layout = layout or r.get("layout", "blur")
    filler = filler_file() if layout == "split" else None
    if layout == "split" and not filler:
        layout = "blur"  # no filler footage yet: fall back
    out_dir.mkdir(parents=True, exist_ok=True)
    length = end - start
    footer = " | ".join(x for x in (credit, r.get("watermark", "")) if x)
    write_ass(out_dir / "subs.ass", length, hook, words, start, footer, layout, r.get("captions", True), platform)

    out = out_dir / out_name
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(source.resolve())]
    n_inputs = 1
    if filler:
        cmd += ["-stream_loop", "-1", "-t", f"{length:.3f}", "-i", str(filler.resolve())]
        n_inputs += 1
    audio_map = "0:a:0"
    if not _has_audio(source):
        cmd += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_map = f"{n_inputs}:a:0"
    cmd += ["-filter_complex", _filter(layout, r.get("facecam") or {}),
            "-map", "[v]", "-map", audio_map, *ENCODE, "-shortest", out_name]
    p = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True)
    if p.returncode != 0 or not out.exists():
        raise RuntimeError(f"ffmpeg failed: {p.stderr[-800:]}")
    return out


def compilation(clip_paths: list[Path], out_dir: Path, hook: str, footer: str = "") -> Path:
    """Joins rendered clips into one countdown video (#N ... #1).
    Ranked compilations add your own structure, which helps with the originality rules."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "list.txt").write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in clip_paths), encoding="utf-8")
    durs = [probe_duration(p) for p in clip_paths]
    total = sum(durs)
    lines = [_ass_header(230, 420)]
    if hook:
        lines.append(f"Dialogue: 3,{_ts(0)},{_ts(min(3.5, total))},Hook,,0,0,0,,{_esc(hook)}")
    t = 0.0
    n = len(clip_paths)
    for i, d in enumerate(durs):
        lines.append(f"Dialogue: 2,{_ts(t)},{_ts(t + d)},Num,,0,0,0,,#{n - i}")
        t += d
    if footer:
        lines.append(f"Dialogue: 0,{_ts(0)},{_ts(total)},Small,,0,0,0,,{_esc(footer)}")
    (out_dir / "subs.ass").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
           "-vf", "ass=subs.ass", *ENCODE, "final.mp4"]
    p = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr[-800:]}")
    return out_dir / "final.mp4"

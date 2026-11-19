"""Finds the best moments: loud audio + fast/excited speech -> candidate windows,
then the local LLM reads each window's transcript and scores it."""
import subprocess
from pathlib import Path
import numpy as np

from . import llm
from .transcribe import text_between

EXCITE = ("!", "oh my god", "no way", "what the", "bro", "let's go", "lets go", "yo ", "bruh",
          "wtf", "holy", "chat", "run", "help", "noo", "ahh")


def loudness_per_second(video: Path) -> np.ndarray:
    """RMS loudness in dB for every second of audio (streamed, low memory)."""
    sr = 8000
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(sr),
         "-f", "s16le", "-"],
        stdout=subprocess.PIPE,
    )
    vals = []
    while True:
        buf = p.stdout.read(sr * 2)
        if not buf:
            break
        a = np.frombuffer(buf, dtype=np.int16).astype(np.float32)
        rms = np.sqrt(np.mean(a * a) + 1e-9)
        vals.append(20 * np.log10(rms + 1e-9))
    p.wait()
    return np.array(vals or [0.0])


def _z(x: np.ndarray) -> np.ndarray:
    return (x - x.mean()) / (x.std() + 1e-6)


def _smooth(x: np.ndarray, k: int) -> np.ndarray:
    return np.convolve(x, np.ones(k) / k, mode="same") if len(x) > k else x


def _snap(segments, t, direction, limit=3.0):
    """Move a cut to the nearest sentence boundary so clips don't start mid-word."""
    best = t
    for s in segments:
        edge = s["start"] if direction < 0 else s["end"]
        if abs(edge - t) <= limit and (direction < 0 and edge <= t + 0.5 or direction > 0 and edge >= t - 0.5):
            if abs(edge - t) < abs(best - t) or best == t:
                best = edge
    return best


def lengths(cfg) -> tuple[float, float]:
    c = cfg.get("clipping") or {}
    if c.get("monetization_mode"):
        return 61.0, 90.0
    return float(c.get("min_len", 20)), float(c.get("max_len", 60))


def find(cfg, video: Path, duration: float, segments: list[dict], streamer: str,
         progress=lambda m: None) -> list[dict]:
    c = cfg.get("clipping") or {}
    k = int(c.get("clips_per_source", 5))
    min_len, max_len = lengths(cfg)

    # Short source (a Twitch clip): the whole thing is the clip.
    if duration <= max_len + 5:
        text = text_between(segments, 0, duration)
        meta = llm.score_window(cfg, streamer, text, "already clipped by viewers")
        return [{"start": 0.0, "end": duration, **meta, "score": meta.get("score", 0)}]

    progress("measuring audio")
    loud = loudness_per_second(video)
    n = len(loud)
    rate = np.zeros(n)
    excite = np.zeros(n)
    for s in segments:
        for w in s.get("words", []):
            i = int(w["start"])
            if 0 <= i < n:
                rate[i] += 1
        sec = int(s["start"])
        if 0 <= sec < n:
            t = s["text"].lower()
            excite[sec] += sum(t.count(e) for e in EXCITE)

    signal = _z(_smooth(loud, 3)) + 0.5 * _z(_smooth(rate, 5)) + 0.7 * _smooth(excite, 5)
    target = (min_len + max_len) / 2

    # Pick peaks, keeping them at least one clip-length apart.
    order = np.argsort(-signal)
    peaks = []
    for i in order:
        if all(abs(i - p) > target for p in peaks):
            peaks.append(int(i))
        if len(peaks) >= min(k * 3, 15):
            break

    sig_max = float(signal.max()) if n else 1.0
    cands = []
    for idx, p in enumerate(peaks):
        start = max(0.0, p - 0.65 * target)
        end = min(duration, start + target)
        start = max(0.0, _snap(segments, start, -1))
        end = min(duration, _snap(segments, end, +1))
        if end - start < min_len:
            end = min(duration, start + min_len)
        if end - start > max_len:
            end = start + max_len
        text = text_between(segments, start, end)
        sig = float(signal[p]) / (sig_max + 1e-6)
        progress(f"AI scoring moment {idx + 1}/{len(peaks)}")
        meta = llm.score_window(
            cfg, streamer, text,
            f"audio/excitement peak strength {sig:.2f} (1.0 = loudest moment of the stream)",
        )
        cands.append({"start": start, "end": end, **meta,
                      "score": float(meta.get("score", 0)) + 3 * max(sig, 0)})

    cands.sort(key=lambda x: -x["score"])
    return cands[:k]

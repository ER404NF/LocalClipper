"""Local speech-to-text with faster-whisper (word timestamps for captions)."""
import json
from pathlib import Path

_model = {"key": None, "m": None}


def _load(cfg):
    w = cfg.get("whisper") or {}
    key = (w.get("model", "small"), w.get("device", "auto"), w.get("compute_type", "auto"))
    if _model["key"] != key:
        from faster_whisper import WhisperModel

        device, ctype = key[1], key[2]
        if device == "auto":
            try:
                import ctranslate2

                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        if ctype == "auto":
            ctype = "float16" if device == "cuda" else "int8"
        _model["m"] = WhisperModel(key[0], device=device, compute_type=ctype)
        _model["key"] = key
    return _model["m"]


def transcribe(cfg, video: Path) -> list[dict]:
    """Returns [{start,end,text,words:[{start,end,word}]}], cached next to the video."""
    cache = video.with_name("transcript.json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    model = _load(cfg)
    lang = (cfg.get("clipping") or {}).get("language")
    segments, _info = model.transcribe(
        str(video), word_timestamps=True, vad_filter=True, language=lang
    )
    out = []
    for s in segments:
        out.append(
            {
                "start": s.start,
                "end": s.end,
                "text": s.text.strip(),
                "words": [{"start": w.start, "end": w.end, "word": w.word} for w in (s.words or [])],
            }
        )
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


def words_between(segments: list[dict], start: float, end: float) -> list[dict]:
    return [
        w for s in segments for w in s.get("words", [])
        if w["start"] >= start - 0.05 and w["end"] <= end + 0.05
    ]


def text_between(segments: list[dict], start: float, end: float) -> str:
    return " ".join(s["text"] for s in segments if s["end"] > start and s["start"] < end)

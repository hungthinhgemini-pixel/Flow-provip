"""Nhận diện giọng nói + timestamp từ file audio bằng faster-whisper (chạy offline)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable

from flowprovip.audio.scenes import Segment, Word


def transcribe(audio_path: str | Path, model_size: str = "small", language: str | None = "vi",
               on_progress: Callable[[float], None] | None = None) -> tuple[list[Segment], float]:
    """-> (segments, tổng thời lượng giây)"""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("Chưa cài faster-whisper: pip install faster-whisper") from e

    model = WhisperModel(model_size, device="auto", compute_type="auto")
    seg_iter, info = model.transcribe(str(audio_path), language=language or None,
                                      word_timestamps=True, vad_filter=True)
    total = float(info.duration or 0) or audio_duration(audio_path)
    segments = []
    for s in seg_iter:
        words = [Word(w.start, w.end, w.word) for w in (s.words or [])]
        segments.append(Segment(s.start, s.end, s.text.strip(), words))
        if on_progress and total:
            on_progress(min(1.0, s.end / total))
    return segments, total


def audio_duration(path: str | Path) -> float:
    """Thời lượng media (giây) qua ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def media_size(path: str | Path) -> tuple[int, int]:
    """(width, height) của ảnh/video qua ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    st = json.loads(out)["streams"][0]
    return int(st["width"]), int(st["height"])

"""Chia lời thoại (đã có timestamp) thành các phân cảnh, mỗi cảnh ứng với 1 ảnh/video."""

from __future__ import annotations

from dataclasses import dataclass, field

_BREAK_PUNCT = (".", "!", "?", "…", ";", ":", ",")


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Scene:
    index: int
    start: float
    end: float
    text: str
    prompt: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


def build_scenes(segments: list[Segment], min_sec: float = 3.0, max_sec: float = 8.0,
                 total_duration: float | None = None) -> list[Scene]:
    """Gộp câu ngắn, tách câu dài, rồi nối liền các cảnh để phủ kín toàn bộ voice (không hở hình)."""
    pieces: list[Segment] = []
    for seg in segments:
        if not seg.text.strip():
            continue
        if seg.duration > max_sec and len(seg.words) > 1:
            pieces.extend(_split_long(seg, max_sec))
        else:
            pieces.append(seg)

    merged: list[Segment] = []
    for p in pieces:
        if merged and (merged[-1].duration < min_sec or p.duration < min_sec * 0.5) \
                and p.end - merged[-1].start <= max_sec:
            last = merged[-1]
            merged[-1] = Segment(last.start, p.end, f"{last.text.strip()} {p.text.strip()}", last.words + p.words)
        else:
            merged.append(p)
    # cảnh cuối quá ngắn -> gộp vào cảnh trước
    if len(merged) > 1 and merged[-1].duration < min_sec * 0.5:
        a, b = merged[-2], merged.pop()
        merged[-1] = Segment(a.start, b.end, f"{a.text.strip()} {b.text.strip()}", a.words + b.words)

    scenes = [Scene(i + 1, s.start, s.end, " ".join(s.text.split())) for i, s in enumerate(merged)]
    if scenes:
        scenes[0].start = 0.0
        for a, b in zip(scenes, scenes[1:]):
            a.end = b.start  # cảnh trước kéo dài tới khi cảnh sau bắt đầu
        if total_duration and total_duration > scenes[-1].end:
            scenes[-1].end = total_duration
    return scenes


def _split_long(seg: Segment, max_sec: float) -> list[Segment]:
    out: list[Segment] = []
    cur: list[Word] = []
    for i, w in enumerate(seg.words):
        cur.append(w)
        dur = cur[-1].end - cur[0].start
        nxt = seg.words[i + 1] if i + 1 < len(seg.words) else None
        at_punct = w.text.strip().endswith(_BREAK_PUNCT)
        would_overflow = nxt is not None and nxt.end - cur[0].start > max_sec
        if nxt is None or would_overflow or (at_punct and dur >= max_sec * 0.5):
            out.append(Segment(cur[0].start, cur[-1].end, "".join(x.text for x in cur).strip(), cur))
            cur = []
    return out


def scenes_to_srt(scenes: list[Scene]) -> str:
    lines = []
    for s in scenes:
        lines += [str(s.index), f"{_ts(s.start)} --> {_ts(s.end)}", s.text, ""]
    return "\n".join(lines)


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(text: str) -> list[Segment]:
    """Đọc file SRT có sẵn (nếu không muốn chạy Whisper)."""
    segs = []
    for block in text.replace("\r", "").strip().split("\n\n"):
        lines = [x for x in block.split("\n") if x.strip()]
        for j, line in enumerate(lines):
            if "-->" in line:
                a, b = (x.strip() for x in line.split("-->"))
                segs.append(Segment(_parse_ts(a), _parse_ts(b), " ".join(lines[j + 1:])))
                break
    return segs


def _parse_ts(s: str) -> float:
    s = s.split()[0].replace(",", ".")
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)

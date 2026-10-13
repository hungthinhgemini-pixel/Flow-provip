"""Mô hình dữ liệu cho tác vụ tạo ảnh/video."""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field
from enum import Enum


class Kind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"          # text -> video
    IMAGE_VIDEO = "img2vid"  # tạo ảnh trước rồi biến ảnh thành video


class Status(str, Enum):
    PENDING = "chờ"
    RUNNING = "đang chạy"
    DONE = "xong"
    FAILED = "lỗi"
    CANCELLED = "huỷ"


@dataclass
class Task:
    index: int
    prompt: str
    kind: Kind = Kind.IMAGE
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    # Ảnh tham chiếu (giữ nhân vật/phong cách đồng nhất) hoặc ảnh đầu cho image->video
    ref_images: list[str] = field(default_factory=list)
    video_prompt: str = ""
    # Thời điểm trong voice (giây) nếu tác vụ thuộc một phân cảnh
    start: float | None = None
    end: float | None = None
    text: str = ""

    status: Status = Status.PENDING
    account: str = ""
    attempts: int = 0
    error: str = ""
    outputs: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.index:04d}"


def tasks_from_text(text: str, kind: Kind, prefix: str = "", suffix: str = "") -> list[Task]:
    """Mỗi dòng không rỗng là một prompt. Hỗ trợ CSV có cột 'prompt' (và tuỳ chọn 'video_prompt')."""
    text = text.strip()
    if not text:
        return []
    first = text.splitlines()[0].lower()
    rows: list[dict]
    if "prompt" in first and ("," in first or "\t" in first):
        dialect = "excel-tab" if "\t" in first else "excel"
        rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
        rows = [{k.strip().lower(): (v or "").strip() for k, v in r.items() if k} for r in rows]
    else:
        rows = [{"prompt": line.strip()} for line in text.splitlines() if line.strip()]
    tasks = []
    for i, r in enumerate(rows, 1):
        if not r.get("prompt"):
            continue
        tasks.append(Task(index=i, prompt=build_prompt(r["prompt"], prefix, suffix), kind=kind,
                          video_prompt=r.get("video_prompt", "")))
    return tasks


def build_prompt(core: str, prefix: str = "", suffix: str = "") -> str:
    parts = [p.strip().strip(",") for p in (prefix, core, suffix) if p and p.strip()]
    return ", ".join(parts)

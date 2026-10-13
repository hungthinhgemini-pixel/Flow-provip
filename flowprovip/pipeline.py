"""Quy trình Voice -> phân cảnh -> tác vụ Flow -> draft CapCut."""

from __future__ import annotations

from pathlib import Path

from flowprovip.audio.scenes import Scene, build_scenes, parse_srt, scenes_to_srt
from flowprovip.audio.transcribe import audio_duration, media_size, transcribe
from flowprovip.capcut.draft import Clip, DraftBuilder, default_drafts_dir
from flowprovip.config import Settings
from flowprovip.jobs import Kind, Task, build_prompt


def scenes_from_audio(audio: str | Path, settings: Settings, srt: str | Path | None = None,
                      on_progress=None) -> list[Scene]:
    if srt:
        segments = parse_srt(Path(srt).read_text(encoding="utf-8-sig"))
        total = audio_duration(audio)
    else:
        segments, total = transcribe(audio, settings.whisper_model, settings.whisper_language, on_progress)
    return build_scenes(segments, settings.scene_min_sec, settings.scene_max_sec, total)


def tasks_from_scenes(scenes: list[Scene], kind: Kind, settings: Settings) -> list[Task]:
    return [
        Task(index=s.index, kind=kind, start=s.start, end=s.end, text=s.text,
             prompt=build_prompt(s.prompt or s.text, settings.style_prefix, settings.style_suffix))
        for s in scenes
    ]


def export_capcut(tasks: list[Task], audio: str | Path, settings: Settings, name: str,
                  prefer_video: bool = True) -> Path:
    """Tạo draft CapCut. Cảnh nào chưa có media sẽ dùng lại media của cảnh gần nhất trước nó."""
    tasks = sorted((t for t in tasks if t.start is not None), key=lambda t: t.start)
    clips: list[Clip] = []
    last_media = None
    for t in tasks:
        media = _pick_media(t, prefer_video) or last_media
        last_media = media
        if not media:
            continue
        w, h = _safe_size(media, settings)
        clip = Clip(path=media, start=t.start, end=t.end, text=t.text, width=w, height=h)
        if not clip.is_image:
            clip.media_duration = audio_duration(media)
        clips.append(clip)
    if not clips:
        raise ValueError("Chưa có ảnh/video nào để xuất")

    builder = DraftBuilder(settings.canvas_width, settings.canvas_height,
                           template_dir=settings.capcut_template_draft or None)
    builder.add_visual_track(clips, ken_burns=settings.ken_burns)
    builder.add_audio(audio, audio_duration(audio))
    if settings.add_subtitles:
        builder.add_subtitles(clips)
    root = Path(settings.capcut_drafts_dir) if settings.capcut_drafts_dir else default_drafts_dir()
    root.mkdir(parents=True, exist_ok=True)
    folder = builder.save(root, name)

    # Kèm file SRT cạnh output để tiện dùng ở chỗ khác
    srt = scenes_to_srt([Scene(i + 1, c.start, c.end, c.text) for i, c in enumerate(clips)])
    (folder / "subtitles.srt").write_text(srt, encoding="utf-8")
    return folder


def _pick_media(t: Task, prefer_video: bool) -> str | None:
    vids = [p for p in t.outputs if p.endswith(".mp4") and Path(p).exists()]
    imgs = [p for p in t.outputs if not p.endswith(".mp4") and Path(p).exists()]
    order = (vids, imgs) if prefer_video else (imgs, vids)
    for group in order:
        if group:
            return group[0]
    return None


def _safe_size(path: str, settings: Settings) -> tuple[int, int]:
    try:
        return media_size(path)
    except Exception:  # noqa: BLE001
        return settings.canvas_width, settings.canvas_height

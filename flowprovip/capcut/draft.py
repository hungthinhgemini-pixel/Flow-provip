"""Xuất project draft cho CapCut desktop: ảnh/video xếp theo timeline voice + phụ đề.

Cấu trúc draft_content.json dựa trên định dạng CapCut desktop bản không mã hoá. Nếu bản CapCut của bạn
không mở được draft tạo từ khung mặc định, hãy tạo 1 project TRỐNG trong CapCut, đóng CapCut rồi chỉ
đường dẫn thư mục draft đó làm "template" — tool sẽ giữ nguyên phần cấu hình của bản CapCut đó và chỉ
thay timeline.
"""

from __future__ import annotations

import copy
import json
import os
import platform
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

US = 1_000_000  # CapCut dùng micro giây
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def default_drafts_dir() -> Path:
    home = Path.home()
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return base / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    if platform.system() == "Darwin":
        return home / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    return home / "CapCut" / "com.lveditor.draft"


@dataclass
class Clip:
    path: str
    start: float      # giây trên timeline
    end: float
    text: str = ""
    width: int = 1920
    height: int = 1080
    media_duration: float | None = None  # với video: độ dài file gốc

    @property
    def is_image(self) -> bool:
        return Path(self.path).suffix.lower() in IMAGE_EXT


def _id() -> str:
    return str(uuid.uuid4()).upper()


def _us(sec: float) -> int:
    return int(round(sec * US))


class DraftBuilder:
    def __init__(self, width: int = 1920, height: int = 1080, fps: float = 30.0,
                 template_dir: str | Path | None = None):
        self.width, self.height, self.fps = width, height, fps
        self.template = _load_template(template_dir) if template_dir else None
        self.materials: dict[str, list] = {k: [] for k in (
            "videos", "audios", "texts", "speeds", "canvases", "sound_channel_mappings",
            "material_animations", "beats", "vocal_separations", "placeholder_infos",
        )}
        self.tracks: list[dict] = []
        self.duration = 0

    # ------------------------------------------------------------------ tracks
    def add_visual_track(self, clips: list[Clip], ken_burns: bool = True, mute: bool = True) -> None:
        segs = []
        for i, c in enumerate(clips):
            dur = _us(c.end - c.start)
            if dur <= 0:
                continue
            mat_id = _id()
            if c.is_image:
                src_dur, speed, mat_dur = dur, 1.0, 10_800 * US
            else:
                mat_dur = _us(c.media_duration or (c.end - c.start))
                if mat_dur >= dur:
                    src_dur, speed = dur, 1.0
                else:  # video ngắn hơn cảnh -> làm chậm cho vừa
                    src_dur, speed = mat_dur, mat_dur / dur
            self.materials["videos"].append(self._video_material(mat_id, c, mat_dur))
            refs = [self._speed(speed), self._canvas(), self._sound_mapping()]
            seg = self._segment(mat_id, _us(c.start), dur, src_dur, refs, speed=speed,
                                volume=0.0 if mute else 1.0)
            if ken_burns:
                zoom_in = i % 2 == 0
                seg["common_keyframes"] = _zoom_keyframes(dur, 1.0 if zoom_in else 1.12, 1.12 if zoom_in else 1.0)
            segs.append(seg)
            self.duration = max(self.duration, _us(c.end))
        self.tracks.append(_track("video", segs))

    def add_audio(self, path: str | Path, duration: float, start: float = 0.0) -> None:
        mat_id = _id()
        self.materials["audios"].append({
            "id": mat_id, "type": "extract_music", "name": Path(path).name, "path": str(Path(path).resolve()),
            "duration": _us(duration), "category_name": "local", "check_flag": 1, "app_id": 0,
            "local_material_id": "", "music_id": _id(), "source_platform": 0, "wave_points": [],
            "copyright_limit_type": "none", "effect_id": "", "formula_id": "", "text_id": "", "tone_type": "",
            "video_id": "", "intensifies_path": "",
        })
        refs = [self._speed(1.0), self._sound_mapping(), self._beats()]
        seg = self._segment(mat_id, _us(start), _us(duration), _us(duration), refs, volume=1.0)
        seg.pop("clip", None)
        seg.pop("uniform_scale", None)
        self.tracks.append(_track("audio", [seg]))
        self.duration = max(self.duration, _us(start + duration))

    def add_subtitles(self, clips: list[Clip], font_size: float = 7.0, y: float = -0.78) -> None:
        segs = []
        for c in clips:
            if not c.text.strip():
                continue
            mat_id = _id()
            self.materials["texts"].append(_text_material(mat_id, c.text.strip(), font_size))
            anim_id = _id()
            self.materials["material_animations"].append(
                {"id": anim_id, "type": "sticker_animation", "animations": [], "multi_language_current": "none"})
            dur = _us(c.end - c.start)
            seg = self._segment(mat_id, _us(c.start), dur, dur, [anim_id])
            seg["clip"]["transform"]["y"] = y
            seg["source_timerange"] = None
            segs.append(seg)
        if segs:
            self.tracks.append(_track("text", segs))

    # ------------------------------------------------------------------ xuất
    def content(self, name: str) -> dict:
        base = copy.deepcopy(self.template) if self.template else _skeleton()
        mats = base.setdefault("materials", {})
        for k in list(mats):
            if isinstance(mats[k], list):
                mats[k] = []
        for k, v in self.materials.items():
            mats[k] = v
        base.update({
            "id": _id(),
            "name": name,
            "duration": self.duration,
            "fps": self.fps,
            "tracks": self.tracks,
            "canvas_config": {"height": self.height, "ratio": "original", "width": self.width},
        })
        return base

    def save(self, drafts_root: str | Path, name: str) -> Path:
        folder = Path(drafts_root) / _safe_name(name)
        if folder.exists():
            folder = folder.with_name(folder.name + time.strftime("_%H%M%S"))
        folder.mkdir(parents=True)
        content = self.content(folder.name)
        (folder / "draft_content.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        # Một số bản CapCut đọc draft_info.json thay cho draft_content.json
        shutil.copy(folder / "draft_content.json", folder / "draft_info.json")
        (folder / "draft_meta_info.json").write_text(
            json.dumps(_meta(folder, self.duration), ensure_ascii=False), encoding="utf-8")
        return folder

    # ------------------------------------------------------------------ helpers
    def _video_material(self, mat_id: str, c: Clip, mat_dur: int) -> dict:
        return {
            "id": mat_id, "type": "photo" if c.is_image else "video",
            "path": str(Path(c.path).resolve()), "material_name": Path(c.path).name,
            "duration": mat_dur, "width": c.width, "height": c.height,
            "category_name": "local", "check_flag": 63487, "has_audio": not c.is_image,
            "crop": {"lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0,
                     "upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0},
            "crop_ratio": "free", "crop_scale": 1.0, "audio_fade": None, "extra_type_option": 0,
            "local_material_id": "", "material_id": "", "media_path": "", "source_platform": 0,
            "stable": {"matrix_path": "", "stable_level": 0, "time_range": {"duration": 0, "start": 0}},
            "matting": {"flag": 0, "has_use_quick_brush": False, "has_use_quick_eraser": False,
                        "interactiveTime": [], "path": "", "strokes": []},
            "video_algorithm": {"algorithms": [], "path": ""},
        }

    def _speed(self, speed: float) -> str:
        sid = _id()
        self.materials["speeds"].append(
            {"id": sid, "type": "speed", "mode": 0, "speed": speed, "curve_speed": None})
        return sid

    def _canvas(self) -> str:
        cid = _id()
        self.materials["canvases"].append({
            "id": cid, "type": "canvas_color", "color": "", "blur": 0.0, "image": "", "album_image": "",
            "image_id": "", "image_name": "", "source_platform": 0, "team_id": "",
        })
        return cid

    def _sound_mapping(self) -> str:
        mid = _id()
        self.materials["sound_channel_mappings"].append(
            {"id": mid, "type": "", "audio_channel_mapping": 0, "is_config_open": False})
        return mid

    def _beats(self) -> str:
        bid = _id()
        self.materials["beats"].append({
            "id": bid, "type": "beats", "enable_ai_beats": False, "gear": 404, "gear_count": 0, "mode": 404,
            "user_beats": [], "user_delete_ai_beats": None,
            "ai_beats": {"beat_speed_infos": [], "beats_path": "", "beats_url": "", "melody_path": "",
                         "melody_percents": [0.0], "melody_url": ""},
        })
        return bid

    def _segment(self, mat_id: str, start: int, dur: int, src_dur: int, refs: list[str],
                 speed: float = 1.0, volume: float = 1.0) -> dict:
        return {
            "id": _id(), "material_id": mat_id, "extra_material_refs": refs,
            "target_timerange": {"start": start, "duration": dur},
            "source_timerange": {"start": 0, "duration": src_dur},
            "speed": speed, "volume": volume, "last_nonzero_volume": 1.0, "visible": True,
            "clip": {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0,
                     "scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}},
            "uniform_scale": {"on": True, "value": 1.0},
            "common_keyframes": [], "keyframe_refs": [], "render_index": 0, "track_render_index": 0,
            "enable_adjust": True, "enable_color_curves": True, "enable_color_wheels": True,
            "enable_lut": True, "enable_smart_color_adjust": False, "is_placeholder": False,
            "is_tone_modify": False, "reverse": False, "intensifies_audio": False, "cartoon": False,
            "group_id": "", "template_id": "", "template_scene": "default", "track_attribute": 0,
            "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000}, "responsive_layout": {
                "enable": False, "horizontal_pos_layout": 0, "size_layout": 0, "target_follow": "",
                "vertical_pos_layout": 0},
            "caption_info": None, "desc": "", "digital_human_template_group_id": "",
            "state": 0, "lyric_keyframes": None,
        }


def _track(kind: str, segments: list[dict]) -> dict:
    return {"id": _id(), "type": kind, "attribute": 0, "flag": 0, "is_default_name": True, "name": "",
            "segments": segments}


def _zoom_keyframes(dur: int, a: float, b: float) -> list[dict]:
    def kf(prop: str) -> dict:
        return {"id": _id(), "material_id": "", "property_type": prop, "keyframe_list": [
            {"id": _id(), "curveType": "Line", "graphID": "", "time_offset": t, "values": [v],
             "left_control": {"x": 0.0, "y": 0.0}, "right_control": {"x": 0.0, "y": 0.0}}
            for t, v in ((0, a), (dur, b))]}
    return [kf("KFTypeScaleX"), kf("KFTypeScaleY")]


def _text_material(mat_id: str, text: str, size: float) -> dict:
    n = len(text.encode("utf-16-le")) // 2
    content = {"text": text, "styles": [{
        "range": [0, n], "size": size, "bold": False, "italic": False, "underline": False,
        "fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [1.0, 1.0, 1.0]}}},
        "strokes": [{"content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [0.0, 0.0, 0.0]}},
                     "width": 0.08}],
    }]}
    return {
        "id": mat_id, "type": "text", "content": json.dumps(content, ensure_ascii=False),
        "alignment": 1, "typesetting": 0, "font_size": size, "text_color": "#FFFFFF",
        "border_color": "#000000", "border_width": 0.08, "check_flag": 15, "line_spacing": 0.02,
        "letter_spacing": 0.0, "line_max_width": 0.82, "global_alpha": 1.0, "fixed_width": -1.0,
        "fixed_height": -1.0, "force_apply_line_max_width": False, "words": {"end_time": [], "start_time": [], "text": []},
        "add_type": 0, "base_content": "", "font_path": "", "font_id": "", "font_name": "", "fonts": [],
        "has_shadow": False, "background_alpha": 1.0, "background_color": "", "background_style": 0,
        "initial_scale": 1.0, "is_rich_text": False, "name": "", "underline": False,
    }


def _skeleton() -> dict:
    now = int(time.time())
    return {
        "canvas_config": {"height": 1080, "ratio": "original", "width": 1920},
        "color_space": 0,
        "config": {"adjust_max_index": 1, "attachment_info": [], "combination_max_index": 1,
                   "export_range": None, "extract_audio_last_index": 1, "lyrics_recognition_id": "",
                   "lyrics_sync": True, "lyrics_taskinfo": [], "maintrack_adsorb": True,
                   "material_save_mode": 0, "original_sound_last_index": 1, "record_audio_last_index": 1,
                   "sticker_max_index": 1, "subtitle_recognition_id": "", "subtitle_sync": True,
                   "subtitle_taskinfo": [], "system_font_list": [], "video_mute": False,
                   "zoom_info_params": None},
        "cover": None, "create_time": now, "update_time": now, "duration": 0, "extra_info": None,
        "fps": 30.0, "free_render_index_mode_on": False, "group_container": None, "id": _id(),
        "keyframe_graph_list": [],
        "keyframes": {k: [] for k in ("adjusts", "audios", "effects", "filters", "handwrites",
                                       "stickers", "texts", "videos")},
        "last_modified_platform": _platform(), "platform": _platform(),
        "materials": {k: [] for k in (
            "ai_translates", "audio_balances", "audio_effects", "audio_fades", "audio_track_indexes",
            "audios", "beats", "canvases", "chromas", "color_curves", "digital_humans", "drafts",
            "effects", "flowers", "green_screens", "handwrites", "hsl", "images", "log_color_wheels",
            "loudnesses", "manual_deformations", "masks", "material_animations", "material_colors",
            "multi_language_refs", "placeholder_infos", "placeholders", "plugin_effects",
            "primary_color_wheels", "realtime_denoises", "shapes", "smart_crops", "smart_relights",
            "sound_channel_mappings", "speeds", "stickers", "tail_leaders", "text_templates", "texts",
            "time_marks", "transitions", "video_effects", "video_trackings", "videos",
            "vocal_beautifys", "vocal_separations")},
        "mutable_config": None, "name": "", "new_version": "110.0.0", "relationships": [],
        "render_index_track_mode_on": False, "retouch_cover": None, "source": "default",
        "static_cover_image_path": "", "time_marks": None, "tracks": [], "version": 360000,
    }


def _platform() -> dict:
    return {"app_id": 359289, "app_source": "cc", "app_version": "5.9.0", "device_id": "",
            "hard_disk_id": "", "mac_address": "", "os": platform.system().lower(),
            "os_version": platform.release()}


def _meta(folder: Path, duration: int) -> dict:
    now = int(time.time() * US)
    return {
        "draft_id": _id(), "draft_name": folder.name, "draft_fold_path": str(folder).replace("\\", "/"),
        "draft_root_path": str(folder.parent).replace("\\", "/"), "draft_cover": "",
        "draft_materials": [{"type": t, "value": []} for t in (0, 1, 2, 3, 6, 7, 8)],
        "draft_removable_storage_device": "", "draft_timeline_materials_size_": 0,
        "tm_draft_create": now, "tm_draft_modified": now, "tm_duration": duration,
        "draft_is_invisible": False, "draft_need_rename_folder": False, "draft_type": "",
        "draft_new_version": "", "draft_segment_extra_info": [], "tm_draft_cloud_completed": "",
        "tm_draft_cloud_modified": 0, "tm_draft_removed": 0,
    }


def _load_template(template_dir: str | Path) -> dict:
    d = Path(template_dir)
    for fname in ("draft_content.json", "draft_info.json"):
        p = d / fname
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise ValueError(
                    f"{p} bị CapCut mã hoá, không dùng làm template được. Hãy dùng bản CapCut "
                    f"không mã hoá draft hoặc bỏ trống template.") from e
    raise FileNotFoundError(f"Không thấy draft_content.json trong {d}")


def _safe_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if ch in bad else ch for ch in name).strip() or "FlowProVip"

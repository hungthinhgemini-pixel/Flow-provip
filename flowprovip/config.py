"""Cấu hình ứng dụng, lưu dạng JSON trong thư mục data/."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def app_home() -> Path:
    """Thư mục gốc chứa data (profile trình duyệt, cấu hình). Có thể đổi bằng biến FLOWPROVIP_HOME."""
    home = Path(os.environ.get("FLOWPROVIP_HOME", Path.cwd() / "data"))
    home.mkdir(parents=True, exist_ok=True)
    return home


@dataclass
class Settings:
    # Thư mục lưu ảnh/video tải về
    output_dir: str = str(Path.cwd() / "output")
    # Số tác vụ chạy song song tối đa trên MỖI tài khoản
    threads_per_account: int = 2
    # Số lần thử lại khi lỗi (không tính lỗi hết quota - sẽ chuyển tài khoản)
    max_retries: int = 2
    # Chạy trình duyệt ẩn khi tạo hàng loạt (đăng nhập luôn hiện cửa sổ)
    headless: bool = False
    # Dùng Google Chrome thật thay vì Chromium (Google ít chặn đăng nhập hơn)
    browser_channel: str = "chrome"

    # --- Tham số tạo ảnh ---
    image_model: str = "GEM_PIX"
    image_aspect: str = "IMAGE_ASPECT_RATIO_LANDSCAPE"
    images_per_prompt: int = 1

    # --- Tham số tạo video ---
    video_model_t2v: str = "veo_3_1_t2v_fast"
    video_model_i2v: str = "veo_3_1_i2v_s_fast"
    video_aspect: str = "VIDEO_ASPECT_RATIO_LANDSCAPE"
    video_poll_interval: float = 8.0
    video_timeout: float = 600.0

    # --- Prompt ---
    style_prefix: str = ""
    style_suffix: str = "cinematic, highly detailed, consistent style"

    # --- Voice / phân cảnh ---
    whisper_model: str = "small"
    whisper_language: str = "vi"
    scene_min_sec: float = 3.0
    scene_max_sec: float = 8.0

    # --- CapCut ---
    capcut_drafts_dir: str = ""
    capcut_template_draft: str = ""
    canvas_width: int = 1920
    canvas_height: int = 1080
    add_subtitles: bool = True
    ken_burns: bool = True

    # Ghi đè endpoint / payload của Flow (xem flow/endpoints.py)
    endpoint_overrides: dict = field(default_factory=dict)

    @classmethod
    def path(cls) -> Path:
        return app_home() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        p = cls.path()
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

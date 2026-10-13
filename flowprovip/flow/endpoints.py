"""Endpoint và payload nội bộ của Google Flow (labs.google/fx/tools/flow).

LƯU Ý: Đây là API nội bộ, Google không công bố và có thể đổi bất kỳ lúc nào. Mọi thứ phụ thuộc vào
API được gom vào file này để khi Flow đổi, chỉ cần sửa ở đây (hoặc ghi đè qua
Settings.endpoint_overrides mà không cần sửa code).

Cách tự kiểm tra lại khi bị lỗi: mở Flow trên Chrome -> F12 -> tab Network -> tạo thử 1 ảnh/video ->
xem request tới aisandbox-pa.googleapis.com, so URL và body với các hàm bên dưới.
"""

from __future__ import annotations

import random
import time
import uuid

FLOW_URL = "https://labs.google/fx/tools/flow"
AUTH_SESSION_URL = "https://labs.google/fx/api/auth/session"
CREATE_PROJECT_URL = "https://labs.google/fx/api/trpc/project.createProject"

API_BASE = "https://aisandbox-pa.googleapis.com/v1"
GENERATE_IMAGES_URL = API_BASE + "/projects/{project_id}/flowMedia:batchGenerateImages"
UPLOAD_IMAGE_URL = API_BASE + ":uploadUserImage"
VIDEO_T2V_URL = API_BASE + "/video:batchAsyncGenerateVideoText"
VIDEO_I2V_URL = API_BASE + "/video:batchAsyncGenerateVideoStartImage"
VIDEO_STATUS_URL = API_BASE + "/video:batchCheckAsyncVideoGenerationStatus"

RECAPTCHA_ACTION = "FLOW_GENERATION"
# Để trống = tự dò site key từ trang Flow
RECAPTCHA_SITE_KEY = ""
TOOL_NAME = "PINHOLE"
PAYGATE_TIER = "PAYGATE_TIER_ONE"

STATUS_SUCCESS = "MEDIA_GENERATION_STATUS_SUCCESSFUL"
STATUS_FAILED = "MEDIA_GENERATION_STATUS_FAILED"


def apply_overrides(overrides: dict) -> None:
    """Ghi đè hằng số trong module này, vd {"VIDEO_T2V_URL": "...", "PAYGATE_TIER": "PAYGATE_TIER_TWO"}."""
    g = globals()
    for k, v in (overrides or {}).items():
        if k.isupper() and k in g:
            g[k] = v


def new_session_id() -> str:
    return f";{int(time.time() * 1000)}"


def client_context(project_id: str, session_id: str, recaptcha_token: str | None) -> dict:
    ctx = {
        "projectId": project_id,
        "tool": TOOL_NAME,
        "userPaygateTier": PAYGATE_TIER,
        "sessionId": session_id,
    }
    if recaptcha_token:
        ctx["recaptchaToken"] = recaptcha_token
    return ctx


def create_project_body(title: str) -> dict:
    return {"json": {"projectTitle": title, "toolName": TOOL_NAME}}


def generate_images_body(ctx: dict, prompt: str, model: str, aspect: str, count: int,
                         ref_media_ids: list[str] | None = None) -> dict:
    image_inputs = [
        {"name": mid, "imageInputType": "IMAGE_INPUT_TYPE_REFERENCE"} for mid in (ref_media_ids or [])
    ]
    return {
        "clientContext": ctx,
        "requests": [
            {
                "clientContext": ctx,
                "seed": random.randint(1, 999_999),
                "imageModelName": model,
                "imageAspectRatio": aspect,
                "prompt": prompt,
                "imageInputs": image_inputs,
            }
            for _ in range(max(1, count))
        ],
    }


def upload_image_body(b64: str, mime: str, aspect: str, session_id: str) -> dict:
    return {
        "imageInput": {
            "rawImageBytes": b64,
            "mimeType": mime,
            "isUserUploaded": True,
            "aspectRatio": aspect,
        },
        "clientContext": {"sessionId": session_id, "tool": "ASSET_MANAGER"},
    }


def video_t2v_body(ctx: dict, prompt: str, model: str, aspect: str) -> dict:
    return {
        "clientContext": ctx,
        "requests": [
            {
                "aspectRatio": aspect,
                "seed": random.randint(1, 99_999),
                "textInput": {"prompt": prompt},
                "videoModelKey": model,
                "metadata": {"sceneId": str(uuid.uuid4())},
            }
        ],
    }


def video_i2v_body(ctx: dict, prompt: str, model: str, aspect: str, start_media_id: str) -> dict:
    body = video_t2v_body(ctx, prompt, model, aspect)
    body["requests"][0]["startImage"] = {"mediaId": start_media_id}
    return body


def video_status_body(operations: list[dict]) -> dict:
    return {"operations": operations}


# ---------- Đọc response ----------

def parse_session(data: dict) -> tuple[str, str, int | None]:
    """-> (access_token, email, expires_epoch|None)"""
    token = data.get("access_token") or data.get("accessToken") or ""
    email = (data.get("user") or {}).get("email", "")
    return token, email, None


def parse_project_id(data: dict) -> str:
    try:
        return data["result"]["data"]["json"]["result"]["projectId"]
    except (KeyError, TypeError):
        return data.get("projectId", "")


def parse_images(data: dict) -> list[dict]:
    """-> list {"b64": str|None, "url": str|None, "media_id": str|None}"""
    out = []
    for m in data.get("media", []):
        gen = (m.get("image") or {}).get("generatedImage") or {}
        out.append({
            "b64": gen.get("encodedImage"),
            "url": gen.get("fifeUrl"),
            "media_id": gen.get("mediaGenerationId") or m.get("name"),
        })
    return out


def parse_upload(data: dict) -> str:
    mg = data.get("mediaGenerationId")
    if isinstance(mg, dict):
        return mg.get("mediaGenerationId", "")
    return mg or ""


def parse_video_ops(data: dict) -> list[dict]:
    return data.get("operations", [])


def video_op_result(op: dict) -> tuple[str, str | None]:
    """-> (status, video_url|None)"""
    status = op.get("status", "")
    video = ((op.get("operation") or {}).get("metadata") or {}).get("video") or {}
    return status, video.get("fifeUrl")


def is_quota_error(status: int, text: str) -> bool:
    t = text.lower()
    return status == 429 or "resource_exhausted" in t or "quota" in t or ("insufficient" in t and "credit" in t)


def is_auth_error(status: int, text: str) -> bool:
    return status in (401, 403) and "recaptcha" not in text.lower()

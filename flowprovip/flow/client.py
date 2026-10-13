"""Phiên làm việc với Google Flow cho MỘT tài khoản, dựa trên profile trình duyệt (Playwright).

- Cookie đăng nhập nằm trong profile -> lấy access_token qua labs.google/fx/api/auth/session.
- Gọi API bằng context.request (dùng chung cookie/proxy của profile).
- reCAPTCHA Enterprise được chạy ngay trong trang Flow đang mở.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import time
from pathlib import Path

from flowprovip.accounts import Account
from flowprovip.config import Settings
from flowprovip.flow import endpoints as ep

log = logging.getLogger(__name__)


class FlowError(Exception):
    pass


class QuotaError(FlowError):
    """Tài khoản hết lượt/credit -> bộ điều phối sẽ chuyển sang tài khoản khác."""


class AuthError(FlowError):
    """Chưa đăng nhập / phiên hết hạn."""


_RECAPTCHA_JS = """
async ([action, forcedKey]) => {
  const g = window.grecaptcha && window.grecaptcha.enterprise;
  if (!g) return null;
  let key = forcedKey || null;
  if (!key) {
    for (const s of document.querySelectorAll('script[src*="recaptcha"]')) {
      const m = s.src.match(/[?&]render=([^&]+)/);
      if (m && m[1] !== 'explicit') { key = m[1]; break; }
    }
  }
  if (!key && window.___grecaptcha_cfg) {
    const seen = new Set();
    const walk = (o, d) => {
      if (!o || typeof o !== 'object' || d > 6 || seen.has(o)) return null;
      seen.add(o);
      for (const k of Object.keys(o)) {
        try {
          if (k === 'sitekey' && typeof o[k] === 'string') return o[k];
          const r = walk(o[k], d + 1); if (r) return r;
        } catch (e) {}
      }
      return null;
    };
    key = walk(window.___grecaptcha_cfg.clients, 0);
  }
  if (!key) return null;
  await new Promise(r => g.ready(r));
  return await g.execute(key, {action});
}
"""


class FlowSession:
    def __init__(self, account: Account, settings: Settings, playwright):
        self.account = account
        self.settings = settings
        self.pw = playwright
        self.context = None
        self.page = None
        self._token = ""
        self._token_time = 0.0
        self._project_id = ""
        self._session_id = ep.new_session_id()
        self._lock = asyncio.Lock()
        # Flow chỉ cho chạy một số job song song trên mỗi tài khoản
        self.semaphore = asyncio.Semaphore(max(1, settings.threads_per_account))

    # ------------------------------------------------------------------ vòng đời
    async def start(self, headless: bool | None = None) -> None:
        headless = self.settings.headless if headless is None else headless
        kwargs = dict(
            user_data_dir=str(self.account.profile_dir),
            headless=headless,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            chromium_sandbox=True,
        )
        if self.account.proxy:
            kwargs["proxy"] = _parse_proxy(self.account.proxy)
        try:
            self.context = await self.pw.chromium.launch_persistent_context(
                channel=self.settings.browser_channel or None, **kwargs)
        except Exception as e:  # không có Chrome thật -> dùng Chromium của Playwright
            log.warning("Không mở được channel %s (%s), dùng Chromium", self.settings.browser_channel, e)
            self.context = await self.pw.chromium.launch_persistent_context(**kwargs)
        if self.account.cookies:
            await self.context.add_cookies(self.account.cookies)
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

    async def open_flow(self) -> None:
        await self.page.goto(ep.FLOW_URL, wait_until="domcontentloaded", timeout=60_000)

    async def close(self) -> None:
        if self.context:
            try:
                await self.context.close()
            finally:
                self.context = None
                self.page = None

    # ------------------------------------------------------------------ xác thực
    async def check_login(self) -> dict:
        """Trả về {"ok": bool, "email": str}. Không raise."""
        try:
            await self._refresh_token(force=True)
            return {"ok": True, "email": self.account.email}
        except Exception as e:  # noqa: BLE001 - lỗi mạng/proxy cũng coi là chưa sẵn sàng
            return {"ok": False, "email": "", "error": str(e).splitlines()[0] if str(e) else type(e).__name__}

    async def _refresh_token(self, force: bool = False) -> str:
        if self._token and not force and time.time() - self._token_time < 40 * 60:
            return self._token
        resp = await self.context.request.get(ep.AUTH_SESSION_URL)
        if resp.status != 200:
            raise AuthError(f"Không lấy được phiên đăng nhập (HTTP {resp.status})")
        token, email, _ = ep.parse_session(await resp.json())
        if not token:
            raise AuthError("Tài khoản chưa đăng nhập Flow")
        self._token, self._token_time = token, time.time()
        if email:
            self.account.email = email
        return token

    async def _recaptcha(self) -> str | None:
        if self.page is None:
            return None
        if "labs.google" not in (self.page.url or ""):
            await self.open_flow()
        try:
            return await self.page.evaluate(_RECAPTCHA_JS, [ep.RECAPTCHA_ACTION, ep.RECAPTCHA_SITE_KEY])
        except Exception as e:
            log.warning("[%s] reCAPTCHA lỗi: %s", self.account.name, e)
            return None

    async def _ensure_project(self) -> str:
        async with self._lock:
            if self._project_id:
                return self._project_id
            resp = await self.context.request.post(
                ep.CREATE_PROJECT_URL,
                data=json.dumps(ep.create_project_body(f"FlowProVip {time.strftime('%Y-%m-%d %H:%M')}")),
                headers={"content-type": "application/json"},
            )
            await _raise_for(resp)
            self._project_id = ep.parse_project_id(await resp.json())
            if not self._project_id:
                raise FlowError("Không tạo được project Flow")
            return self._project_id

    async def _ctx(self, need_recaptcha: bool = True) -> dict:
        project_id = await self._ensure_project()
        token = await self._recaptcha() if need_recaptcha else None
        return ep.client_context(project_id, self._session_id, token)

    async def _post(self, url: str, body: dict) -> dict:
        token = await self._refresh_token()
        resp = await self.context.request.post(
            url,
            data=json.dumps(body),
            headers={
                "authorization": f"Bearer {token}",
                "content-type": "text/plain;charset=UTF-8",
                "origin": "https://labs.google",
                "referer": "https://labs.google/",
            },
            timeout=120_000,
        )
        if resp.status == 401:  # token hết hạn -> lấy lại một lần
            token = await self._refresh_token(force=True)
            resp = await self.context.request.post(
                url, data=json.dumps(body),
                headers={"authorization": f"Bearer {token}", "content-type": "text/plain;charset=UTF-8"},
                timeout=120_000,
            )
        await _raise_for(resp)
        data = await resp.json()
        if isinstance(data, dict) and "remainingCredits" in data:
            self.account.credits = data["remainingCredits"]
        return data

    # ------------------------------------------------------------------ media
    async def download(self, url: str) -> bytes:
        resp = await self.context.request.get(url, timeout=300_000)
        await _raise_for(resp)
        return await resp.body()

    async def upload_image(self, path: str | Path) -> str:
        path = Path(path)
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        b64 = base64.b64encode(path.read_bytes()).decode()
        aspect = self.settings.image_aspect
        data = await self._post(ep.UPLOAD_IMAGE_URL, ep.upload_image_body(b64, mime, aspect, self._session_id))
        media_id = ep.parse_upload(data)
        if not media_id:
            raise FlowError("Upload ảnh không trả về mediaId")
        return media_id

    async def generate_images(self, prompt: str, count: int = 1, ref_images: list[str] | None = None) -> list[bytes]:
        refs = [await self.upload_image(p) for p in (ref_images or [])]
        ctx = await self._ctx()
        body = ep.generate_images_body(ctx, prompt, self.settings.image_model, self.settings.image_aspect,
                                       count, refs)
        data = await self._post(ep.GENERATE_IMAGES_URL.format(project_id=ctx["projectId"]), body)
        results = []
        for img in ep.parse_images(data):
            if img["b64"]:
                results.append(base64.b64decode(img["b64"]))
            elif img["url"]:
                results.append(await self.download(img["url"]))
        if not results:
            raise FlowError("Flow không trả về ảnh nào (có thể prompt bị chặn)")
        return results

    async def generate_video(self, prompt: str, start_image: str | None = None) -> bytes:
        ctx = await self._ctx()
        s = self.settings
        if start_image:
            media_id = await self.upload_image(start_image)
            body = ep.video_i2v_body(ctx, prompt, s.video_model_i2v, s.video_aspect, media_id)
            url = ep.VIDEO_I2V_URL
        else:
            body = ep.video_t2v_body(ctx, prompt, s.video_model_t2v, s.video_aspect)
            url = ep.VIDEO_T2V_URL
        ops = ep.parse_video_ops(await self._post(url, body))
        if not ops:
            raise FlowError("Flow không nhận yêu cầu tạo video")

        deadline = time.time() + s.video_timeout
        while time.time() < deadline:
            await asyncio.sleep(s.video_poll_interval)
            ops = ep.parse_video_ops(await self._post(ep.VIDEO_STATUS_URL, ep.video_status_body(ops))) or ops
            status, video_url = ep.video_op_result(ops[0])
            if status == ep.STATUS_SUCCESS and video_url:
                return await self.download(video_url)
            if status == ep.STATUS_FAILED:
                raise FlowError(f"Tạo video thất bại: {json.dumps(ops[0], ensure_ascii=False)[:300]}")
        raise FlowError("Hết thời gian chờ video")


async def _raise_for(resp) -> None:
    if resp.ok:
        return
    text = (await resp.text())[:500]
    if ep.is_quota_error(resp.status, text):
        raise QuotaError(f"Hết quota (HTTP {resp.status}): {text}")
    if ep.is_auth_error(resp.status, text):
        raise AuthError(f"Lỗi đăng nhập (HTTP {resp.status}): {text}")
    raise FlowError(f"HTTP {resp.status}: {text}")


def _parse_proxy(proxy: str) -> dict:
    from urllib.parse import urlparse

    u = urlparse(proxy if "://" in proxy else "http://" + proxy)
    out = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
    if u.username:
        out["username"] = u.username
        out["password"] = u.password or ""
    return out

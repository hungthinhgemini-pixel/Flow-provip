"""Chạy Playwright + Engine trong một luồng nền có event loop riêng (tách khỏi giao diện Qt)."""

from __future__ import annotations

import asyncio
import threading
from typing import Callable

from flowprovip.accounts import Account
from flowprovip.config import Settings
from flowprovip.engine import Engine
from flowprovip.flow import endpoints as ep
from flowprovip.flow.client import FlowSession
from flowprovip.jobs import Task


class BackgroundLoop:
    """Một asyncio loop chạy mãi trong thread riêng; UI gửi coroutine vào qua submit()."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self._pw = None

    def submit(self, coro, done: Callable | None = None):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if done:
            fut.add_done_callback(done)
        return fut

    async def playwright(self):
        if self._pw is None:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
        return self._pw


async def login_account(bg: BackgroundLoop, account: Account, settings: Settings,
                        log: Callable[[str], None]) -> dict:
    """Mở trình duyệt cho người dùng đăng nhập; tự phát hiện đăng nhập xong rồi tự đóng cửa sổ."""
    pw = await bg.playwright()
    s = FlowSession(account, settings, pw)
    await s.start(headless=False)
    await s.open_flow()
    log(f"[{account.name}] Đã mở trình duyệt: hãy đăng nhập Google. Tool sẽ tự nhận biết khi xong.")
    closed = asyncio.Event()
    s.context.on("close", lambda *_: closed.set())
    result = {"ok": False, "error": "Cửa sổ đã đóng trước khi đăng nhập xong"}
    for _ in range(600):  # tối đa ~20 phút
        if closed.is_set() or not s.context.pages:
            break
        try:
            if await s._refresh_token(force=True):
                result = {"ok": True, "email": account.email}
                break
        except Exception:  # noqa: BLE001 - chưa đăng nhập, đợi tiếp
            pass
        await asyncio.sleep(2)
    account.status = "ok" if result["ok"] else "chưa đăng nhập"
    if result["ok"]:
        log(f"[{account.name}] Đăng nhập thành công: {account.email or 'ok'}")
        await asyncio.sleep(2)  # để Chrome kịp ghi cookie vào profile
    await s.close()
    return result


async def check_account(bg: BackgroundLoop, account: Account, settings: Settings) -> dict:
    pw = await bg.playwright()
    s = FlowSession(account, settings, pw)
    await s.start(headless=True)
    try:
        res = await s.check_login()
    finally:
        await s.close()
    account.status = "ok" if res["ok"] else "chưa đăng nhập"
    return res


class BatchRun:
    def __init__(self, bg: BackgroundLoop, accounts: list[Account], settings: Settings,
                 on_task: Callable[[Task], None], on_log: Callable[[str], None]):
        self.bg, self.accounts, self.settings = bg, accounts, settings
        self.on_task, self.on_log = on_task, on_log
        self.engine: Engine | None = None
        self.sessions: list[FlowSession] = []

    async def run(self, tasks: list[Task]) -> list[Task]:
        ep.apply_overrides(self.settings.endpoint_overrides)
        pw = await self.bg.playwright()
        try:
            for acc in self.accounts:
                s = FlowSession(acc, self.settings, pw)
                try:
                    await s.start()
                    await s.open_flow()
                    res = await s.check_login()
                except Exception as e:  # noqa: BLE001
                    res = {"ok": False, "error": str(e)}
                if res["ok"]:
                    acc.status = "ok"
                    self.sessions.append(s)
                    self.on_log(f"[{acc.name}] sẵn sàng ({acc.email})")
                else:
                    acc.status = "chưa đăng nhập"
                    self.on_log(f"[{acc.name}] bỏ qua: {res.get('error')}")
                    await s.close()
            if not self.sessions:
                raise RuntimeError("Không có tài khoản nào đăng nhập được")
            self.engine = Engine(
                self.sessions, self.settings.output_dir,
                threads_per_account=self.settings.threads_per_account,
                max_retries=self.settings.max_retries,
                images_per_prompt=self.settings.images_per_prompt,
                on_task=self.on_task, on_log=self.on_log,
            )
            return await self.engine.run(tasks)
        finally:
            for s in self.sessions:
                await s.close()
            self.sessions = []

    def cancel(self) -> None:
        if self.engine:
            self.bg.loop.call_soon_threadsafe(self.engine.cancel)

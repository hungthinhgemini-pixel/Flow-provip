"""Bộ điều phối chạy nhiều luồng trên nhiều tài khoản.

Mỗi tài khoản có `threads_per_account` worker lấy tác vụ từ một hàng đợi chung. Khi một tài khoản hết
quota hoặc mất đăng nhập, worker của nó dừng và tác vụ được trả lại hàng đợi cho tài khoản khác.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, Protocol

from flowprovip.flow.client import AuthError, FlowError, QuotaError
from flowprovip.jobs import Kind, Status, Task

log = logging.getLogger(__name__)


class Session(Protocol):
    account: object
    semaphore: asyncio.Semaphore

    async def generate_images(self, prompt: str, count: int = 1, ref_images: list[str] | None = None) -> list[bytes]: ...
    async def generate_video(self, prompt: str, start_image: str | None = None) -> bytes: ...


class Engine:
    def __init__(self, sessions: list[Session], out_dir: str | Path, *, threads_per_account: int = 2,
                 max_retries: int = 2, images_per_prompt: int = 1,
                 on_task: Callable[[Task], None] | None = None,
                 on_log: Callable[[str], None] | None = None):
        self.sessions = sessions
        self.out_dir = Path(out_dir)
        self.threads = max(1, threads_per_account)
        self.max_retries = max_retries
        self.images_per_prompt = images_per_prompt
        self.on_task = on_task or (lambda t: None)
        self.on_log = on_log or (lambda m: log.info(m))
        self._cancel = asyncio.Event()
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._in_flight = 0
        self._dead: set[int] = set()

    def cancel(self) -> None:
        self._cancel.set()

    async def run(self, tasks: list[Task]) -> list[Task]:
        (self.out_dir / "images").mkdir(parents=True, exist_ok=True)
        (self.out_dir / "videos").mkdir(parents=True, exist_ok=True)
        for t in tasks:
            if t.status != Status.DONE:
                t.status = Status.PENDING
                self._queue.put_nowait(t)
        workers = [
            asyncio.create_task(self._worker(i, s))
            for i, s in enumerate(self.sessions)
            for _ in range(self.threads)
        ]
        if workers:
            await asyncio.gather(*workers)
        # Phần còn lại trong hàng đợi: không còn tài khoản nào chạy được hoặc đã huỷ
        while not self._queue.empty():
            t = self._queue.get_nowait()
            t.status = Status.CANCELLED if self._cancel.is_set() else Status.FAILED
            if not self._cancel.is_set():
                t.error = t.error or "Không còn tài khoản khả dụng"
            self.on_task(t)
        return tasks

    async def _worker(self, idx: int, session: Session) -> None:
        name = getattr(session.account, "name", str(idx))
        while not self._cancel.is_set() and idx not in self._dead:
            try:
                task = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                if self._in_flight == 0:
                    return
                await asyncio.sleep(0.3)  # có thể có tác vụ lỗi sắp được trả lại hàng đợi
                continue
            self._in_flight += 1
            try:
                task.status, task.account, task.error = Status.RUNNING, name, ""
                task.attempts += 1
                self.on_task(task)
                await self._execute(session, task)
                task.status = Status.DONE
                self.on_log(f"[{name}] ✓ {task.name}")
            except (QuotaError, AuthError) as e:
                self._dead.add(idx)
                task.attempts -= 1  # không tính là lỗi của tác vụ
                task.status, task.error = Status.PENDING, str(e)
                self._queue.put_nowait(task)
                self.on_log(f"[{name}] dừng tài khoản: {e}")
            except asyncio.CancelledError:
                task.status = Status.CANCELLED
                raise
            except Exception as e:  # noqa: BLE001 - mọi lỗi khác: thử lại
                task.error = str(e) if isinstance(e, FlowError) else f"{type(e).__name__}: {e}"
                if task.attempts <= self.max_retries:
                    task.status = Status.PENDING
                    self._queue.put_nowait(task)
                    self.on_log(f"[{name}] ✗ {task.name} thử lại ({task.attempts}): {task.error}")
                else:
                    task.status = Status.FAILED
                    self.on_log(f"[{name}] ✗ {task.name} bỏ qua: {task.error}")
            finally:
                self._in_flight -= 1
                self.on_task(task)

    async def _execute(self, session: Session, task: Task) -> None:
        async with session.semaphore:
            if task.kind in (Kind.IMAGE, Kind.IMAGE_VIDEO):
                images = [p for p in task.outputs if p.endswith(".png")]
                if not images:  # tránh tạo lại ảnh khi chỉ bước video bị lỗi
                    count = self.images_per_prompt if task.kind == Kind.IMAGE else 1
                    blobs = await session.generate_images(task.prompt, count, task.ref_images)
                    for k, blob in enumerate(blobs):
                        p = self.out_dir / "images" / f"{task.name}_{k + 1}.png"
                        p.write_bytes(blob)
                        images.append(str(p))
                    task.outputs = images
                    self.on_task(task)
                if task.kind == Kind.IMAGE_VIDEO:
                    blob = await session.generate_video(task.video_prompt or task.prompt, start_image=images[0])
                    p = self.out_dir / "videos" / f"{task.name}.mp4"
                    p.write_bytes(blob)
                    task.outputs = images + [str(p)]
            else:
                start = task.ref_images[0] if task.ref_images else None
                blob = await session.generate_video(task.video_prompt or task.prompt, start_image=start)
                p = self.out_dir / "videos" / f"{task.name}.mp4"
                p.write_bytes(blob)
                task.outputs = [str(p)]

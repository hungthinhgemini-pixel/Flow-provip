import asyncio

from flowprovip.engine import Engine
from flowprovip.flow.client import FlowError, QuotaError
from flowprovip.jobs import Kind, Status, Task


class FakeAccount:
    def __init__(self, name):
        self.name = name


class FakeSession:
    def __init__(self, name, quota=None, fail_first=0):
        self.account = FakeAccount(name)
        self.semaphore = asyncio.Semaphore(4)
        self.quota = quota
        self.fail_first = fail_first
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def _work(self):
        self.calls += 1
        if self.quota is not None and self.calls > self.quota:
            raise QuotaError("hết quota")
        if self.fail_first and self.calls <= self.fail_first:
            raise FlowError("lỗi tạm")
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1

    async def generate_images(self, prompt, count=1, ref_images=None):
        await self._work()
        return [b"png"] * count

    async def generate_video(self, prompt, start_image=None):
        await self._work()
        return b"mp4"


def make_tasks(n, kind=Kind.IMAGE):
    return [Task(index=i + 1, prompt=f"p{i}", kind=kind) for i in range(n)]


async def test_runs_all_tasks_in_parallel(tmp_path):
    a, b = FakeSession("a"), FakeSession("b")
    tasks = await Engine([a, b], tmp_path, threads_per_account=3).run(make_tasks(12))
    assert all(t.status == Status.DONE for t in tasks)
    assert a.calls + b.calls == 12
    assert a.max_active > 1 and b.max_active > 1
    assert (tmp_path / "images" / "0001_1.png").exists()


async def test_quota_moves_tasks_to_other_account(tmp_path):
    a, b = FakeSession("a", quota=2), FakeSession("b")
    tasks = await Engine([a, b], tmp_path, threads_per_account=1).run(make_tasks(8))
    assert all(t.status == Status.DONE for t in tasks)
    assert {t.account for t in tasks} <= {"a", "b"}


async def test_all_accounts_exhausted_marks_failed(tmp_path):
    a = FakeSession("a", quota=1)
    tasks = await Engine([a], tmp_path, threads_per_account=1).run(make_tasks(3))
    assert sum(t.status == Status.DONE for t in tasks) == 1
    assert sum(t.status == Status.FAILED for t in tasks) == 2


async def test_retry_then_success(tmp_path):
    a = FakeSession("a", fail_first=1)
    tasks = await Engine([a], tmp_path, threads_per_account=1, max_retries=2).run(make_tasks(1))
    assert tasks[0].status == Status.DONE and tasks[0].attempts == 2


async def test_image_to_video_writes_both(tmp_path):
    a = FakeSession("a")
    tasks = await Engine([a], tmp_path).run(make_tasks(2, Kind.IMAGE_VIDEO))
    assert all(t.status == Status.DONE for t in tasks)
    assert any(p.endswith(".mp4") for p in tasks[0].outputs)
    assert any(p.endswith(".png") for p in tasks[0].outputs)

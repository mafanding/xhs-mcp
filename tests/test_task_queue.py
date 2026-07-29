"""The background task queue.

Long browser work (publishing types a body one keystroke at a time; login waits
for a human) cannot be answered inside an MCP tool call, so it is queued and
polled. Two properties matter: callers get an id immediately, and the work runs
one at a time.
"""

from __future__ import annotations

import asyncio

import pytest

from xhs_mcp.core.tasks import TaskQueue, TaskStatus


@pytest.fixture
def queue() -> TaskQueue:
    return TaskQueue()


async def test_submit_returns_before_the_work_runs(queue: TaskQueue) -> None:
    started = asyncio.Event()

    async def work() -> str:
        started.set()
        await asyncio.sleep(0.2)
        return "done"

    task = queue.submit("publish_image", work)

    assert task.status is TaskStatus.QUEUED
    assert not started.is_set(), "submit must not await the work"
    assert task.to_dict()["taskId"] == task.id


async def test_work_runs_and_records_its_result(queue: TaskQueue) -> None:
    task = queue.submit("publish_image", lambda: _returns({"noteId": "abc"}))

    await queue.wait(task.id, timeout=5)

    assert task.status is TaskStatus.SUCCEEDED
    payload = task.to_dict()
    assert payload["status"] == "succeeded"
    assert payload["result"] == {"noteId": "abc"}
    assert payload["durationMs"] >= 0


async def _returns(value):
    return value


async def test_tasks_run_serially_in_submission_order(queue: TaskQueue) -> None:
    """Concurrent publishing invites rate-limiting, so the queue is serial."""
    events: list[str] = []

    def make(name: str, delay: float):
        async def work() -> None:
            events.append(f"{name}:start")
            await asyncio.sleep(delay)
            events.append(f"{name}:end")

        return work

    first = queue.submit("publish_image", make("A", 0.15))
    second = queue.submit("publish_image", make("B", 0.01))

    await queue.wait(first.id, timeout=5)
    await queue.wait(second.id, timeout=5)

    assert events == ["A:start", "A:end", "B:start", "B:end"]


async def test_failure_is_captured_not_raised(queue: TaskQueue) -> None:
    async def boom() -> None:
        raise ValueError("标题过长")

    task = queue.submit("publish_image", boom)
    await queue.wait(task.id, timeout=5)

    assert task.status is TaskStatus.FAILED
    payload = task.to_dict()
    assert payload["error"] == "ValueError"
    assert payload["message"] == "标题过长"
    assert "result" not in payload


async def test_failure_uses_the_xhs_error_code(queue: TaskQueue) -> None:
    from xhs_mcp.shared.errors import PublishError

    async def boom() -> None:
        raise PublishError("could not find submit button")

    task = queue.submit("publish_image", boom)
    await queue.wait(task.id, timeout=5)

    assert task.to_dict()["error"] == "PublishError"


async def test_one_failure_does_not_stop_the_queue(queue: TaskQueue) -> None:
    async def boom() -> None:
        raise RuntimeError("nope")

    failed = queue.submit("publish_image", boom)
    ok = queue.submit("publish_image", lambda: _returns("fine"))

    await queue.wait(failed.id, timeout=5)
    await queue.wait(ok.id, timeout=5)

    assert failed.status is TaskStatus.FAILED
    assert ok.status is TaskStatus.SUCCEEDED


async def test_get_and_list(queue: TaskQueue) -> None:
    first = queue.submit("publish_image", lambda: _returns(1))
    second = queue.submit("auth_login", lambda: _returns(2))
    await queue.wait(second.id, timeout=5)

    assert queue.get(first.id) is first
    assert queue.get("nope") is None

    listed = queue.list()
    assert [task.id for task in listed] == [second.id, first.id], "newest first"
    assert [task.id for task in queue.list(kind="auth_login")] == [second.id]
    assert len(queue.list(limit=1)) == 1


async def test_wait_returns_none_for_an_unknown_task(queue: TaskQueue) -> None:
    assert await queue.wait("nope", timeout=0.1) is None


async def test_wait_times_out_without_failing_the_task(queue: TaskQueue) -> None:
    async def slow() -> None:
        await asyncio.sleep(5)

    task = queue.submit("publish_image", slow)
    returned = await queue.wait(task.id, timeout=0.1)

    assert returned is task
    assert not task.is_terminal, "a polling timeout must not kill the work"


async def test_pending_work_can_be_cancelled(queue: TaskQueue) -> None:
    async def slow() -> None:
        await asyncio.sleep(1)

    running = queue.submit("publish_image", slow)
    queued = queue.submit("publish_image", slow)

    assert queue.cancel_pending(queued.id) is True
    assert queued.status is TaskStatus.CANCELLED

    await asyncio.sleep(0)  # let the worker pick up the first task
    assert queue.cancel_pending(running.id) is False, "already running"


async def test_shutdown_cancels_queued_work(queue: TaskQueue) -> None:
    async def slow() -> None:
        await asyncio.sleep(5)

    queue.submit("publish_image", slow)
    waiting = queue.submit("publish_image", slow)

    await queue.shutdown()

    assert waiting.status is TaskStatus.CANCELLED
    assert "shutting down" in waiting.error


async def test_task_payload_omits_absent_fields(queue: TaskQueue) -> None:
    task = queue.submit("publish_image", lambda: _returns(None))

    payload = task.to_dict()
    assert set(payload) == {"taskId", "kind", "status", "createdAt"}


async def test_detail_is_echoed_back_for_the_caller(queue: TaskQueue) -> None:
    task = queue.submit(
        "publish_image", lambda: _returns(1), {"title": "今日美食", "mediaCount": 3}
    )

    assert task.to_dict()["detail"] == {"title": "今日美食", "mediaCount": 3}


async def test_unfinished_work_is_never_evicted(queue: TaskQueue) -> None:
    from xhs_mcp.core.tasks import task_queue as module

    original = module._MAX_RETAINED
    module._MAX_RETAINED = 2
    try:
        async def slow() -> None:
            await asyncio.sleep(5)

        long_running = queue.submit("k", slow)
        for _ in range(5):
            queue.submit("k", lambda: _returns(1))

        assert queue.get(long_running.id) is not None
        # Order is preserved: the oldest submission is still listed last.
        assert queue.list(limit=50)[-1].id == long_running.id
    finally:
        module._MAX_RETAINED = original
        await queue.shutdown()


async def test_finished_tasks_are_evicted_but_live_ones_are_kept(
    queue: TaskQueue,
) -> None:
    from xhs_mcp.core.tasks import task_queue as module

    monkey = module._MAX_RETAINED
    module._MAX_RETAINED = 3
    try:
        tasks = [queue.submit("k", lambda: _returns(1)) for _ in range(6)]
        for task in tasks:
            await queue.wait(task.id, timeout=5)

        # Eviction happens on submit, so nothing is dropped until the next one.
        newest = queue.submit("k", lambda: _returns(1))
        await queue.wait(newest.id, timeout=5)

        listed = queue.list(limit=50)
        remaining = [task.id for task in listed]
        assert len(remaining) <= 3
        assert newest.id == remaining[0], "newest first, and it survives"
        assert tasks[0].id not in remaining, "oldest finished result is dropped"
    finally:
        module._MAX_RETAINED = monkey

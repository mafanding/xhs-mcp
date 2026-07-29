"""Background task queue for long-running browser work.

Some operations take minutes: publishing types a note body one keystroke at a
time, and login waits for a human to scan a QR code. An MCP tool call is a
request/response exchange — no client waits twenty minutes for a reply — so
those operations are submitted here, return a task id immediately, and the
caller polls for the result.

The queue is also deliberately **serial**. The browser is a shared resource,
and XiaoHongShu rate-limits accounts that publish in bursts, so running one
long operation at a time is a feature rather than a limitation. Short read-only
operations (status, search, feeds) do not go through the queue at all; they
still run concurrently in their own tabs.

Tasks live in memory for the life of the process. A finished task is retained
so it can be polled, up to ``_MAX_RETAINED`` results.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ...shared.logger import logger

_MAX_RETAINED = 200


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = (
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Task:
    """One unit of queued work and everything a caller can poll about it."""

    id: str
    kind: str
    status: TaskStatus = TaskStatus.QUEUED
    created_at: int = field(default_factory=_now_ms)
    started_at: int | None = None
    finished_at: int | None = None
    result: Any = None
    error: str | None = None
    error_code: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    """Caller-supplied description, e.g. the title being published."""

    _done: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def mark_finished(self) -> None:
        self.finished_at = self.finished_at or _now_ms()
        self._done.set()

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        """The polling payload. Absent values are omitted, not nulled."""
        payload: dict[str, Any] = {
            "taskId": self.id,
            "kind": self.kind,
            "status": self.status.value,
            "createdAt": self.created_at,
        }

        if self.started_at is not None:
            payload["startedAt"] = self.started_at
        if self.finished_at is not None:
            payload["finishedAt"] = self.finished_at
            payload["durationMs"] = self.finished_at - (
                self.started_at or self.created_at
            )
        if self.detail:
            payload["detail"] = self.detail
        if self.result is not None:
            payload["result"] = self.result
        if self.error is not None:
            payload["error"] = self.error_code or "TaskError"
            payload["message"] = self.error

        return payload


class TaskQueue:
    """Runs submitted work one at a time, in submission order."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._order: list[str] = []
        self._pending: asyncio.Queue[tuple[Task, Callable[[], Awaitable[Any]]]] = (
            asyncio.Queue()
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._worker: asyncio.Task[None] | None = None
        self._shutting_down = False

    # ------------------------------------------------------------------
    # Submission and polling
    # ------------------------------------------------------------------

    def submit(
        self,
        kind: str,
        work: Callable[[], Awaitable[Any]],
        detail: dict[str, Any] | None = None,
    ) -> Task:
        """Queue ``work`` and return its task immediately."""
        self._rebind_if_loop_changed()

        if self._shutting_down:
            raise RuntimeError("Task queue is shutting down")

        task = Task(id=uuid.uuid4().hex, kind=kind, detail=detail or {})
        self._tasks[task.id] = task
        self._order.append(task.id)
        self._evict_old_results()

        self._pending.put_nowait((task, work))
        self._ensure_worker()

        logger.info(f"Queued task {task.id} ({kind}); {self.pending_count} pending")
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(self, limit: int = 20, kind: str | None = None) -> list[Task]:
        """Most recently submitted first."""
        tasks = [self._tasks[tid] for tid in reversed(self._order) if tid in self._tasks]
        if kind is not None:
            tasks = [task for task in tasks if task.kind == kind]
        return tasks[:limit]

    async def wait(self, task_id: str, timeout: float | None = None) -> Task | None:
        """Block until the task finishes. Used by the CLI, where blocking is fine."""
        task = self._tasks.get(task_id)
        if task is None:
            return None

        if task.is_terminal:
            return task

        try:
            await asyncio.wait_for(task._done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

        return task

    @property
    def pending_count(self) -> int:
        return self._pending.qsize()

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _rebind_if_loop_changed(self) -> None:
        """Re-create loop-bound state when the running loop is not ours.

        ``asyncio.Queue`` and the worker task belong to the loop that created
        them. A process normally has one loop for its whole life, so this is a
        no-op there — but a queue that silently stops draining when the loop
        changes is a nasty failure mode, so it rebinds instead.
        """
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            return

        if self._loop is running:
            return

        if self._loop is not None:
            logger.debug("Task queue rebinding to a new event loop")

        self._loop = running
        self._worker = None
        self._pending = asyncio.Queue()
        # A new loop is a new server lifecycle. Without this a queue that was
        # shut down once would refuse every later submission for the life of
        # the process.
        self._shutting_down = False

    def _ensure_worker(self) -> None:
        """Start the worker lazily: submit() may be called outside a loop."""
        if self._worker is None or self._worker.done():
            self._worker = asyncio.ensure_future(self._run())

    async def _run(self) -> None:
        while True:
            try:
                task, work = await self._pending.get()
            except asyncio.CancelledError:
                return

            if task.status is TaskStatus.CANCELLED:
                self._pending.task_done()
                continue

            task.status = TaskStatus.RUNNING
            task.started_at = _now_ms()
            logger.info(f"Running task {task.id} ({task.kind})")

            try:
                task.result = await work()
                task.status = TaskStatus.SUCCEEDED
                logger.info(f"Task {task.id} succeeded")
            except asyncio.CancelledError:
                task.status = TaskStatus.CANCELLED
                task.error = "Task cancelled"
                task.finished_at = _now_ms()
                task._done.set()
                self._pending.task_done()
                raise
            except Exception as error:
                task.status = TaskStatus.FAILED
                task.error = str(error)
                task.error_code = getattr(error, "error_code", None) or type(
                    error
                ).__name__
                logger.error(f"Task {task.id} failed: {error}")
            finally:
                if task.finished_at is None:
                    task.finished_at = _now_ms()
                    task._done.set()
                    self._pending.task_done()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def cancel_pending(self, task_id: str) -> bool:
        """Cancel a task that has not started. Running tasks are left alone."""
        task = self._tasks.get(task_id)
        if task is None or task.status is not TaskStatus.QUEUED:
            return False

        task.status = TaskStatus.CANCELLED
        task.error = "Task cancelled before it started"
        task.finished_at = _now_ms()
        task._done.set()
        return True

    async def shutdown(self) -> None:
        """Stop the worker; anything still queued is marked cancelled."""
        self._shutting_down = True

        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except (asyncio.CancelledError, Exception):
                pass
        self._worker = None

        while not self._pending.empty():
            task, _ = self._pending.get_nowait()
            if not task.is_terminal:
                task.status = TaskStatus.CANCELLED
                task.error = "Task cancelled: server shutting down"
                task.finished_at = _now_ms()
                task._done.set()

    def _evict_old_results(self) -> None:
        """Drop the oldest finished results once past the retention cap.

        Unfinished work is never evicted, and surviving tasks keep their
        submission order — callers list newest-first off this list.
        """
        if len(self._order) <= _MAX_RETAINED:
            return

        evictable = sum(
            1
            for tid in self._order
            if (task := self._tasks.get(tid)) is None or task.is_terminal
        )
        to_drop = min(len(self._order) - _MAX_RETAINED, evictable)

        if to_drop <= 0:
            return

        kept: list[str] = []
        for tid in self._order:
            task = self._tasks.get(tid)
            if to_drop > 0 and (task is None or task.is_terminal):
                to_drop -= 1
                self._tasks.pop(tid, None)
                continue
            kept.append(tid)

        self._order = kept


_queue = TaskQueue()


def get_task_queue() -> TaskQueue:
    """The process-wide queue every entry point submits long work to."""
    return _queue

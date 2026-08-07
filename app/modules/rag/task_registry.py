from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class ChatTask:
    owner_id: int
    cancel_event: asyncio.Event
    created_at: float


class ChatTaskRegistry:
    """单进程任务注册表；任务只能由创建它的用户取消。"""

    def __init__(self) -> None:
        self._tasks: dict[str, ChatTask] = {}
        self._lock = threading.Lock()

    def register(self, task_id: str, owner_id: int) -> asyncio.Event:
        event = asyncio.Event()
        with self._lock:
            self._tasks[task_id] = ChatTask(owner_id, event, time.monotonic())
        return event

    def unregister(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)

    def cancel(self, task_id: str, owner_id: int) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None or task.owner_id != owner_id:
            return False
        task.cancel_event.set()
        return True

    def active_count(self) -> int:
        with self._lock:
            return len(self._tasks)


registry = ChatTaskRegistry()

"""进程内聊天任务注册表

支持 RAGent 前端的 "停止生成" (/rag/v3/stop):
- 流式生成开始时注册 task_id -> asyncio.Event
- 前端调用 stop 时 set 事件, 生成循环检测到后中断并发送 INTERRUPTED 结束事件
- 任务结束/异常时注销

注意: 单进程部署适用; 多 worker 部署需替换为 Redis 等共享存储。
"""

from __future__ import annotations

import asyncio
import threading
import time


class ChatTaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Event] = {}
        self._created_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def register(self, task_id: str) -> asyncio.Event:
        event = asyncio.Event()
        with self._lock:
            self._tasks[task_id] = event
            self._created_at[task_id] = time.monotonic()
        return event

    def unregister(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)
            self._created_at.pop(task_id, None)

    def cancel(self, task_id: str) -> bool:
        """请求取消任务, 返回该任务是否存在"""
        with self._lock:
            event = self._tasks.get(task_id)
        if event is None:
            return False
        event.set()
        return True

    def active_count(self) -> int:
        with self._lock:
            return len(self._tasks)


registry = ChatTaskRegistry()

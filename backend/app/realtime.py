"""In-process event bus feeding SSE and WebSocket clients.

Events are also persisted as TaskEvent rows, so a reconnecting client can replay
history from the REST API. The bus itself is best-effort live delivery.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional


class EventBus:
    def __init__(self) -> None:
        self._subscribers: Dict[int, asyncio.Queue] = {}
        self._sequence = 0

    def subscribe(self) -> "asyncio.Queue[Dict[str, Any]]":
        self._sequence += 1
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers[self._sequence] = queue
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[Dict[str, Any]]") -> None:
        for key, value in list(self._subscribers.items()):
            if value is queue:
                self._subscribers.pop(key, None)

    def publish(self, event: Dict[str, Any]) -> None:
        for queue in list(self._subscribers.values()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop the oldest so the stream stays live.
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:
                    pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def stream(self, queue: "asyncio.Queue[Dict[str, Any]]", heartbeat: float = 20.0) -> AsyncIterator[Dict[str, Any]]:
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    yield {"type": "heartbeat"}
        finally:
            self.unsubscribe(queue)


bus = EventBus()


def emit_task_event(task_id: str, event_type: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    bus.publish({"type": event_type, "task_id": task_id, "message": message, "data": data or {}})


def active_subscribers() -> int:
    return bus.subscriber_count

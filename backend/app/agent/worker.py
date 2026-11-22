"""Durable background worker + scheduler.

Tasks live in the database, so a restart loses nothing. The worker claims queued
tasks, respects the concurrency limit, and the scheduler promotes due reminders,
scheduled tasks and recurring content workflows.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Set

from sqlalchemy import or_

from ..config import settings
from ..db import SessionLocal
from ..models import Task, User, Workflow, utcnow
from .executor import execute_task

logger = logging.getLogger("nova.worker")


class Worker:
    def __init__(self) -> None:
        self.started_at: Optional[datetime] = None
        self.last_tick: Optional[datetime] = None
        self.last_error: str = ""
        self.running: Set[str] = set()
        self.processed: int = 0
        self._stopping = False
        self._loop_task: Optional[asyncio.Task] = None
        self._jobs: Set[asyncio.Task] = set()

    @property
    def alive(self) -> bool:
        return bool(self._loop_task and not self._loop_task.done())

    def status(self) -> dict:
        return {
            "alive": self.alive,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_tick": self.last_tick.isoformat() if self.last_tick else None,
            "running": len(self.running),
            "concurrency": settings.worker_concurrency,
            "processed": self.processed,
            "last_error": self.last_error,
        }

    async def start(self) -> None:
        self.started_at = utcnow()
        self._loop_task = asyncio.create_task(self._run(), name="nova-worker")
        logger.info("Worker started (concurrency=%s)", settings.worker_concurrency)

    async def stop(self) -> None:
        self._stopping = True
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self.tick()
                self.last_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{exc}"
                logger.exception("Worker tick failed")
            await asyncio.sleep(2)

    async def tick(self) -> None:
        self.last_tick = utcnow()
        if settings.scheduler_enabled:
            self._schedule()

        db = SessionLocal()
        try:
            capacity = max(0, settings.worker_concurrency - len(self.running))
            if capacity == 0:
                return
            candidates = (
                db.query(Task)
                .filter(Task.status == "queued")
                .order_by(Task.priority.asc(), Task.created_at.asc())
                .limit(capacity * 4)
                .all()
            )
            now = utcnow()
            started = 0
            for task in candidates:
                if started >= capacity:
                    break
                if task.scheduled_for and task.scheduled_for > now:
                    if task.status == "queued":
                        task.status = "scheduled"  # not due yet; scheduler will promote it
                        db.commit()
                    continue
                if task.id in self.running:
                    continue
                self._spawn(task.id)
                started += 1
        finally:
            db.close()

    def _spawn(self, task_id: str) -> None:
        self.running.add(task_id)

        async def runner() -> None:
            try:
                await execute_task(task_id)
                self.processed += 1
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{task_id}: {exc}"
                logger.exception("Task %s crashed", task_id)
            finally:
                self.running.discard(task_id)

        job = asyncio.create_task(runner(), name=f"task-{task_id}")
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)

    def _schedule(self) -> None:
        db = SessionLocal()
        try:
            now = utcnow()
            due = (
                db.query(Task)
                .filter(Task.status == "scheduled", Task.scheduled_for.isnot(None), Task.scheduled_for <= now)
                .limit(20)
                .all()
            )
            for task in due:
                task.status = "queued"
            workflows = (
                db.query(Workflow)
                .filter(Workflow.enabled.is_(True), or_(Workflow.next_run_at.is_(None), Workflow.next_run_at <= now))
                .limit(10)
                .all()
            )
            for workflow in workflows:
                user = db.get(User, workflow.user_id)
                if user is None:
                    continue
                task = Task(
                    user_id=user.id,
                    title=workflow.name[:250],
                    prompt=workflow.prompt,
                    kind=workflow.kind,
                    status="queued",
                    source="workflow",
                )
                db.add(task)
                workflow.last_run_at = now
                workflow.next_run_at = _next_run(workflow, now)
                db.flush()
            db.commit()
        finally:
            db.close()


def _next_run(workflow: Workflow, now: datetime) -> datetime:
    if workflow.schedule_kind == "interval":
        return now + timedelta(minutes=max(5, workflow.interval_minutes))
    try:
        hour, minute = (int(part) for part in (workflow.at_time or "09:00").split(":"))
    except ValueError:
        hour, minute = 9, 0
    target = now.replace(hour=min(hour, 23), minute=min(minute, 59), second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


worker = Worker()

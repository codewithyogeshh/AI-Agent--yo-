"""Orchestrator: turns an instruction into a task, handles direct control commands,
and produces the acknowledgement the user sees in chat / WhatsApp.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, or_

from ..db import SessionLocal
from ..models import ChatMessage, Task, TaskEvent, User, utcnow
from ..tools import catalog_text
from . import permissions
from .planner import Plan, make_plan


def memory_context(db, user: User, limit: int = 6) -> str:
    from ..models import Memory

    memories = (
        db.query(Memory)
        .filter(Memory.user_id == user.id)
        .order_by(Memory.importance.desc(), Memory.updated_at.desc())
        .limit(limit)
        .all()
    )
    if not memories:
        return ""
    return "\n".join(f"- [{m.kind}] {m.title}: {m.content[:220]}" for m in memories)


def _control(prompt: str) -> Optional[str]:
    lowered = prompt.lower().strip()
    if re.search(r"\b(emergency stop|stop everything|halt all|abort all)\b", lowered):
        return "stop_all"
    if re.search(r"\bpause (all|every)( running)? tasks?\b", lowered):
        return "pause_all"
    if re.search(r"\bresume (all|every)( paused)? tasks?\b", lowered):
        return "resume_all"
    if re.search(r"\b(show|list) (me )?(today'?s )?completed tasks?\b", lowered):
        return "list_completed"
    if re.search(r"\bcancel task\b", lowered):
        return "cancel_task"
    return None


def handle_control(db, user: User, command: str, prompt: str) -> Optional[Task]:
    now = utcnow()
    active = (
        db.query(Task)
        .filter(Task.user_id == user.id, Task.status.in_(["queued", "running", "planning"]))
        .all()
    )
    result: Dict[str, Any] = {}
    if command == "stop_all":
        for task in active:
            task.status = "cancelled"
            task.error = "Emergency stop"
            task.finished_at = now
        result = {"cancelled": len(active), "message": f"Emergency stop: {len(active)} active task(s) cancelled."}
    elif command == "pause_all":
        for task in active:
            task.status = "paused"
        result = {"paused": len(active), "message": f"{len(active)} task(s) paused. Say “resume all tasks” to continue."}
    elif command == "resume_all":
        paused = db.query(Task).filter(Task.user_id == user.id, Task.status == "paused").all()
        for task in paused:
            task.status = "queued"
        result = {"resumed": len(paused), "message": f"{len(paused)} task(s) queued again."}
    elif command == "list_completed":
        completed = (
            db.query(Task)
            .filter(Task.user_id == user.id, Task.status == "completed", Task.finished_at >= now - timedelta(days=1))
            .order_by(desc(Task.finished_at))
            .limit(20)
            .all()
        )
        result = {
            "count": len(completed),
            "message": f"{len(completed)} task(s) completed in the last 24h:\n"
            + "\n".join(f"• {t.title} ({t.id})" for t in completed),
        }
    elif command == "cancel_task":
        match = re.search(r"(t_[a-f0-9]{4,16}|task\s+([a-f0-9]{4,16}))", prompt.lower())
        target = None
        if match:
            token = match.group(1)
            token = token.split()[-1]
            target = (
                db.query(Task)
                .filter(Task.user_id == user.id, Task.id.like(f"%{token.replace('t_', '')}%"))
                .order_by(desc(Task.created_at))
                .first()
            )
        if target is None:
            result = {"message": "I could not match that task ID. Task IDs look like t_1a2b3c4d5e6f."}
        else:
            target.status = "cancelled"
            target.finished_at = now
            result = {"cancelled": target.id, "message": f"Cancelled “{target.title}” ({target.id})."}

    record = Task(
        user_id=user.id,
        title=f"Control: {command.replace('_', ' ')}",
        prompt=prompt,
        kind="control",
        status="completed",
        progress=100,
        source="control",
        result_json=json.dumps(result),
        started_at=now,
        finished_at=now,
        current_step="Applied directly",
    )
    db.add(record)
    db.flush()
    db.add(TaskEvent(task_id=record.id, seq=1, type="result", message=str(result.get("message", ""))[:2000]))
    db.commit()
    return record


async def submit_task(db, user: User, prompt: str, source: str = "web") -> Task:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Empty instruction")
    command = _control(prompt)
    if command:
        return handle_control(db, user, command, prompt)

    prefs = permissions.get_settings_map(db, user)
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = db.query(Task).filter(Task.user_id == user.id, Task.created_at >= day_start).count()
    if today_count >= int(prefs.get("max_daily_tasks", 40)):
        raise ValueError(
            f"Daily task limit reached ({prefs.get('max_daily_tasks')}). Raise it in Permissions if this is intentional."
        )

    plan: Plan = await make_plan(prompt, memory_context(db, user))
    task = Task(
        user_id=user.id,
        title=plan.title[:290],
        prompt=prompt,
        kind=plan.kind,
        agent=_agent_for(plan.kind),
        status="queued",
        plan_json=json.dumps(plan.steps),
        source=source,
        approval_required=any(_risk(step.get("tool", "")) != "safe" for step in plan.steps),
    )
    db.add(task)
    db.flush()
    db.add(
        TaskEvent(
            task_id=task.id,
            seq=1,
            type="status",
            message=f"Task received — {plan.notes}",
            data_json="{}",
        )
    )
    db.commit()
    return task


def _risk(tool_name: str) -> str:
    from ..tools import get_tool

    tool = get_tool(tool_name)
    return tool.risk if tool else "safe"


def _agent_for(kind: str) -> str:
    return {
        "research": "research",
        "content_video": "video_production",
        "youtube": "youtube",
        "youtube_upload": "youtube",
        "instagram": "instagram",
        "email": "assistant",
        "calendar": "assistant",
        "reminder": "assistant",
        "tasks": "assistant",
        "files": "coding",
        "code": "coding",
        "system": "orchestrator",
    }.get(kind, "orchestrator")


def acknowledgement(task: Task) -> str:
    try:
        steps = json.loads(task.plan_json or "[]")
    except json.JSONDecodeError:
        steps = []
    first = steps[0]["label"] if steps else "planning"
    return (
        f"Task received ({task.id}). I am working on: {task.title}. "
        f"{len(steps)} step(s), starting with: {first}. I'll report back when it is verified."
    )


def record_chat(db, user: User, role: str, content: str, task_id: Optional[str] = None, source: str = "web") -> ChatMessage:
    message = ChatMessage(user_id=user.id, role=role, content=content, task_id=task_id, source=source)
    db.add(message)
    db.commit()
    return message

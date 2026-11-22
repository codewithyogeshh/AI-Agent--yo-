"""Memory, task and reminder tools — the agent's working + long-term context."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import or_

from ..models import Memory, Task, TaskEvent, utcnow
from .base import ToolContext, ToolResult, tool

SENSITIVE = (
    "password", "passwd", "api key", "apikey", "secret", "token", "credit card", "cvv",
    "social security", "aadhaar", "pan number", "bank account", "private key",
)


def _looks_sensitive(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in SENSITIVE)


@tool(
    name="memory.save",
    description="Store a durable fact, preference or project note in NOVA's memory.",
    category="memory",
    params={
        "title": {"type": "string", "required": True},
        "content": {"type": "string", "required": True},
        "kind": {"type": "string", "required": False, "description": "fact | preference | project | workflow"},
        "tags": {"type": "string", "required": False},
    },
)
async def memory_save(ctx: ToolContext, title: str, content: str, kind: str = "fact", tags: str = "") -> ToolResult:
    if _looks_sensitive(content) or _looks_sensitive(title):
        return ToolResult(
            False,
            "Refused: that looks like a credential or financial detail. NOVA never stores secrets in memory.",
            verified=False,
        )
    existing = (
        ctx.db.query(Memory)
        .filter(Memory.user_id == ctx.user.id, Memory.title == title[:200])
        .first()
    )
    if existing:
        existing.content = content
        existing.kind = kind
        existing.tags = tags
        existing.updated_at = utcnow()
        ctx.db.commit()
        return ToolResult(True, f"Memory updated: {title[:60]}", {"memory_id": existing.id})
    memory = Memory(
        user_id=ctx.user.id, title=title[:200], content=content, kind=kind, tags=tags, source="agent"
    )
    ctx.db.add(memory)
    ctx.db.commit()
    return ToolResult(True, f"Remembered: {title[:60]}", {"memory_id": memory.id})


@tool(
    name="memory.search",
    description="Search stored memories to ground the current task.",
    category="memory",
    params={"query": {"type": "string", "required": True}, "limit": {"type": "integer", "required": False}},
)
async def memory_search(ctx: ToolContext, query: str, limit: int = 5) -> ToolResult:
    words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 2][:6]
    q = ctx.db.query(Memory).filter(Memory.user_id == ctx.user.id)
    if words:
        clauses = []
        for word in words:
            clauses.append(Memory.title.ilike(f"%{word}%"))
            clauses.append(Memory.content.ilike(f"%{word}%"))
            clauses.append(Memory.tags.ilike(f"%{word}%"))
        q = q.filter(or_(*clauses))
    rows = q.order_by(Memory.updated_at.desc()).limit(int(limit)).all()
    return ToolResult(
        True,
        f"{len(rows)} relevant memories" if rows else "No relevant memories yet",
        {"memories": [{"id": m.id, "title": m.title, "content": m.content[:800], "kind": m.kind} for m in rows]},
    )


def parse_when(instruction: str, tz: str = "UTC") -> Optional[datetime]:
    """Parse common natural-language reminders: 'tomorrow at 9am', 'in 2 hours', 'friday 17:30'."""
    text = instruction.lower()
    now = utcnow()
    time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    hour, minute = 9, 0
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        meridiem = time_match.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        if not meridiem and hour < 7:  # "at 9" most likely 9am
            hour = hour
    relative = re.search(r"in\s+(\d+)\s*(minute|min|hour|hr|day|week)s?", text)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        delta = {
            "minute": timedelta(minutes=amount), "min": timedelta(minutes=amount),
            "hour": timedelta(hours=amount), "hr": timedelta(hours=amount),
            "day": timedelta(days=amount), "week": timedelta(weeks=amount),
        }[unit]
        return (now + delta).replace(second=0, microsecond=0)
    if "tomorrow" in text:
        base = now + timedelta(days=1)
    elif "today" in text or "tonight" in text:
        base = now
    else:
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        found = next((i for i, day in enumerate(days) if day in text), None)
        if found is None:
            if time_match:
                base = now
            else:
                return None
        else:
            ahead = (found - now.weekday()) % 7 or 7
            base = now + timedelta(days=ahead)
    return base.replace(hour=min(hour, 23), minute=min(minute, 59), second=0, microsecond=0)


@tool(
    name="reminder.create",
    description="Create a scheduled reminder (appears in tasks and the calendar).",
    category="productivity",
    params={
        "instruction": {"type": "string", "required": True, "description": "e.g. 'tomorrow at 9am call the bank'"},
        "title": {"type": "string", "required": False},
    },
)
async def reminder_create(ctx: ToolContext, instruction: str, title: str = "") -> ToolResult:
    when = parse_when(instruction, ctx.user.timezone)
    if when is None:
        return ToolResult(
            False,
            "I could not find a date/time in that request. Try “tomorrow at 9am” or “in 2 hours”.",
            verified=False,
        )
    clean = title or re.sub(
        r"^(please\s+)?(remind me( to)?|set a reminder( to| for)?|create a reminder( to| for)?)\s*",
        "",
        instruction,
        flags=re.I,
    )
    clean = re.sub(r"\b(tomorrow|today|tonight|at\s+\d{1,2}(:\d{2})?\s*(am|pm)?|in\s+\d+\s*(minutes?|hours?|days?))\b", "", clean, flags=re.I).strip(" .")
    task = Task(
        user_id=ctx.user.id,
        title=(clean or "Reminder")[:250],
        prompt=instruction,
        kind="reminder",
        status="scheduled",
        scheduled_for=when,
        source=ctx.task.source if ctx.task else "agent",
        plan_json=json.dumps([{"tool": "notify.reminder", "args": {}, "status": "pending", "index": 0}]),
    )
    ctx.db.add(task)
    ctx.db.flush()
    ctx.db.add(TaskEvent(task_id=task.id, seq=1, type="info", message=f"Reminder scheduled for {when.isoformat(timespec='minutes')} UTC"))
    ctx.db.commit()
    return ToolResult(
        True,
        f"Reminder set for {when.strftime('%a %d %b %H:%M')} UTC: {task.title[:60]}",
        {"reminder_id": task.id, "scheduled_for": when.isoformat()},
        artifacts=[{"kind": "reminder", "title": task.title, "task_id": task.id}],
    )


@tool(
    name="tasks.report",
    description="Compile a day or week report of tasks: completed, failed, running, upcoming.",
    category="productivity",
    params={"scope": {"type": "string", "required": False, "description": "day | week"}},
)
async def tasks_report(ctx: ToolContext, scope: str = "day") -> ToolResult:
    since = utcnow() - timedelta(days=7 if scope == "week" else 1)
    rows = (
        ctx.db.query(Task)
        .filter(Task.user_id == ctx.user.id, Task.created_at >= since)
        .order_by(Task.created_at.desc())
        .all()
    )
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for task in rows:
        buckets.setdefault(task.status, []).append(
            {"id": task.id, "title": task.title, "status": task.status, "progress": task.progress}
        )
    upcoming = (
        ctx.db.query(Task)
        .filter(Task.user_id == ctx.user.id, Task.scheduled_for.isnot(None), Task.scheduled_for >= utcnow())
        .order_by(Task.scheduled_for)
        .limit(10)
        .all()
    )
    lines = [f"{key.replace('_', ' ').title()}: {len(value)}" for key, value in buckets.items()]
    body = (
        f"# Task report ({scope})\n\n"
        f"Generated {utcnow().isoformat(timespec='seconds')}Z\n\n"
        + ("\n".join(f"- {line}" for line in lines) or "- No tasks recorded in this window.")
        + "\n\n## Details\n\n"
        + "\n".join(
            f"- [{(t['status'] or '').upper()}] {t['title']} ({t['progress']}%) — {t['id']}"
            for group in buckets.values()
            for t in group
        )
        + "\n\n## Upcoming\n\n"
        + ("\n".join(f"- {t.scheduled_for:%a %d %b %H:%M} — {t.title}" for t in upcoming) or "- Nothing scheduled.")
    )
    path = ctx.user_dir / "reports" / f"tasks-{scope}-{utcnow():%Y%m%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return ToolResult(
        True,
        f"Task report: {len(rows)} tasks in the last {'7 days' if scope == 'week' else '24 hours'}",
        {"counts": {k: len(v) for k, v in buckets.items()}, "path": str(path)},
        artifacts=[{"kind": "report", "title": f"{scope.title()} task report", "path": str(path)}],
    )


@tool(
    name="notify.reminder",
    description="Deliver a scheduled reminder to the user's channels.",
    category="productivity",
    params={"message": {"type": "string", "required": False}},
)
async def notify_reminder(ctx: ToolContext, message: str = "") -> ToolResult:
    from ..services.notifications import notify_user

    text = message or (ctx.task.title if ctx.task else "Reminder")
    channels = await notify_user(ctx.db, ctx.user, "Reminder", text)
    return ToolResult(True, f"Reminder delivered via {', '.join(channels) or 'dashboard'}", {"channels": channels})

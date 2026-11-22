"""API serialisation helpers — one shape per entity, shared by every router."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .models import (
    Approval, AuditLog, ChatMessage, ContentItem, DesktopJob, MediaAsset, Memory,
    Notification, Task, TaskEvent, User, Workflow,
)


def _json(value: str, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (json.JSONDecodeError, TypeError):
        return default


def user_dict(user: User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "phone": user.phone,
        "timezone": user.timezone,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def event_dict(event: TaskEvent) -> Dict[str, Any]:
    return {
        "id": event.id,
        "seq": event.seq,
        "type": event.type,
        "message": event.message,
        "data": _json(event.data_json, {}),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def task_dict(task: Task, detail: bool = False, events: Optional[List[TaskEvent]] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": task.id,
        "title": task.title,
        "prompt": task.prompt,
        "kind": task.kind,
        "agent": task.agent,
        "status": task.status,
        "priority": task.priority,
        "progress": task.progress,
        "current_step": task.current_step,
        "source": task.source,
        "error": task.error,
        "approval_required": task.approval_required,
        "scheduled_for": task.scheduled_for.isoformat() if task.scheduled_for else None,
        "recurrence": task.recurrence,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "duration_seconds": (
            round((task.finished_at - task.started_at).total_seconds())
            if task.finished_at and task.started_at
            else None
        ),
    }
    if detail:
        data["plan"] = _json(task.plan_json, [])
        data["result"] = _json(task.result_json, {})
        data["events"] = [event_dict(e) for e in (events or [])]
    return data


def approval_dict(approval: Approval, task_title: str = "") -> Dict[str, Any]:
    return {
        "id": approval.id,
        "task_id": approval.task_id,
        "task_title": task_title,
        "tool": approval.tool,
        "action": approval.action,
        "explanation": approval.explanation,
        "payload": _json(approval.payload_json, {}),
        "risk": approval.risk,
        "status": approval.status,
        "note": approval.note,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
    }


def memory_dict(memory: Memory) -> Dict[str, Any]:
    return {
        "id": memory.id,
        "kind": memory.kind,
        "title": memory.title,
        "content": memory.content,
        "tags": [t for t in (memory.tags or "").split(",") if t],
        "source": memory.source,
        "importance": memory.importance,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    }


def content_dict(item: ContentItem) -> Dict[str, Any]:
    meta = _json(item.metadata_json, {})
    return {
        "id": item.id,
        "platform": item.platform,
        "kind": item.kind,
        "title": item.title,
        "status": item.status,
        "hook": item.hook,
        "script": item.script,
        "caption": item.caption,
        "hashtags": item.hashtags,
        "description": item.description,
        "metadata": meta,
        "asset_url": f"/api/content/{item.id}/asset" if item.asset_path else "",
        "thumb_url": f"/api/content/{item.id}/thumbnail" if item.thumb_path else "",
        "has_video": bool(item.asset_path),
        "task_id": item.task_id,
        "scheduled_for": item.scheduled_for.isoformat() if item.scheduled_for else None,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "external_id": item.external_id,
        "duration_seconds": meta.get("duration_seconds"),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def asset_dict(asset: MediaAsset) -> Dict[str, Any]:
    return {
        "id": asset.id,
        "name": asset.name,
        "path": asset.path,
        "mime": asset.mime,
        "size": asset.size,
        "kind": asset.kind,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


def notification_dict(row: Notification) -> Dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "level": row.level,
        "read": row.read,
        "channel": row.channel,
        "meta": _json(row.meta_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def log_dict(row: AuditLog) -> Dict[str, Any]:
    return {
        "id": row.id,
        "actor": row.actor,
        "action": row.action,
        "target": row.target,
        "level": row.level,
        "ip": row.ip,
        "data": _json(row.data_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def chat_dict(row: ChatMessage) -> Dict[str, Any]:
    return {
        "id": row.id,
        "role": row.role,
        "content": row.content,
        "task_id": row.task_id,
        "source": row.source,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def workflow_dict(row: Workflow) -> Dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "prompt": row.prompt,
        "schedule_kind": row.schedule_kind,
        "at_time": row.at_time,
        "interval_minutes": row.interval_minutes,
        "enabled": row.enabled,
        "publishing_mode": row.publishing_mode,
        "config": _json(row.config_json, {}),
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
    }


def desktop_job_dict(row: DesktopJob) -> Dict[str, Any]:
    return {
        "id": row.id,
        "command": row.command,
        "cwd": row.cwd,
        "status": row.status,
        "output": row.output[-4000:],
        "exit_code": row.exit_code,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }

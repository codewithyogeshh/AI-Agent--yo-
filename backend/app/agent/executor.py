"""Task executor.

One path for every action:
  permission check -> approval gate -> tool call (with retries) -> verification
  -> persisted event -> live event -> notification.

A task is only reported as completed when every executed step verified.
"""
from __future__ import annotations

import json
import traceback
from datetime import timedelta
from typing import Any, Dict, Optional

from sqlalchemy import func

from ..config import settings
from ..db import SessionLocal
from ..models import Approval, Task, TaskEvent, User, utcnow
from ..realtime import emit_task_event
from ..services.notifications import notify_user
from ..tools import ToolContext, get_tool
from . import permissions
from .planner import make_plan


class ExecutorResult(str):
    pass


def _append_event(db, task: Task, seq: int, event_type: str, message: str, data: Dict[str, Any]) -> int:
    db.add(
        TaskEvent(
            task_id=task.id,
            seq=seq,
            type=event_type,
            message=message[:4000],
            data_json=json.dumps(data, default=str)[:20000],
        )
    )
    db.commit()
    emit_task_event(task.id, event_type, message, data)
    return seq + 1


def _resolve_args(args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and value.startswith("$"):
            reference = value[1:]
            if reference in state:
                resolved[key] = state[reference]
            continue  # unresolved placeholders become missing params, which tools report
        resolved[key] = value
    return resolved


def _plan_agent(kind: str) -> str:
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
        "report": "research",
        "system": "orchestrator",
    }.get(kind, "orchestrator")


async def execute_task(task_id: str) -> str:
    """Returns a terminal state string: completed | failed | waiting_approval | cancelled."""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if task is None:
            return "missing"
        user = db.get(User, task.user_id)
        if user is None:
            task.status = "failed"
            task.error = "Owner account no longer exists"
            db.commit()
            return "failed"
        if task.status in {"cancelled", "completed", "paused", "waiting_approval"}:
            return task.status

        seq = (db.query(func.max(TaskEvent.seq)).filter(TaskEvent.task_id == task.id).scalar() or 0) + 1

        if not task.plan_json or task.plan_json == "[]":
            task.status = "planning"
            db.commit()
            seq = _append_event(db, task, seq, "status", "Planning the task", {})
            plan = await make_plan(task.prompt)
            task.plan_json = json.dumps(plan.steps)
            task.kind = plan.kind
            task.agent = _plan_agent(plan.kind)
            task.title = task.title or plan.title
            db.commit()
            seq = _append_event(db, task, seq, "plan", f"{len(plan.steps)} steps planned ({plan.planner})",
                                {"steps": plan.steps, "planner": plan.planner})

        plan = json.loads(task.plan_json)
        state: Dict[str, Any] = {}

        task.status = "running"
        task.started_at = task.started_at or utcnow()
        task.error = ""
        db.commit()

        artifacts: list = []
        total = max(1, len(plan))

        def save_plan() -> None:
            task.plan_json = json.dumps(plan)
            db.commit()

        for index, step in enumerate(plan):
            tool = get_tool(step.get("tool", ""))
            if tool is None:
                step["status"] = "failed"
                step["error"] = f"Unknown tool {step.get('tool')}"
                save_plan()
                task.status, task.error = "failed", f"Unknown tool: {step.get('tool')}"
                db.commit()
                _append_event(db, task, seq, "error", task.error, {})
                return "failed"

            if step.get("status") in {"done"}:
                state.update(step.get("output") or {})
                continue

            db.refresh(task)
            if task.status in {"cancelled", "paused"}:
                _append_event(db, task, seq, "status", f"Task {task.status} by user", {})
                return task.status

            decision = permissions.evaluate(db, user, tool.name, tool.risk)
            if decision == "deny":
                task.status = "failed"
                task.error = f"Blocked by permissions: {tool.name} is disabled or requires explicit authorisation."
                task.finished_at = utcnow()
                db.commit()
                _append_event(db, task, seq, "error", task.error, {"tool": tool.name})
                return "failed"

            if decision == "approval" and not step.get("approved"):
                approval = (
                    db.query(Approval)
                    .filter(Approval.task_id == task.id, Approval.tool == tool.name, Approval.status == "pending")
                    .first()
                )
                if approval is None:
                    args = _resolve_args(step.get("args") or {}, state)
                    approval = Approval(
                        user_id=user.id,
                        task_id=task.id,
                        tool=tool.name,
                        action=step.get("label") or tool.description,
                        explanation=(
                            f"NOVA wants to run `{tool.name}`, which is marked “{tool.risk}”. "
                            "Review the payload and approve or reject."
                        ),
                        payload_json=json.dumps(args, default=str)[:10000],
                        risk="high" if tool.risk == "blocked" else "medium",
                    )
                    db.add(approval)
                    db.commit()
                    _append_event(
                        db, task, seq, "approval",
                        f"Waiting for approval: {step.get('label') or tool.name}",
                        {"tool": tool.name, "step": index, "approval_id": approval.id},
                    )
                step["status"] = "waiting_approval"
                task.status = "waiting_approval"
                task.progress = min(95, int(index / total * 100))
                task.current_step = step.get("label") or tool.name
                save_plan()
                if settings.worker_enabled:
                    try:
                        await notify_user(
                            db, user, "Approval needed",
                            (
                                f"{(step.get('label') or tool.name)[:120]}\n"
                                f"Task: {task.title[:120]}\n"
                                f"Approval ID: {approval.id}\n"
                                f"Or reply “approve {approval.id}” / “reject {approval.id}”."
                            ),
                            level="warning",
                            meta={"task_id": task.id, "approval_id": approval.id},
                            buttons=[
                                {"id": f"approve:{approval.id}", "title": "Approve"},
                                {"id": f"reject:{approval.id}", "title": "Reject"},
                            ],
                        )
                    except Exception:
                        pass
                return "waiting_approval"

            args = _resolve_args(step.get("args") or {}, state)
            step["status"] = "running"
            task.current_step = (step.get("label") or tool.description)[:300]
            task.progress = min(95, int(index / total * 100))
            save_plan()
            seq = _append_event(db, task, seq, "step", task.current_step, {"tool": tool.name, "args": args})

            def emit(event_type: str, message: str, data: Optional[Dict[str, Any]] = None, _s=seq) -> None:
                nonlocal seq
                seq = _append_event(db, task, seq, event_type, message, data or {})

            ctx = ToolContext(db=db, user=user, task=task, emit=emit, settings=settings)
            ctx.state = state  # type: ignore[attr-defined]

            result = None
            last_error = ""
            for attempt in range(2):
                try:
                    result = await tool.run(ctx, **args)
                    break
                except Exception as exc:  # noqa: BLE001 - tool failures are data, not crashes
                    last_error = f"{exc}"
                    emit("error", f"{tool.name} raised: {exc}", {"attempt": attempt + 1, "trace": traceback.format_exc()[-1200:]})
                if attempt == 0:
                    emit("retry", f"Retrying {tool.name} once", {})

            if result is None:
                step["status"] = "failed"
                step["error"] = last_error
                save_plan()
                task.status = "failed"
                task.error = f"{tool.name} failed: {last_error}"
                task.finished_at = utcnow()
                db.commit()
                emit("error", task.error, {})
                await _finalise_notification(db, user, task, failed=True)
                return "failed"

            step["verified"] = bool(result.verified)
            step["output"] = result.data
            state.update(result.data or {})
            ctx.state = state  # type: ignore[attr-defined]

            if result.setup_required:
                step["status"] = "blocked"
                step["error"] = result.summary
                save_plan()
                task.status = "failed"
                task.error = f"Setup required ({result.setup_required}): {result.summary}"
                task.finished_at = utcnow()
                db.commit()
                emit("error", task.error, {"setup_required": result.setup_required})
                await _finalise_notification(db, user, task, failed=True)
                return "failed"

            if not result.ok:
                step["status"] = "failed"
                step["error"] = result.summary
                save_plan()
                task.status = "failed"
                task.error = f"{tool.name}: {result.summary}"
                task.finished_at = utcnow()
                db.commit()
                emit("error", task.error, {})
                await _finalise_notification(db, user, task, failed=True)
                return "failed"

            step["status"] = "done"
            save_plan()
            for artifact in result.artifacts or []:
                enriched = dict(artifact)
                enriched.setdefault("step", index)
                artifacts.append(enriched)
            task.progress = min(99, int((index + 1) / total * 100))
            db.commit()
            emit("result", result.summary, {"tool": tool.name, "verified": result.verified, "step": index})

        verified_all = all(step.get("verified", True) for step in plan if step.get("status") == "done")
        task.status = "completed"
        task.progress = 100
        task.current_step = "Finished"
        task.finished_at = utcnow()
        task.attempts += 1
        task.result_json = json.dumps(
            {
                "summary": [step.get("output", {}).get("summary", "") for step in plan if step.get("output")],
                "artifacts": artifacts,
                "verified": verified_all,
                "steps": [
                    {"tool": s.get("tool"), "status": s.get("status"), "verified": s.get("verified", True)}
                    for s in plan
                ],
            },
            default=str,
        )[:100000]
        save_plan()
        db.commit()
        emit(
            "completed",
            "Task completed" + ("" if verified_all else " (some results could not be verified)"),
            {"verified": verified_all, "artifacts": len(artifacts)},
        )
        await _finalise_notification(db, user, task, failed=False)

        if task.recurrence in {"daily", "weekly"}:
            delta = timedelta(days=1 if task.recurrence == "daily" else 7)
            follow_up = Task(
                user_id=user.id,
                title=task.title,
                prompt=task.prompt,
                kind=task.kind,
                agent=task.agent,
                status="scheduled",
                scheduled_for=(task.scheduled_for or utcnow()) + delta,
                recurrence=task.recurrence,
                plan_json=json.dumps(
                    [{**step, "status": "pending", "approved": False} for step in plan]
                ),
                source=task.source,
                parent_id=task.id,
            )
            db.add(follow_up)
            db.commit()
        return "completed"
    finally:
        db.close()


async def _finalise_notification(db, user: User, task: Task, failed: bool) -> None:
    if not permissions.get_settings_map(db, user).get("notify_on_complete", True):
        return
    try:
        body = task.error if failed else _result_excerpt(task)
        await notify_user(
            db, user,
            "Task failed" if failed else "Task completed",
            f"{task.title}\n\n{body}"[:3500],
            level="error" if failed else "success",
            meta={"task_id": task.id},
        )
    except Exception:
        pass


def _result_excerpt(task: Task) -> str:
    try:
        data = json.loads(task.result_json or "{}")
    except json.JSONDecodeError:
        return "Result saved."
    lines = [line for line in data.get("summary", []) if line]
    return "\n".join(lines[-6:]) or "Result saved."

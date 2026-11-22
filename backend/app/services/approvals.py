"""Approval decisions — one implementation for every channel.

The dashboard and WhatsApp both call `decide()`, so an approval has identical
state transitions, task events and audit records regardless of where it was
approved. `parse_decision()` recognises the reply syntax used in chat.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import Approval, Task, TaskEvent, User, utcnow
from ..security import audit

# "approve a_1a2b3c", "reject a_123 — too risky", "APPROVE 1a2b3c4d"
DECISION_RE = re.compile(
    r"^\s*(approve|reject)(?:\s+(a_[0-9a-f]{3,16}|[0-9a-f]{6,16}))?\s*(?:[-–—:,]\s*(.*))?$",
    re.IGNORECASE,
)


@dataclass
class DecisionCommand:
    action: str  # "approve" | "reject"
    reference: str = ""
    note: str = ""


BUTTON_RE = re.compile(r"^(approve|reject)[:|](a_[0-9a-f]{3,16})$", re.IGNORECASE)


def parse_button_id(value: str) -> Optional[DecisionCommand]:
    """Decode an interactive button payload such as `approve:a_1a2b3c`."""
    match = BUTTON_RE.match((value or "").strip())
    if match is None:
        return None
    return DecisionCommand(action=match.group(1).lower(), reference=match.group(2).lower())


def parse_decision(text: str) -> Optional[DecisionCommand]:
    """Return the decision command if the message is an approval reply."""
    if not text:
        return None
    match = DECISION_RE.match(text.strip())
    if match is None:
        return None
    return DecisionCommand(
        action=match.group(1).lower(),
        reference=(match.group(2) or "").lower(),
        note=(match.group(3) or "").strip(),
    )


def find_pending(
    db: Session, user: User, reference: str
) -> Tuple[Optional[Approval], List[Approval]]:
    """Resolve an approval reference (full id or unique prefix) to one pending approval."""
    pending = (
        db.query(Approval)
        .filter(Approval.user_id == user.id, Approval.status == "pending")
        .order_by(Approval.created_at.desc())
        .all()
    )
    if not reference:
        return None, pending
    cleaned = reference if reference.startswith("a_") else f"a_{reference}"
    exact = [row for row in pending if row.id == cleaned]
    if exact:
        return exact[0], exact
    matches = [row for row in pending if row.id.startswith(cleaned)]
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def _load_plan(task: Task) -> List[dict]:
    try:
        plan = json.loads(task.plan_json or "[]")
    except json.JSONDecodeError:
        return []
    return plan if isinstance(plan, list) else []


def decide(
    db: Session,
    user: User,
    approval: Approval,
    approve: bool,
    note: str = "",
    actor: str = "web",
    ip: str = "",
) -> Tuple[Approval, Optional[Task]]:
    """Apply a decision and re-queue or cancel the owning task.

    Raises ValueError when the approval was already decided or belongs to
    another user; callers translate that into their own error shape.
    """
    if approval.user_id != user.id:
        raise ValueError("Approval not found")
    if approval.status != "pending":
        raise ValueError("This approval was already decided")

    approval.status = "approved" if approve else "rejected"
    approval.note = note[:2000]
    approval.decided_at = utcnow()
    task = db.get(Task, approval.task_id) if approval.task_id else None
    label = f"Approved via {actor}" if approve else f"Rejected via {actor}"

    if task is not None and task.user_id == user.id:
        plan = _load_plan(task)
        if approve:
            for step in plan:
                if step.get("tool") == approval.tool and step.get("status") == "waiting_approval":
                    step["approved"] = True
                    step["status"] = "pending"
                    break
            task.plan_json = json.dumps(plan)
            task.status = "queued"
            db.add(
                TaskEvent(
                    task_id=task.id,
                    seq=999_994,
                    type="approval",
                    message=f"{label}: {approval.action}"[:2000],
                )
            )
        else:
            for step in plan:
                if step.get("tool") == approval.tool:
                    step["status"] = "rejected"
            task.plan_json = json.dumps(plan)
            task.status = "cancelled"
            task.error = f"Rejected by you: {approval.action}"[:2000]
            task.finished_at = utcnow()
            db.add(
                TaskEvent(
                    task_id=task.id,
                    seq=999_993,
                    type="approval",
                    message=f"{label}: {approval.action}"[:2000],
                )
            )
    db.commit()

    audit(
        db,
        user.id,
        "approval.approve" if approve else "approval.reject",
        approval.id,
        ip=ip,
        actor=actor,
        data={
            "tool": approval.tool,
            "task_id": approval.task_id,
            "channel": actor,
            "note": note[:500],
        },
    )
    return approval, task

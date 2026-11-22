"""Desktop bridge tools.

NOVA never gets an unrestricted remote shell. Commands must be on the configured
allowlist, are queued as jobs, and execute only on a machine running the bridge
with the shared token.
"""
from __future__ import annotations

import re
from typing import Any

from ..config import settings
from ..models import DesktopJob
from .base import ToolContext, ToolResult, tool

SHELL_META = re.compile(r"[;&|`$><\n]")


@tool(
    name="desktop.run",
    description="Queue an allowlisted command for the local desktop agent (needs the bridge online). Requires approval.",
    category="desktop",
    params={
        "command": {"type": "string", "required": True},
        "cwd": {"type": "string", "required": False},
    },
    risk="blocked",
)
async def desktop_run(ctx: ToolContext, command: str, cwd: str = "") -> ToolResult:
    allowlist = settings.desktop_allowlist
    command = command.strip()
    if not allowlist:
        return ToolResult(False, "No desktop commands are allowlisted (DESKTOP_ALLOWED_COMMANDS).", verified=False)
    if SHELL_META.search(command):
        return ToolResult(
            False,
            "Refused: shell operators (;, &, |, $, >) are not allowed. Queue one plain command at a time.",
            verified=False,
        )
    if not any(command == allowed or command.startswith(allowed + " ") for allowed in allowlist):
        return ToolResult(
            False,
            f"Refused: “{command}” is not on the desktop allowlist ({', '.join(allowlist)}).",
            verified=False,
        )
    if not settings.desktop_bridge_token:
        return ToolResult(
            False,
            "Desktop bridge is not configured. Set DESKTOP_BRIDGE_TOKEN and run the bridge on the target machine.",
            verified=False,
            setup_required="desktop",
        )
    job = DesktopJob(
        user_id=ctx.user.id,
        task_id=ctx.task.id if ctx.task else None,
        command=command,
        cwd=cwd,
        status="queued",
    )
    ctx.db.add(job)
    ctx.db.commit()
    return ToolResult(
        True,
        f"Queued for the desktop agent: {command} (job {job.id})",
        {"job_id": job.id, "status": "queued"},
        verified=False,
    )


@tool(
    name="desktop.status",
    description="Check the result of a queued desktop job.",
    category="desktop",
    params={"job_id": {"type": "string", "required": True}},
)
async def desktop_status(ctx: ToolContext, job_id: str) -> ToolResult:
    job = ctx.db.get(DesktopJob, job_id)
    if job is None or job.user_id != ctx.user.id:
        return ToolResult(False, "Desktop job not found", verified=False)
    return ToolResult(
        job.status in {"done", "failed"},
        f"Job {job_id}: {job.status}",
        {"status": job.status, "output": job.output[-4000:], "exit_code": job.exit_code},
        verified=job.status == "done",
    )

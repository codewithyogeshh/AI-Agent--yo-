"""Tool contract + registry.

Every capability NOVA has is a Tool: described, permission-tagged, and executed
through one path so logging, approvals and verification cannot be bypassed.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from ..config import Settings, settings as global_settings
from ..models import Task, User


@dataclass
class ToolResult:
    ok: bool
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)
    verified: bool = True
    artifacts: List[Dict[str, str]] = field(default_factory=list)
    setup_required: str = ""


@dataclass
class ToolContext:
    db: Session
    user: User
    task: Optional[Task]
    emit: Callable[[str, str, Dict[str, Any]], None]
    settings: Settings = field(default_factory=lambda: global_settings)

    @property
    def user_dir(self) -> Path:
        """Absolute path so artifacts stay resolvable regardless of the process CWD."""
        path = (Path(self.settings.workspace_dir) / self.user.id).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


@dataclass
class Tool:
    name: str
    description: str
    category: str
    handler: Callable[..., Awaitable[ToolResult]]
    params: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    risk: str = "safe"  # safe | confirm | blocked
    requires: List[str] = field(default_factory=list)  # integration providers
    agents: List[str] = field(default_factory=list)

    def missing_params(self, args: Dict[str, Any]) -> List[str]:
        return [key for key, spec in self.params.items() if spec.get("required") and key not in args]

    def spec(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk": self.risk,
            "requires": self.requires,
            "params": self.params,
        }

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        missing = self.missing_params(kwargs)
        if missing:
            return ToolResult(False, f"Missing required parameters: {', '.join(missing)}", verified=False)
        result = self.handler(ctx, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ToolResult):
            return ToolResult(False, "Tool returned an invalid result", verified=False)
        return result


REGISTRY: Dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if tool.name in REGISTRY:
        raise ValueError(f"Duplicate tool: {tool.name}")
    REGISTRY[tool.name] = tool
    return tool


def tool(
    name: str,
    description: str,
    category: str,
    params: Optional[Dict[str, Dict[str, Any]]] = None,
    risk: str = "safe",
    requires: Optional[List[str]] = None,
    agents: Optional[List[str]] = None,
) -> Callable[[Callable[..., Awaitable[ToolResult]]], Callable[..., Awaitable[ToolResult]]]:
    def decorator(fn: Callable[..., Awaitable[ToolResult]]):
        register(
            Tool(
                name=name,
                description=description,
                category=category,
                handler=fn,
                params=params or {},
                risk=risk,
                requires=requires or [],
                agents=agents or [],
            )
        )
        return fn

    return decorator


def get_tool(name: str) -> Optional[Tool]:
    return REGISTRY.get(name)


def list_tools(category: Optional[str] = None) -> List[Tool]:
    tools = sorted(REGISTRY.values(), key=lambda t: t.name)
    return [t for t in tools if not category or t.category == category]


def catalog_text() -> str:
    lines = []
    for t in list_tools():
        params = ", ".join(
            f"{k}{'*' if v.get('required') else ''}:{v.get('type', 'string')}" for k, v in t.params.items()
        )
        lines.append(f"- {t.name}({params}) :: {t.description} [risk={t.risk}]")
    return "\n".join(lines)

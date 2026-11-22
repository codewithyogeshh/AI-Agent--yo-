"""Planner: natural language -> validated execution plan.

Two planners share one output contract:
  * LLM planner  — used when a provider key exists, constrained to the tool registry.
  * Offline planner — deterministic intent routing that still performs real work.
Both emit steps of {tool, args, label} so the executor is provider-agnostic.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..tools import catalog_text
from ..tools.base import REGISTRY
from . import llm


@dataclass
class Plan:
    title: str
    kind: str
    steps: List[Dict[str, Any]]
    planner: str
    notes: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> List[Dict[str, Any]]:
        return self.steps


PLAN_SCHEMA = {
    "title": "short task title",
    "kind": "research|content_video|youtube|instagram|email|calendar|reminder|tasks|files|code|report|general",
    "steps": [{"tool": "tool.name", "args": {"param": "value"}, "label": "what this step does"}],
}


INTENTS = [
    ("youtube_upload", ["upload", "publish"], ["youtube", "video"]),
    ("instagram", ["instagram", "reel", "carousel"], []),
    ("youtube", ["youtube", "short", "thumbnail", "channel"], []),
    ("content_video", ["video", "reel", "create a video", "generate video", "faceless"], []),
    ("email", ["email", "gmail", "inbox", "mail"], []),
    ("calendar", ["calendar", "meeting", "schedule a", "availability", "event"], []),
    ("reminder", ["remind", "reminder", "tomorrow at", "at 9", "wake me"], []),
    ("research", ["research", "find", "latest", "news", "compare", "summarize", "look up", "search"], []),
    ("tasks", ["my tasks", "today's tasks", "plan my day", "completed tasks", "weekly report", "task list"], []),
    ("files", ["file", "folder", "rename", "organize", "pdf", "document", "spreadsheet"], []),
    ("code", ["code", "bug", "test", "refactor", "repository", "script"], []),
    ("system", ["pause all", "stop all", "emergency", "status", "system"], []),
]


def detect_intent(text: str) -> str:
    lowered = text.lower()
    best, score = "general", 0
    for name, primary, secondary in INTENTS:
        hits = sum(2 for kw in primary if kw in lowered) + sum(1 for kw in secondary if kw in lowered)
        if hits > score:
            best, score = name, hits
    return best


def _title_from(prompt: str, limit: int = 80) -> str:
    cleaned = re.sub(r"\s+", " ", prompt).strip()
    return (cleaned[:limit] + "…") if len(cleaned) > limit else (cleaned or "New task")


# --------------------------------------------------------------------- offline
def offline_plan(prompt: str) -> Plan:
    intent = detect_intent(prompt)
    topic = _extract_topic(prompt)
    steps: List[Dict[str, Any]] = []

    if intent == "research":
        steps = [
            {"tool": "web.search", "args": {"query": topic, "limit": 6}, "label": f"Search the web for “{topic}”"},
            {"tool": "research.report", "args": {"topic": topic, "max_sources": 4}, "label": "Fetch sources and build a cited report"},
            {"tool": "memory.save", "args": {"title": f"Research: {topic}", "content": "Report stored in task artifacts.", "kind": "project", "tags": "research"}, "label": "Store the research in memory"},
        ]
    elif intent in {"content_video", "youtube", "instagram", "youtube_upload"}:
        platform = "instagram" if intent == "instagram" else "youtube"
        fmt = "vertical" if platform == "instagram" else "vertical"
        steps = [
            {"tool": "content.plan", "args": {"topic": topic, "platform": platform}, "label": "Build the content plan"},
            {"tool": "video.produce", "args": {"topic": topic, "platform": platform, "format": fmt, "duration": 60}, "label": "Produce the video package"},
            {"tool": "content.draft", "args": {"platform": platform, "kind": "short"}, "label": "Save script, caption and metadata as a draft"},
        ]
        if intent == "youtube_upload":
            steps.append({"tool": "youtube.upload", "args": {"content_id": "$content_id", "privacy": "private"}, "label": "Upload to YouTube (approval required)"})
        if intent == "instagram":
            steps.append({"tool": "instagram.publish", "args": {"content_id": "$content_id"}, "label": "Publish the Reel (approval required)"})
    elif intent == "email":
        if any(word in prompt.lower() for word in ["send", "reply", "draft"]):
            steps = [{"tool": "email.draft", "args": {"instruction": prompt}, "label": "Draft the email"}]
        else:
            steps = [
                {"tool": "email.list", "args": {"query": "is:unread", "limit": 10}, "label": "Read unread mail"},
                {"tool": "email.summarize", "args": {"query": "is:unread", "limit": 10}, "label": "Summarize what matters"},
            ]
    elif intent == "calendar":
        steps = [
            {"tool": "calendar.list", "args": {"days": 3}, "label": "Read the next 3 days"},
            {"tool": "calendar.suggest", "args": {"instruction": prompt}, "label": "Propose scheduling"},
        ]
    elif intent == "reminder":
        steps = [{"tool": "reminder.create", "args": {"instruction": prompt}, "label": "Create the reminder"}]
    elif intent == "tasks":
        steps = [
            {"tool": "tasks.report", "args": {"scope": "week" if "week" in prompt.lower() else "day"}, "label": "Compile the task report"},
        ]
    elif intent == "files":
        steps = [{"tool": "files.list", "args": {"path": ""}, "label": "Inspect the workspace"}]
    elif intent == "code":
        steps = [{"tool": "report.write", "args": {"title": "Coding task plan", "body": prompt}, "label": "Write a plan document"}]
    elif intent == "system":
        steps = [{"tool": "system.status", "args": {}, "label": "Check system status"}]
    else:
        steps = [
            {"tool": "memory.search", "args": {"query": prompt[:120]}, "label": "Check memory for context"},
            {"tool": "report.write", "args": {"title": _title_from(prompt), "body": prompt, "enrich": True}, "label": "Produce a structured response"},
        ]

    return Plan(
        title=_title_from(prompt),
        kind=intent,
        planner="offline",
        notes="Deterministic planner (no AI provider configured). Uses real tools; generative prose is unavailable.",
        steps=[
            {**step, "status": "pending", "index": index}
            for index, step in enumerate(steps)
        ],
    )


def _extract_topic(prompt: str) -> str:
    topic = re.sub(
        r"^(please\s+)?(can you\s+)?(find|research|create|make|generate|build|prepare|show me|upload)\s+",
        "",
        prompt.strip(),
        flags=re.I,
    )
    topic = re.sub(r"^(me\s+)?(the\s+)?", "", topic, flags=re.I)
    topic = re.sub(r"\b(and\s+send\s+me\s+a\s+summary|for me|please)\b", "", topic, flags=re.I)
    return topic.strip(" .") or prompt.strip()[:80]


# --------------------------------------------------------------------- LLM plan
async def llm_plan(prompt: str, context_hint: str = "") -> Optional[Plan]:
    result = await llm.complete_optional(
        (
            "Create an execution plan for the user request using ONLY the tools below.\n"
            "Rules: prefer the minimum number of steps; use setup-gated tools only when the request truly needs them; "
            "never invent tool names; args must be JSON values; use $content_id to reference the content item created earlier.\n\n"
            f"TOOLS:\n{catalog_text()}\n\n"
            f"Known user context:\n{context_hint or '(none)'}\n\n"
            f"USER REQUEST:\n{prompt}\n\n"
            f"Return JSON exactly shaped like: {json.dumps(PLAN_SCHEMA)}"
        ),
        system="You are a precise task planner. Output JSON only.",
        json_mode=True,
        temperature=0.2,
    )
    if result is None:
        return None
    data = result.json()
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        return None

    steps: List[Dict[str, Any]] = []
    for index, raw in enumerate(data["steps"][:12]):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("tool", "")).strip()
        if name not in REGISTRY:
            continue
        args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        steps.append(
            {
                "tool": name,
                "args": args,
                "label": str(raw.get("label") or REGISTRY[name].description)[:300],
                "status": "pending",
                "index": index,
            }
        )
    if not steps:
        return None
    return Plan(
        title=str(data.get("title") or _title_from(prompt))[:120],
        kind=str(data.get("kind") or detect_intent(prompt))[:32],
        steps=steps,
        planner=f"llm:{result.provider}",
        notes=f"Planned by {result.provider} ({result.model}).",
    )


async def make_plan(prompt: str, context_hint: str = "") -> Plan:
    plan = await llm_plan(prompt, context_hint)
    return plan or offline_plan(prompt)

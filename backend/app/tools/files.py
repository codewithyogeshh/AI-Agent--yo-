"""File tools — sandboxed to the user's workspace directory.

No tool here can escape `<workspace>/<user_id>`. Path traversal is rejected.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from ..models import MediaAsset
from .base import ToolContext, ToolResult, tool

MAX_READ_BYTES = 400_000
TEXT_SUFFIXES = {".md", ".txt", ".json", ".csv", ".srt", ".py", ".ts", ".tsx", ".js", ".yml", ".yaml", ".html", ".svg"}


def safe_path(ctx: ToolContext, relative: str) -> Path:
    base = ctx.user_dir.resolve()
    candidate = (base / (relative or "")).resolve()
    if base != candidate and base not in candidate.parents:
        raise ValueError("Path escapes the sandboxed workspace")
    return candidate


@tool(
    name="files.list",
    description="List files and folders inside the NOVA workspace.",
    category="files",
    params={"path": {"type": "string", "required": False}},
)
async def files_list(ctx: ToolContext, path: str = "") -> ToolResult:
    target = safe_path(ctx, path)
    if not target.exists():
        return ToolResult(True, "Folder is empty (nothing created yet).", {"path": path, "entries": []})
    if not target.is_dir():
        return ToolResult(False, f"{path} is not a directory", verified=False)
    entries: List[Dict[str, object]] = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))[:300]:
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "path": str(child.relative_to(ctx.user_dir)),
                "type": "dir" if child.is_dir() else "file",
                "size": stat.st_size,
                "modified": datetime.utcfromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            }
        )
    return ToolResult(True, f"{len(entries)} entries in /{path}", {"path": path, "entries": entries})


@tool(
    name="files.read",
    description="Read a text document from the workspace (returns a truncated preview for large files).",
    category="files",
    params={"path": {"type": "string", "required": True}},
)
async def files_read(ctx: ToolContext, path: str) -> ToolResult:
    target = safe_path(ctx, path)
    if not target.is_file():
        return ToolResult(False, f"File not found: {path}", verified=False)
    if target.stat().st_size > MAX_READ_BYTES:
        return ToolResult(False, "File is too large to read inline (>400 KB)", verified=False)
    if target.suffix.lower() not in TEXT_SUFFIXES:
        return ToolResult(False, f"Unsupported preview type: {target.suffix or 'unknown'}", verified=False)
    return ToolResult(True, f"Read {target.name}", {"path": path, "content": target.read_text(encoding="utf-8", errors="replace")})


@tool(
    name="files.write",
    description="Write a text or markdown document into the workspace.",
    category="files",
    params={
        "path": {"type": "string", "required": True, "description": "Relative path, e.g. notes/plan.md"},
        "content": {"type": "string", "required": True},
    },
)
async def files_write(ctx: ToolContext, path: str, content: str) -> ToolResult:
    target = safe_path(ctx, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    ctx.db.add(
        MediaAsset(
            user_id=ctx.user.id,
            name=target.name,
            path=str(target),
            mime="text/markdown" if target.suffix == ".md" else "text/plain",
            size=target.stat().st_size,
            kind="document",
            meta_json="{}",
        )
    )
    ctx.db.commit()
    return ToolResult(True, f"Wrote {target.name} ({target.stat().st_size} bytes)", {"path": str(target.relative_to(ctx.user_dir))})


@tool(
    name="files.organize",
    description="Move files into folders by extension inside the workspace.",
    category="files",
    params={"path": {"type": "string", "required": False, "description": "Folder to organize (default root)"}},
    risk="confirm",
)
async def files_organize(ctx: ToolContext, path: str = "") -> ToolResult:
    target = safe_path(ctx, path)
    if not target.is_dir():
        return ToolResult(False, "Target folder does not exist", verified=False)
    mapping = {
        ".mp4": "video", ".mov": "video", ".mp3": "audio", ".wav": "audio",
        ".png": "images", ".jpg": "images", ".jpeg": "images", ".webp": "images", ".svg": "images",
        ".md": "documents", ".txt": "documents", ".pdf": "documents", ".csv": "documents",
    }
    moved = 0
    for item in list(target.iterdir()):
        if not item.is_file():
            continue
        bucket = mapping.get(item.suffix.lower())
        if not bucket:
            continue
        dest_dir = target / bucket
        dest_dir.mkdir(exist_ok=True)
        shutil.move(str(item), str(dest_dir / item.name))
        moved += 1
    return ToolResult(True, f"Moved {moved} files into categorized folders", {"moved": moved})


@tool(
    name="report.write",
    description="Write a structured markdown report to the workspace, optionally enriched by the AI provider.",
    category="files",
    params={
        "title": {"type": "string", "required": True},
        "body": {"type": "string", "required": True},
        "enrich": {"type": "boolean", "required": False},
    },
)
async def report_write(ctx: ToolContext, title: str, body: str, enrich: bool = False) -> ToolResult:
    from ..agent import llm

    content = body
    note = "Draft only — no AI provider configured, content is your original request."
    if enrich and llm.active_provider():
        result = await llm.complete_optional(
            f"Turn this request into a clear, actionable working document titled '{title}'. "
            f"Use headings, concrete steps and note any information you cannot verify.\n\nREQUEST:\n{body}",
            max_tokens=1500,
        )
        if result is not None:
            content = result.text
            note = f"Written by {result.provider} ({result.model})."
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:46].strip("-") or "document"
    path = ctx.user_dir / "documents" / f"{datetime.utcnow():%Y%m%d-%H%M%S}-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{content}\n\n---\n_{note}_\n", encoding="utf-8")
    return ToolResult(
        True,
        f"Document saved: {path.name}",
        {"path": str(path), "note": note},
        artifacts=[{"kind": "document", "title": title, "path": str(path)}],
    )

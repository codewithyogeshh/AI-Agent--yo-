"""Content production tools: planning, video production, drafting, publishing.

The video pipeline really renders files. Every stage records what it produced so
the dashboard can link to artefacts instead of describing them.
"""
from __future__ import annotations

import asyncio
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..agent import llm
from ..models import ContentItem
from ..services import media
from .base import ToolContext, ToolResult, tool


def _slug(text: str, limit: int = 48) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower())[:limit].strip("-") or "content"


def _offline_scenes(topic: str, duration: int) -> List[Dict[str, Any]]:
    """Deterministic scene skeleton used when no AI provider is configured.

    It is a real, usable production structure — not generated prose, and it says so.
    """
    beats = [
        ("Hook", f"{topic}", "Open with the single most surprising fact about this topic."),
        ("Why it matters", f"Context around {topic}", "Frame the problem this topic solves for the viewer."),
        ("Core idea", f"How {topic} actually works", "Explain the mechanism in plain language with one analogy."),
        ("Example", f"A concrete example", "Walk through one specific, verifiable example."),
        ("Action", f"What to do next", "Give the viewer one action they can take today."),
    ]
    per = max(4, duration // len(beats))
    scenes = []
    for index, (heading, narration, note) in enumerate(beats):
        scenes.append(
            {
                "index": index,
                "heading": heading,
                "narration": narration,
                "visual": note,
                "seconds": per,
            }
        )
    return scenes


def _normalise_scenes(raw: Any, topic: str, duration: int) -> List[Dict[str, Any]]:
    scenes: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            scenes.append(
                {
                    "index": index,
                    "heading": str(item.get("heading") or item.get("title") or f"Scene {index + 1}")[:80],
                    "narration": str(item.get("narration") or item.get("text") or "")[:1200],
                    "visual": str(item.get("visual") or item.get("visual_prompt") or "")[:400],
                    "seconds": float(item.get("seconds") or 0) or 0,
                }
            )
    return [s for s in scenes if s["narration"]] or _offline_scenes(topic, duration)


def _split_script(script: str, topic: str, duration: int) -> List[Dict[str, Any]]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", script) if p.strip()]
    if len(paragraphs) < 2:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
        paragraphs = [" ".join(sentences[i : i + 2]) for i in range(0, len(sentences), 2)]
    if not paragraphs:
        return _offline_scenes(topic, duration)
    total_words = sum(len(p.split()) for p in paragraphs) or 1
    scenes = []
    for index, paragraph in enumerate(paragraphs[:12]):
        scenes.append(
            {
                "index": index,
                "heading": f"Part {index + 1}",
                "narration": paragraph,
                "visual": "Supporting visual or b-roll for this beat.",
                "seconds": max(3.0, duration * len(paragraph.split()) / total_words),
            }
        )
    return scenes


def _render_package(
    work: Path,
    scenes: List[Dict[str, Any]],
    durations: List[float],
    size: Tuple[int, int],
    voiceover: str | None,
    srt_path: Path,
    video_path: Path,
    thumb_path: Path,
    thumbnail_title: str,
    thumbnail_subtitle: str,
) -> Tuple[bool, List[str]]:
    """Blocking ffmpeg work — always called through asyncio.to_thread so the API stays responsive."""
    notes: List[str] = []
    caps = media.capabilities()
    if not caps["ffmpeg"]:
        return False, ["ffmpeg unavailable: rendered production package only (script, scenes, subtitles)."]
    if not caps["font"]:
        return False, ["No font available: visual render skipped, package complete."]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        parts: List[Path] = []
        for index, scene in enumerate(scenes):
            part = tmp_dir / f"scene-{index:02d}.mp4"
            ok, log = media.render_scene(part, scene["heading"], scene["narration"], durations[index], size, tmp_dir)
            if not ok:
                notes.append(f"Scene {index + 1} render failed: {log[:200]}")
                break
            parts.append(part)
        if len(parts) == len(scenes) and parts:
            joined = tmp_dir / "joined.mp4"
            ok, log = media.concat_videos(parts, joined)
            if not ok:
                notes.append(f"Concat failed: {log[:200]}")
            else:
                final_audio = voiceover
                if not final_audio:
                    silent = tmp_dir / "silent.m4a"
                    ok_a, _ = media.silent_audio(silent, sum(durations))
                    final_audio = str(silent) if ok_a else None
                ok, log = media.finalise(joined, srt_path, final_audio, video_path, size)
                if not ok:
                    notes.append(f"Final encode failed: {log[:300]}")

    thumb_size = (1080, 1920) if size[1] > size[0] else (1280, 720)
    with tempfile.TemporaryDirectory() as tmp:
        ok_thumb, thumb_log = media.make_thumbnail(thumb_path, thumbnail_title, thumbnail_subtitle, thumb_size, Path(tmp))
    if not ok_thumb:
        notes.append(f"Thumbnail skipped: {thumb_log[:160]}")

    rendered = video_path.exists() and video_path.stat().st_size > 10_000
    return rendered, notes


@tool(
    name="content.plan",
    description="Produce a content plan: idea, hook, audience, format, scenes and CTA for YouTube or Instagram.",
    category="content",
    params={
        "topic": {"type": "string", "required": True},
        "platform": {"type": "string", "required": False, "description": "youtube | instagram"},
        "format": {"type": "string", "required": False, "description": "short | long | reel"},
    },
)
async def content_plan(ctx: ToolContext, topic: str, platform: str = "youtube", format: str = "short") -> ToolResult:
    ctx.emit("tool", f"Planning {platform} content on “{topic}”", {"platform": platform})
    plan: Dict[str, Any] = {}
    note = "Offline structural plan (no AI provider configured)."
    if llm.active_provider():
        result = await llm.complete_optional(
            (
                f"Create a {platform} {format} content plan about: {topic}\n"
                "Return JSON with keys: title, hook, audience, format, duration_seconds, cta, "
                "keywords (array), scenes (array of {heading, narration, visual, seconds}). "
                "Narration must be spoken-word natural and factually careful — no invented statistics."
            ),
            json_mode=True,
            temperature=0.6,
            max_tokens=1800,
        )
        if result is not None:
            data = result.json()
            if isinstance(data, dict):
                plan = data
                note = f"Planned by {result.provider} ({result.model})."
    if not plan:
        plan = {
            "title": topic[:90],
            "hook": f"A 15-second opener that states why {topic} matters right now.",
            "audience": "Curious learners and builders following this niche.",
            "format": format,
            "duration_seconds": 60 if format in {"short", "reel"} else 480,
            "cta": "Subscribe / follow for the next breakdown.",
            "keywords": [topic],
            "scenes": _offline_scenes(topic, 60),
        }
    ctx.state["content_plan"] = plan
    ctx.state["topic"] = topic
    ctx.state["platform"] = platform
    return ToolResult(
        True,
        f"Plan ready: {plan.get('title', topic)[:80]}",
        {"plan": plan, "note": note},
        artifacts=[{"kind": "plan", "title": f"{platform} plan: {topic}"}],
    )


@tool(
    name="video.produce",
    description="Render a real MP4 with scenes, subtitles and optional voiceover, plus thumbnail and metadata.",
    category="media",
    params={
        "topic": {"type": "string", "required": True},
        "platform": {"type": "string", "required": False},
        "format": {"type": "string", "required": False, "description": "vertical | landscape | square"},
        "duration": {"type": "integer", "required": False, "description": "Target seconds"},
        "script": {"type": "string", "required": False, "description": "Optional full narration script"},
    },
)
async def video_produce(
    ctx: ToolContext, topic: str, platform: str = "youtube", format: str = "vertical", duration: int = 60, script: str = ""
) -> ToolResult:
    duration = max(15, min(int(duration or 60), 900))
    work = ctx.user_dir / "content" / f"{datetime.utcnow():%Y%m%d-%H%M%S}-{_slug(topic)}"
    work.mkdir(parents=True, exist_ok=True)
    caps = media.capabilities()
    notes: List[str] = []

    # 1 — script
    if not script:
        if llm.active_provider():
            ctx.emit("progress", "Writing the script", {"stage": "script"})
            result = await llm.complete_optional(
                (
                    f"Write a {duration}-second spoken narration script for a {platform} {format} video about: {topic}\n"
                    "Rules: no stage directions, no markdown headings; 1-3 short paragraphs separated by blank lines; "
                    "hook in the first sentence; end with a call to action. Only verifiable claims."
                ),
                temperature=0.7,
                max_tokens=1500,
            )
            if result is not None:
                script = result.text.strip()
                notes.append(f"Script written by {result.provider}.")
        if not script:
            plan = ctx.state.get("content_plan") or {}
            if plan.get("scenes"):
                script = "\n\n".join(str(s.get("narration", "")) for s in plan["scenes"] if s.get("narration"))
            if not script:
                script = "\n\n".join(s["narration"] for s in _offline_scenes(topic, duration))
            notes.append("Offline mode: structural narration only, no generative script.")

    # 2 — scenes
    scenes = _split_script(script, topic, duration)
    (work / "script.md").write_text(f"# {topic}\n\n{script}\n", encoding="utf-8")
    (work / "scenes.json").write_text(json.dumps(scenes, indent=2), encoding="utf-8")

    # 3 — voiceover
    voiceover: str | None = None
    ctx.emit("progress", "Generating voiceover", {"stage": "tts"})
    audio, tts_note = await media.text_to_speech(script, work / "voiceover.mp3")
    notes.append(tts_note)
    voiceover = audio

    # 4 — durations + subtitles
    if voiceover:
        audio_duration = media.probe_duration(voiceover)
        if audio_duration > 0:
            weights = [max(1, len(s["narration"])) for s in scenes]
            total_weight = sum(weights)
            for scene, weight in zip(scenes, weights):
                scene["seconds"] = max(2.0, audio_duration * weight / total_weight)
            duration = int(duration)
    durations = [float(s.get("seconds") or duration / len(scenes)) for s in scenes]
    total_duration = sum(durations)
    srt_path = work / "captions.srt"
    srt_path.write_text(media.build_srt(scenes, durations), encoding="utf-8")

    # 5 + 6 — render video and thumbnail off the event loop
    video_path = work / "final.mp4"
    thumb_path = work / "thumbnail.png"
    size = media.size_for(format)
    ctx.emit("progress", "Rendering scenes", {"stage": "render", "scenes": len(scenes)})
    rendered, render_notes = await asyncio.to_thread(
        _render_package,
        work,
        scenes,
        durations,
        size,
        voiceover,
        srt_path,
        video_path,
        thumb_path,
        topic,
        f"{platform.upper()} · {round(total_duration)}s",
    )
    notes.extend(render_notes)

    # 7 — metadata + draft record
    metadata = {
        "title": topic[:95],
        "description": f"{topic}\n\n{script[:400]}\n\n#{(ctx.state.get('content_plan') or {}).get('keywords', [topic])[0]}",
        "tags": (ctx.state.get("content_plan") or {}).get("keywords", [topic]),
        "format": format,
        "platform": platform,
        "duration_seconds": round(total_duration, 1),
        "voiceover": bool(voiceover),
        "rendered": rendered,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "notes": notes,
    }
    (work / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    item = ContentItem(
        user_id=ctx.user.id,
        platform=platform,
        kind="short" if format in {"vertical", "reel"} else "video",
        title=topic[:250],
        status="rendered" if rendered else "draft",
        hook=(ctx.state.get("content_plan") or {}).get("hook", ""),
        script=script,
        caption=f"{topic}\n\n{(ctx.state.get('content_plan') or {}).get('cta', '')}",
        hashtags=" ".join(f"#{re.sub(r'[^A-Za-z0-9]', '', k)}" for k in metadata["tags"][:6]),
        description=metadata["description"],
        metadata_json=json.dumps(metadata),
        asset_path=str(video_path) if rendered else "",
        thumb_path=str(thumb_path) if thumb_path.exists() else "",
        task_id=ctx.task.id if ctx.task else None,
    )
    ctx.db.add(item)
    ctx.db.commit()
    ctx.state["content_id"] = item.id
    ctx.state["production"] = {"dir": str(work), "metadata": metadata, "srt": str(srt_path), "script": script}

    artifacts = [
        {"kind": "file", "title": "Script", "path": str(work / "script.md")},
        {"kind": "file", "title": "Subtitles", "path": str(srt_path)},
        {"kind": "file", "title": "Metadata", "path": str(work / "metadata.json")},
    ]
    if rendered:
        artifacts.append({"kind": "video", "title": topic[:60], "path": str(video_path)})
    if thumb_path.exists():
        artifacts.append({"kind": "image", "title": "Thumbnail", "path": str(thumb_path)})

    summary = (
        f"Video rendered ({round(total_duration)}s, {size[0]}x{size[1]}) · content {item.id}"
        if rendered
        else f"Production package created in {work.name} — {notes[-1] if notes else 'render unavailable'}"
    )
    ctx.emit("progress", "Video production finished" if rendered else "Production package finished", {"rendered": rendered})
    return ToolResult(True, summary, {"content_id": item.id, "dir": str(work), "metadata": metadata, "notes": notes}, verified=rendered or thumb_path.exists(), artifacts=artifacts)


@tool(
    name="content.draft",
    description="Create or finalise a content draft (script, caption, hashtags, metadata) in the content library.",
    category="content",
    params={
        "platform": {"type": "string", "required": False},
        "kind": {"type": "string", "required": False},
        "title": {"type": "string", "required": False},
        "caption": {"type": "string", "required": False},
    },
)
async def content_draft(
    ctx: ToolContext, platform: str = "", kind: str = "", title: str = "", caption: str = ""
) -> ToolResult:
    content_id = ctx.state.get("content_id")
    item = ctx.db.get(ContentItem, content_id) if content_id else None
    if item is None:
        production = ctx.state.get("production") or {}
        plan = ctx.state.get("content_plan") or {}
        item = ContentItem(
            user_id=ctx.user.id,
            platform=platform or ctx.state.get("platform", "youtube"),
            kind=kind or "short",
            title=title or plan.get("title") or ctx.state.get("topic", "Draft")[:250],
            caption=caption or plan.get("hook", ""),
            script=production.get("script", ""),
            description=(production.get("metadata") or {}).get("description", ""),
            hashtags=" ".join(f"#{re.sub(r'[^A-Za-z0-9]', '', k)}" for k in plan.get("keywords", [])[:6]),
            metadata_json=json.dumps(plan),
            task_id=ctx.task.id if ctx.task else None,
        )
        ctx.db.add(item)
        ctx.db.commit()
        ctx.state["content_id"] = item.id
    elif caption:
        item.caption = caption
        item.updated_at = datetime.utcnow()
        ctx.db.commit()
    return ToolResult(
        True,
        f"Draft saved: {item.title[:70]} ({item.platform}, {item.status})",
        {"content_id": item.id, "platform": item.platform, "status": item.status},
        artifacts=[{"kind": "content", "title": item.title, "content_id": item.id}],
    )


@tool(
    name="content.calendar",
    description="Schedule a content item for publication and move it to 'scheduled'.",
    category="content",
    params={"content_id": {"type": "string", "required": True}, "when": {"type": "string", "required": True}},
    risk="confirm",
)
async def content_calendar(ctx: ToolContext, content_id: str, when: str) -> ToolResult:
    item = ctx.db.get(ContentItem, content_id)
    if item is None or item.user_id != ctx.user.id:
        return ToolResult(False, "Content item not found", verified=False)
    try:
        when_dt = datetime.fromisoformat(when.replace("Z", ""))
    except ValueError:
        return ToolResult(False, f"Could not parse date/time: {when}", verified=False)
    item.scheduled_for = when_dt
    item.status = "scheduled"
    ctx.db.commit()
    return ToolResult(True, f"Scheduled “{item.title[:60]}” for {when_dt.isoformat(timespec='minutes')}", {"content_id": item.id})

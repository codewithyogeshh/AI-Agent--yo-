"""Real media pipeline: scene rendering, subtitle burn-in, TTS, thumbnails.

Uses ffmpeg (system binary or the static one shipped with imageio-ffmpeg).
Every capability is probed at runtime; when something is missing the caller is
told exactly what, instead of getting a fake success.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from ..config import settings

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONT_DIR = ASSETS / "fonts"


def ffmpeg_path() -> Optional[str]:
    if settings.ffmpeg_path and shutil.which(settings.ffmpeg_path):
        return shutil.which(settings.ffmpeg_path)
    if settings.ffmpeg_path and Path(settings.ffmpeg_path).exists():
        return settings.ffmpeg_path
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def font_path() -> Optional[str]:
    configured = ASSETS / "fonts" / "Inter-Regular.ttf"
    if configured.exists():
        return str(configured)
    candidates = sorted(FONT_DIR.glob("*.ttf")) + sorted(FONT_DIR.glob("*.otf"))
    return str(candidates[0]) if candidates else None


def capabilities() -> Dict[str, object]:
    return {
        "ffmpeg": bool(ffmpeg_path()),
        "ffmpeg_binary": ffmpeg_path() or "",
        "font": font_path() or "",
        "tts": bool(settings.elevenlabs_api_key or settings.openai_api_key),
        "ai_images": bool(settings.openai_api_key),
    }


@dataclass
class RenderResult:
    ok: bool
    path: str = ""
    log: str = ""
    duration: float = 0.0


def run_ffmpeg(args: List[str], timeout: int = 300) -> Tuple[bool, str]:
    binary = ffmpeg_path()
    if not binary:
        return False, "ffmpeg is not available"
    try:
        proc = subprocess.run(
            [binary, "-hide_banner", "-loglevel", "error", "-y", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "ffmpeg timed out"
    return proc.returncode == 0, (proc.stderr or "").strip()[-4000:]


def probe_duration(path: str) -> float:
    binary = ffmpeg_path()
    if not binary:
        return 0.0
    try:
        proc = subprocess.run([binary, "-hide_banner", "-i", path], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return 0.0
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr or "")
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt(scenes: List[Dict], durations: List[float]) -> str:
    lines: List[str] = []
    cursor = 0.0
    for index, scene in enumerate(scenes, start=1):
        duration = durations[index - 1]
        text = str(scene.get("narration") or scene.get("heading") or "").strip()
        wrapped = "\n".join(textwrap.wrap(text, 42)) or " "
        lines.append(f"{index}\n{_timestamp(cursor)} --> {_timestamp(cursor + duration)}\n{wrapped}\n")
        cursor += duration
    return "\n".join(lines)


def wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(re.sub(r"\s+", " ", text).strip(), width)) or " "


def render_scene(
    out_path: Path,
    heading: str,
    body: str,
    duration: float,
    size: Tuple[int, int],
    workdir: Path,
    accent: str = "0x38BDF8",
) -> Tuple[bool, str]:
    width, height = size
    font = font_path()
    if not font:
        return False, "No font file available for text rendering (expected backend/app/assets/fonts/Inter-Regular.ttf)"
    heading_file = workdir / f"{out_path.stem}-heading.txt"
    body_file = workdir / f"{out_path.stem}-body.txt"
    heading_file.write_text(wrap(heading.upper(), 30 if width < height else 48), encoding="utf-8")
    body_file.write_text(wrap(body, 30 if width < height else 52), encoding="utf-8")
    title_size = int(height * 0.042) if width < height else int(height * 0.062)
    body_size = int(height * 0.028) if width < height else int(height * 0.04)

    filters = [
        f"drawbox=x=0:y=0:w=iw:h=ih:color=0x0B1220:t=fill",
        f"drawbox=x=0:y=0:w=iw:h={max(4, int(height * 0.006))}:color={accent}@0.9:t=fill",
        (
            f"drawtext=fontfile='{font}':textfile='{heading_file}':fontcolor=0xE2E8F0:fontsize={title_size}:"
            f"line_spacing={int(title_size * 0.35)}:x=(w-text_w)/2:y={int(height * (0.16 if width < height else 0.14))}"
        ),
        (
            f"drawtext=fontfile='{font}':textfile='{body_file}':fontcolor=0x94A3B8:fontsize={body_size}:"
            f"line_spacing={int(body_size * 0.5)}:x=(w-text_w)/2:y={int(height * 0.42)}"
        ),
    ]
    args = [
        "-f", "lavfi",
        "-i", f"color=c=0x0B1220:s={width}x{height}:d={max(1.0, duration):.2f}:r=25",
        "-vf", ",".join(filters),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "stillimage",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]
    return run_ffmpeg(args, timeout=180)


def concat_videos(parts: List[Path], out_path: Path) -> Tuple[bool, str]:
    if not parts:
        return False, "No scene videos to concatenate"
    listing = out_path.parent / "concat.txt"
    listing.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
    return run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out_path)], timeout=180)


def finalise(video: Path, srt: Optional[Path], audio: Optional[Path], out_path: Path, size: Tuple[int, int]) -> Tuple[bool, str]:
    binary = ffmpeg_path()
    if not binary:
        return False, "ffmpeg is not available"
    args: List[str] = ["-i", str(video)]
    has_audio = bool(audio and Path(audio).exists())
    if has_audio:
        args += ["-i", str(audio)]
    use_subs = bool(srt and srt.exists() and font_path())
    if use_subs:
        style = (
            "FontName=Inter,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,"
            "BorderStyle=3,Outline=1,Shadow=0,Alignment=2,MarginV=60"
        )
        subs = f"subtitles='{srt.as_posix()}':fontsdir='{FONT_DIR.as_posix()}':force_style='{style}'"
        args += ["-vf", subs]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p"]
    if has_audio:
        args += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    args += ["-movflags", "+faststart", str(out_path)]
    return run_ffmpeg(args, timeout=600)


def make_thumbnail(out_path: Path, title: str, subtitle: str, size: Tuple[int, int], workdir: Path) -> Tuple[bool, str]:
    font = font_path()
    if not font:
        return False, "No font file available for thumbnail rendering"
    width, height = size
    title_file = workdir / "thumb-title.txt"
    sub_file = workdir / "thumb-sub.txt"
    title_file.write_text(wrap(title.upper(), 22), encoding="utf-8")
    sub_file.write_text(wrap(subtitle, 34), encoding="utf-8")
    filters = [
        "drawbox=x=0:y=0:w=iw:h=ih:color=0x0B1220:t=fill",
        f"drawbox=x=0:y={int(height * 0.72)}:w={width}:h={int(height * 0.28)}:color=0x0F172A:t=fill",
        f"drawbox=x={int(width * 0.06)}:y={int(height * 0.1)}:w={int(width * 0.03)}:h={int(height * 0.5)}:color=0x38BDF8:t=fill",
        (
            f"drawtext=fontfile='{font}':textfile='{title_file}':fontcolor=0xF8FAFC:fontsize={int(height * 0.1)}:"
            f"line_spacing={int(height * 0.02)}:x={int(width * 0.12)}:y={int(height * 0.12)}"
        ),
        (
            f"drawtext=fontfile='{font}':textfile='{sub_file}':fontcolor=0x38BDF8:fontsize={int(height * 0.045)}:"
            f"x={int(width * 0.06)}:y={int(height * 0.79)}"
        ),
    ]
    args = [
        "-f", "lavfi", "-i", f"color=c=0x0B1220:s={width}x{height}:d=1",
        "-vf", ",".join(filters), "-frames:v", "1", "-pix_fmt", "rgb24", str(out_path),
    ]
    return run_ffmpeg(args, timeout=90)


async def text_to_speech(text: str, out_path: Path) -> Tuple[Optional[str], str]:
    """Return (audio path, note). Falls back to silent audio handled by caller."""
    if settings.elevenlabs_api_key and settings.elevenlabs_voice_id:
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                res = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
                    headers={"xi-api-key": settings.elevenlabs_api_key, "accept": "audio/mpeg"},
                    json={"text": text[:4500], "model_id": "eleven_multilingual_v2"},
                )
                if res.status_code < 400:
                    out_path.write_bytes(res.content)
                    return str(out_path), "Voiceover generated with ElevenLabs."
                return None, f"ElevenLabs error {res.status_code}: {res.text[:200]}"
        except Exception as exc:
            return None, f"ElevenLabs request failed: {exc}"
    if settings.openai_api_key:
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                res = await client.post(
                    f"{settings.openai_base_url.rstrip('/')}/audio/speech",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json={
                        "model": "gpt-4o-mini-tts",
                        "voice": settings.openai_tts_voice,
                        "input": text[:4000],
                        "response_format": "mp3",
                    },
                )
                if res.status_code < 400:
                    out_path.write_bytes(res.content)
                    return str(out_path), "Voiceover generated with OpenAI TTS."
                return None, f"OpenAI TTS error {res.status_code}: {res.text[:200]}"
        except Exception as exc:
            return None, f"OpenAI TTS failed: {exc}"
    return None, "No TTS provider configured — video rendered with a silent audio track."


def silent_audio(out_path: Path, seconds: float) -> Tuple[bool, str]:
    return run_ffmpeg(
        ["-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100", "-t", f"{max(1.0, seconds):.2f}",
         "-c:a", "aac", "-b:a", "128k", str(out_path)],
        timeout=120,
    )


def size_for(fmt: str) -> Tuple[int, int]:
    if fmt in {"vertical", "reel", "short"}:
        return (1080, 1920) if fmt != "short" else (1080, 1920)
    if fmt == "square":
        return (1080, 1080)
    return (1920, 1080)

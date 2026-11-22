"""Generate PWA icons with the standard library only (no Pillow needed).

Draws the NOVA mark: a dark rounded tile with a cyan nova ring and core.
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "icons"


def blend(base, top, alpha):
    return tuple(int(b * (1 - alpha) + t * alpha) for b, t in zip(base, top))


def render(size: int, maskable: bool = False) -> bytearray:
    bg = (7, 11, 20)
    deep = (12, 20, 36)
    accent = (56, 189, 248)
    soft = (125, 211, 252)
    white = (240, 249, 255)
    pixels = bytearray(size * size * 4)
    cx = cy = (size - 1) / 2
    scale = 0.78 if maskable else 0.92
    radius = size / 2 * scale
    ring_inner = radius * 0.60
    ring_outer = radius * 0.72

    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            nx = (x - cx) / radius
            ny = (y - cy) / radius
            dist = math.hypot(nx, ny)
            angle = math.atan2(ny, nx)

            # Tile background: subtle vertical gradient with a radial lift.
            t = y / max(1, size - 1)
            color = blend(bg, deep, t * 0.85)
            glow = max(0.0, 1.0 - dist / 1.05) ** 2
            color = blend(color, (10, 30, 52), glow * 0.55)

            # Nova ring with soft falloff.
            if ring_inner <= dist <= ring_outer:
                edge = min(dist - ring_inner, ring_outer - dist)
                alpha = min(1.0, 0.35 + edge / (radius * 0.05)) if edge < radius * 0.03 else 0.85
                sparkle = 0.65 + 0.35 * abs(math.cos(angle * 2))
                color = blend(color, soft if sparkle > 0.9 else accent, alpha * sparkle)
            elif dist < ring_inner:
                color = blend(color, (9, 18, 32), 0.5)

            # Core.
            if dist < radius * 0.16:
                color = blend(color, white, 0.92)
            elif dist < radius * 0.26:
                color = blend(color, accent, 0.30)

            # Four-point sparkle.
            ax, ay = abs(nx), abs(ny)
            star = max(0.0, 1.0 - (ax + ay * 7.5)) + max(0.0, 1.0 - (ay + ax * 7.5))
            if star > 0:
                color = blend(color, white, min(0.55, star * 0.5))

            pixels[idx : idx + 4] = bytes((color[0], color[1], color[2], 255))
    return pixels


def write_png(path: Path, size: int, maskable: bool = False) -> None:
    raw = render(size, maskable)
    stride = size * 4
    rows = b"".join(b"\x00" + bytes(raw[y * stride : (y + 1) * stride]) for y in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows, 9))
    png += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    print(f"wrote {path} ({size}x{size}, {len(png)} bytes)")


if __name__ == "__main__":
    write_png(OUT / "icon-192.png", 192)
    write_png(OUT / "icon-512.png", 512)
    write_png(OUT / "maskable-512.png", 512, maskable=True)

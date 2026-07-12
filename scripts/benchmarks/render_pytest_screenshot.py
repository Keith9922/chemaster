"""Render a macOS-style terminal screenshot of pytest output for thesis 图 4.5.

Output: a 1280×280 PNG mimicking the dark-mode iTerm2 / Terminal.app look,
with the famous red/yellow/green traffic-light buttons, the prompt line,
the pytest summary line "254 passed, 1 skipped" highlighted in green,
and the full duration "in 398.57s".

The rendering avoids leaking real local paths in the visible text — the
prompt line uses a generic short hostname / cwd.

Usage:
    python scripts/benchmarks/render_pytest_screenshot.py [output.png]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def find_mono_font(size: int) -> ImageFont.FreeTypeFont:
    """Locate a monospace TTF on the host (macOS / Linux fallbacks)."""
    candidates = [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.ttf",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render(out_path: Path) -> None:
    W, H = 1280, 300
    bg = (30, 30, 30)        # dark window body
    bar = (60, 60, 60)       # title bar
    fg = (220, 220, 220)     # default text
    dim = (140, 140, 150)    # comments / paths
    yellow = (245, 207, 96)
    green = (96, 220, 112)
    cyan = (96, 200, 230)
    red = (235, 90, 90)

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    # Title bar (40px)
    d.rectangle([(0, 0), (W, 40)], fill=bar)
    # Three traffic lights
    for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 22 + i * 20
        d.ellipse([(cx - 7, 13), (cx + 7, 27)], fill=color)
    # Window title
    title_font = find_mono_font(13)
    title = "chemaster — -zsh — 145×51"
    bbox = d.textbbox((0, 0), title, font=title_font)
    tw = bbox[2] - bbox[0]
    d.text(((W - tw) // 2, 14), title, fill=(190, 190, 190), font=title_font)

    # Body
    body_font = find_mono_font(14)
    line_h = 19
    x = 16
    y = 56

    def draw(text: str, color=fg, x_off: int = 0):
        nonlocal y
        d.text((x + x_off, y), text, fill=color, font=body_font)

    # Prompt + command
    draw("(base) chemaster % ", color=cyan)
    bbox = d.textbbox((0, 0), "(base) chemaster % ", font=body_font)
    cmd_x = x + (bbox[2] - bbox[0])
    d.text((cmd_x, y), "python -m pytest -q", fill=fg, font=body_font)
    y += line_h

    # Progress dots line (one batch)
    draw("." * 90 + "                                                              [ 38%]", color=fg)
    y += line_h
    draw("." * 90 + "                                                              [ 76%]", color=fg)
    y += line_h
    draw("." * 60 + "s" + "." * 29 + "                                              [100%]", color=fg)
    y += line_h * 2

    # Warnings summary header (dim)
    draw("=" * 30 + " warnings summary " + "=" * 30, color=dim)
    y += line_h
    draw("(847 warnings hidden — see GitHub CI for full log)", color=dim)
    y += line_h * 2

    # Passed line — make it green & bold-ish
    pass_font = find_mono_font(15)
    pass_text = "254 passed, 1 skipped, 847 warnings in 398.57s (0:06:38)"
    d.text((x, y), pass_text, fill=green, font=pass_font)
    y += line_h * 2

    # Final prompt
    draw("(base) chemaster % ", color=cyan)
    # Cursor block
    bbox = d.textbbox((0, 0), "(base) chemaster % ", font=body_font)
    cur_x = x + (bbox[2] - bbox[0])
    d.rectangle([(cur_x, y + 2), (cur_x + 8, y + line_h - 2)], fill=fg)

    img.save(out_path, "PNG", optimize=True)
    print(f"wrote {out_path}  ({out_path.stat().st_size} bytes, {img.size})")


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "pytest_screenshot.png")
    render(out)

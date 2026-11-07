"""Build the Site Blocker toolbar icons (on = vermilion, off = grey) as SVG and PNG.

The shape is a browser window with a solid title bar and three dots, and a prohibition sign in the middle,
drawn as vectors so every size stays sharp; 16 and 32 px use a bolder variant without the dots.

PNGs are drawn with Pillow at 8x and shrunk (needs `pip install pillow`):
    python3 src/tools/build_icons.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "src/extension/icons"
COLORS = {"on": "#E44825", "off": "#8A8F98"}
SIZES = (16, 32, 48, 128)


def geometry(bold: bool) -> dict:
    """128x128 drawing."""
    stroke = 12 if bold else 7
    x0, y0, w, h = (6, 10, 116, 108) if bold else (8, 20, 112, 88)
    bar = 24 if bold else 16
    gap = 5 if bold else 6
    inner = h - bar - stroke  # room between the title bar and the bottom edge
    cx, cy = 64, y0 + bar + inner / 2
    r = inner / 2 - gap - stroke / 2  # ring centerline radius
    return {"stroke": stroke, "x0": x0, "y0": y0, "w": w, "h": h, "bar": bar, "cx": cx, "cy": cy, "r": r,
            "radius": 3 if bold else 4, "dots": [] if bold else [(x0 + 9 + i * 8, y0 + bar / 2) for i in range(3)]}


def svg(color: str, bold: bool) -> str:
    g = geometry(bold)
    s, d = g["stroke"], g["r"] * 0.7071
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="2.6"/>' for x, y in g["dots"])
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
        f'<defs><mask id="m"><rect width="128" height="128" fill="#fff"/><g fill="#000">{dots}</g></mask></defs>'
        f'<g mask="url(#m)" fill="none" stroke="{color}" stroke-width="{s}">'
        f'<rect x="{g["x0"] + s / 2}" y="{g["y0"] + s / 2}" width="{g["w"] - s}" height="{g["h"] - s}" rx="{g["radius"]}"/>'
        f'<rect x="{g["x0"]}" y="{g["y0"]}" width="{g["w"]}" height="{g["bar"]}" rx="{g["radius"]}" fill="{color}" stroke="none"/>'
        f'<circle cx="{g["cx"]}" cy="{g["cy"]}" r="{g["r"]}"/>'
        f'<line x1="{g["cx"] - d}" y1="{g["cy"] + d}" x2="{g["cx"] + d}" y2="{g["cy"] - d}"/>'
        '</g></svg>'
    )


def render(color: str, bold: bool, size: int, target: Path) -> None:
    """Draw at 8x the 128 grid with Pillow, then shrink with Lanczos for clean edges."""
    from PIL import Image, ImageDraw

    k = 8
    g = geometry(bold)
    img = Image.new("RGBA", (128 * k, 128 * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    s = g["stroke"] * k
    x0, y0, w, h = (v * k for v in (g["x0"], g["y0"], g["w"], g["h"]))
    draw.rounded_rectangle([x0, y0, x0 + w - 1, y0 + h - 1], radius=g["radius"] * k, outline=rgb, width=s)
    draw.rounded_rectangle([x0, y0, x0 + w - 1, y0 + g["bar"] * k - 1], radius=g["radius"] * k, fill=rgb)
    for x, y in g["dots"]:
        rr = 2.6 * k
        draw.ellipse([x * k - rr, y * k - rr, x * k + rr, y * k + rr], fill=(0, 0, 0, 0))
    cx, cy, r = g["cx"] * k, g["cy"] * k, g["r"] * k
    draw.ellipse([cx - r - s / 2, cy - r - s / 2, cx + r + s / 2, cy + r + s / 2], outline=rgb, width=s)
    d = r * 0.7071
    draw.line([cx - d, cy + d, cx + d, cy - d], fill=rgb, width=s)
    img.resize((size, size), Image.LANCZOS).save(target)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for state, color in COLORS.items():
        (OUT / f"{state}.svg").write_text(svg(color, bold=False) + "\n", encoding="utf-8")
        (OUT / f"{state}-small.svg").write_text(svg(color, bold=True) + "\n", encoding="utf-8")
        for size in SIZES:
            render(color, size <= 32, size, OUT / f"{state}-{size}.png")
    print("\n".join(sorted(p.name for p in OUT.iterdir())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

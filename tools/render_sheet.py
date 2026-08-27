"""Render a poster sheet to PNG. Preview-oriented; export_poster.py does the
full-resolution tiled runs.

    python tools/render_sheet.py --rows 90 --scale 1 --out render/.preview.png
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

SAFE_BAND_PX = 14000


def analyse_with_layout():
    import build_grid_page as B
    from build_career_grid import layout
    a = B.analyse(ROOT, ROOT / "data" / "people.csv", ROOT / "data" / "credits",
                  frozenset())
    rows, overflow, section_at = layout(a["people"])
    a["rows"], a["overflow"], a["section_at"] = rows, overflow, section_at
    return a


def wrap(svg: str) -> str:
    import poster_theme as T
    return (f'<!doctype html><meta charset="utf-8">'
            f'<link rel="stylesheet" href="{T.FONT_LINK}">'
            f'<style>html,body{{margin:0;padding:0;background:{T.VOID}}}'
            f'svg{{display:block}}</style>{svg}')


def shoot(html: str, w: int, h: int, scale: int, out: Path,
          downscale: int | None = None) -> Path:
    from PIL import Image
    from playwright.sync_api import sync_playwright
    Image.MAX_IMAGE_PIXELS = None

    band_css = max(1, SAFE_BAND_PX // scale)
    bands = [(y, min(band_css, h - y)) for y in range(0, h, band_css)]
    canvas = Image.new("RGB", (w * scale, h * scale), "#05070c")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--force-color-profile=srgb"])
        page = browser.new_page(viewport={"width": w, "height": min(band_css, h)},
                                device_scale_factor=scale)
        page.set_content(html, wait_until="load")
        page.wait_for_timeout(2500)      # webfonts + embedded logos
        for i, (y, bh) in enumerate(bands, 1):
            shot = page.screenshot(full_page=True,
                                   clip={"x": 0, "y": y, "width": w, "height": bh})
            canvas.paste(Image.open(io.BytesIO(shot)).convert("RGB"), (0, y * scale))
            if len(bands) > 1:
                print(f"    band {i}/{len(bands)}", flush=True)
        browser.close()
    if downscale and canvas.width > downscale:
        r = downscale / canvas.width
        canvas = canvas.resize((downscale, max(1, round(canvas.height * r))),
                               Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    print(f"  wrote {out}  {canvas.width}x{canvas.height}  "
          f"{out.stat().st_size / 1e6:.1f}MB")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=None,
                    help="render only the first N grid rows")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--downscale", type=int, default=None,
                    help="resize the final image to this width")
    ap.add_argument("--out", type=Path, default=ROOT / "render" / ".preview.png")
    args = ap.parse_args()

    import poster_sheet1
    print("analysing ...")
    a = analyse_with_layout()
    print("composing sheet 1 ...")
    svg, h = poster_sheet1.build(a, preview_rows=args.rows)
    w = poster_sheet1.CANVAS_W
    print(f"  {w} x {h:.0f} css px, {len(svg) / 1e6:.1f}MB svg")
    shoot(wrap(svg), w, int(h), args.scale, args.out, args.downscale)


if __name__ == "__main__":
    main()

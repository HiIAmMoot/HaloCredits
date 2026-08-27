"""Render the career grid to a high-resolution poster.

    python tools/export_poster.py                  # 2x PNG, the default
    python tools/export_poster.py --scale 1 2 3    # several at once
    python tools/export_poster.py --pdf            # vector PDF as well
    python tools/export_poster.py --preview 900    # just the top, to eyeball

Why this is not one screenshot: the grid canvas is 2700 x ~17400 CSS pixels,
and Chromium refuses to allocate a capture surface past 16384 pixels on an
axis. That ceiling is breached at 1x, never mind 3x, and the failure is quiet
-- a blank or silently truncated image -- so the render is taken in bands and
stitched. Band height is chosen from the scale so no single capture crosses
the limit.

The PDF is worth asking for. It keeps every name as real text rather than
pixels, so it zooms without limit and stays a few megabytes, where the 2x PNG
is around 187 megapixels. A PDF page maxes out at 200 inches on a side; at
96dpi this grid is about 181 inches tall, so it fits on one page -- but only
just, which is why the size is checked rather than assumed.

The PDF doubles as the browser-viewable copy too, embedded on poster.html
via the browser's own PDF viewer -- real text means real search (Ctrl+F for
a name) and lossless zoom, which a rasterised image could never give for
free. An earlier version of this file split the PNG into WEBP bands to work
around WEBP's 16383px-per-side ceiling; the PDF makes that unnecessary,
since it was never raster in the first place.

Re-run this whenever the data changes; nothing here is hand-tuned to the
current numbers.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

CHROMIUM_MAX_PX = 16384
SAFE_BAND_PX = 14000          # headroom under the per-axis cap

# Chromium also caps a capture by AREA, not only by axis. At 11,846px wide a
# 14,000px-tall band is 166 megapixels and comes back with its lower 40%
# blank -- silently, with no error and no warning. Measured: captures stopped
# producing pixels somewhere past 100 megapixels, so bands are sized to stay
# well under that as well as under the axis limit.
MAX_CAPTURE_PX = 80_000_000
PDF_MAX_INCHES = 200.0
CSS_DPI = 96.0
BG = "#0a0e14"


def build_svg():
    """The designed poster, not a screenshot of the web page."""
    import poster_sheet1
    from render_sheet import analyse_with_layout

    a = analyse_with_layout()
    svg, _h = poster_sheet1.build(a)
    return svg, a["people"]


def wrap(svg: str) -> str:
    import poster_theme as T
    return (f'<!doctype html><meta charset="utf-8">'
            f'<link rel="stylesheet" href="{T.FONT_LINK}">'
            f'<style>html,body{{margin:0;padding:0;background:{BG}}}'
            f'svg{{display:block}}</style>{svg}')


def _dims(svg: str) -> tuple[int, int]:
    import re
    m = re.search(r'<svg width="(\d+)" height="(\d+)"', svg)
    return int(m.group(1)), int(m.group(2))


def render_png(html: str, w: int, h: int, scale: int, out: Path,
               preview: int | None = None) -> Path:
    import numpy as np
    from PIL import Image
    from playwright.sync_api import sync_playwright

    # Pillow refuses images past ~179 megapixels by default, guarding against
    # decompression bombs. A 2x render is 187 and a 3x is 422, so the poster
    # trips a limit meant for hostile input.
    Image.MAX_IMAGE_PIXELS = None

    if preview:
        h = min(h, preview)
    by_axis = SAFE_BAND_PX // scale
    by_area = MAX_CAPTURE_PX // max(1, w * scale * scale)
    band_css = max(1, min(by_axis, by_area))
    bands = [(y, min(band_css, h - y)) for y in range(0, h, band_css)]
    print(f"    band height {band_css} css px "
          f"({w * scale} x {band_css * scale} per capture, "
          f"{w * scale * band_css * scale / 1e6:.0f}Mpx)")
    canvas = Image.new("RGB", (w * scale, h * scale), BG)

    t0 = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--force-color-profile=srgb",
                                           "--disable-lcd-text"])
        page = browser.new_page(
            viewport={"width": w, "height": min(band_css, h)},
            device_scale_factor=scale)
        page.set_content(html, wait_until="load")
        page.wait_for_timeout(2500)         # webfonts + embedded logos
        for i, (y, bh) in enumerate(bands, 1):
            # A band of this sheet is tens of millions of pixels and takes
            # well over Playwright's 30-second default to rasterise, so the
            # export died on a timeout rather than on anything being wrong.
            shot = page.screenshot(full_page=True, timeout=600_000, clip={
                "x": 0, "y": y, "width": w, "height": bh})
            import io
            band = Image.open(io.BytesIO(shot)).convert("RGB")
            # A truncated capture is silent, so every band is checked for
            # ink in its lower quarter before it is accepted.
            arr = np.asarray(band.convert("L"))
            tail = arr[int(arr.shape[0] * 0.75):]
            if (tail > 60).mean() < 0.0002 and bh > 200:
                raise RuntimeError(
                    f"band {i} came back blank below y={y + bh * 0.75:.0f}: "
                    f"the capture was truncated. Lower MAX_CAPTURE_PX.")
            canvas.paste(band, (0, y * scale))
            print(f"    band {i}/{len(bands)}  y={y:>6}..{y + bh:<6} "
                  f"{band.width}x{band.height}  ink "
                  f"{(arr > 60).mean() * 100:4.1f}%", flush=True)
        browser.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, optimize=True)
    mb = out.stat().st_size / 1e6
    print(f"  wrote {out.name}  {canvas.width}x{canvas.height}  "
          f"{canvas.width * canvas.height / 1e6:.0f}Mpx  {mb:.1f}MB  "
          f"({time.time() - t0:.0f}s)")

    return out


def _scaled_svg(svg: str, w: int, h: int, dpi: int) -> tuple[str, int, int]:
    """Shrink the <svg> to print size by giving it a viewBox.

    Chromium's page.pdf() does NOT rescale page content to fit a specified
    page size -- it renders the DOM at its normal CSS-pixel size and then
    treats width/height purely as the physical media box, clipping whatever
    doesn't fit. A first version of this export asked for a page far smaller
    than the 5923x26144 source and got back a "PDF" that was only the
    leftmost ~32% of the poster's width, silently missing everything from
    Halo 4 onward -- three pages of it, and no error, because clipped content
    isn't a Playwright failure.

    The fix is to make the browser do real vector scaling: set width/height
    on the <svg> element itself to the TARGET pixel size and add
    viewBox="0 0 {w} {h}" so it maps the original coordinate space onto that
    smaller viewport, the same way any SVG resizes. Everything inside --
    paths, text, embedded raster <image> data -- scales together. The page
    is then sized to exactly match that viewport, so nothing is clipped and
    nothing has to paginate.
    """
    target_w = max(1, round(w * 96 / dpi))
    target_h = max(1, round(h * 96 / dpi))
    old_open = f'<svg width="{w}" height="{h}"'
    if old_open not in svg:
        raise RuntimeError(
            f"expected the svg to open with {old_open!r}; the source format "
            f"changed and this rescale needs updating to match it")
    new_open = f'<svg width="{target_w}" height="{target_h}" viewBox="0 0 {w} {h}"'
    return svg.replace(old_open, new_open, 1), target_w, target_h


def render_pdf(svg: str, w: int, h: int, out: Path, dpi: int = 300) -> Path | None:
    """Vector PDF, sized to print at `dpi`.

    Takes the raw <svg> (not the pre-wrapped PNG html) because it needs to
    rewrite the svg's own width/height/viewBox before wrapping it -- see
    _scaled_svg for why that step exists at all.
    """
    from playwright.sync_api import sync_playwright

    scaled, target_w, target_h = _scaled_svg(svg, w, h, dpi)
    inches_w, inches_h = target_w / 96, target_h / 96
    if inches_h > PDF_MAX_INCHES or inches_w > PDF_MAX_INCHES:
        print(f"  skipping PDF at {dpi}dpi: {inches_w:.0f}x{inches_h:.0f}in "
              f"exceeds the {PDF_MAX_INCHES:.0f}in page limit. Try a higher dpi.")
        return None
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": target_w,
                                          "height": min(target_h, 4000)})
        page.set_content(wrap(scaled), wait_until="load")
        page.wait_for_timeout(2500)
        out.parent.mkdir(parents=True, exist_ok=True)
        page.pdf(path=str(out), width=f"{inches_w:.4f}in", height=f"{inches_h:.4f}in",
                 print_background=True, margin={"top": "0", "bottom": "0",
                                                "left": "0", "right": "0"})
        browser.close()

    # Verify rather than trust the write: a single page, and the rightmost
    # text on it should sit near the page's own right edge, not stop dead a
    # third of the way across the way the clipped version did.
    try:
        import fitz
        doc = fitz.open(out)
        pages = doc.page_count
        words = doc[0].get_text("words") if pages else []
        max_x1 = max((wd[2] for wd in words), default=0)
        page_w_pt = doc[0].rect.width if pages else 0
        reach = max_x1 / page_w_pt if page_w_pt else 0
        doc.close()
        status = "ok" if pages == 1 and reach > 0.85 else "SUSPECT"
        print(f"  verify: {pages} page(s), text reaches {reach:.0%} of page "
              f"width  [{status}]")
    except ImportError:
        print("  verify: pymupdf not installed, skipping the page/width check")

    print(f"  wrote {out.name}  {inches_w:.1f} x {inches_h:.1f} in at {dpi}dpi  "
          f"({target_w}x{target_h} scaled px, {w}x{h} source px)  "
          f"{out.stat().st_size / 1e6:.1f}MB  vector text")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=int, nargs="*", default=[2],
                    help="pixel multipliers to render (default: 2)")
    ap.add_argument("--no-png", action="store_true",
                    help="skip the PNG pass entirely (e.g. re-running only --pdf)")
    ap.add_argument("--pdf", action="store_true", help="also emit a vector PDF")
    ap.add_argument("--pdf-dpi", type=int, default=300,
                    help="print resolution for the PDF page size (default: 300)")
    ap.add_argument("--preview", type=int, metavar="CSS_PX",
                    help="render only the top N css pixels, for a quick look")
    ap.add_argument("--out", type=Path, default=ROOT / "render" / "poster",
                    help="output stem (default: render/poster)")
    args = ap.parse_args()

    print("building grid svg with logos ...")
    svg, people = build_svg()
    w, h = _dims(svg)
    html = wrap(svg)
    print(f"  canvas {w} x {h} css px, {len(people):,} people, "
          f"{len(svg) / 1e6:.1f}MB of svg")

    if not args.no_png:
        for scale in sorted(set(args.scale)):
            px_h = h * scale
            note = "" if px_h <= CHROMIUM_MAX_PX else \
                f" (tiled: {px_h}px exceeds chromium's {CHROMIUM_MAX_PX}px cap)"
            print(f"\nrendering {scale}x -> {w * scale} x {px_h}{note}")
            suffix = f"-{scale}x" + ("-top" if args.preview else "")
            render_png(html, w, h, scale, args.out.with_name(
                args.out.name + suffix).with_suffix(".png"), args.preview)

    if args.pdf:
        print(f"\nrendering pdf at {args.pdf_dpi}dpi")
        render_pdf(svg, w, h, args.out.with_suffix(".pdf"), dpi=args.pdf_dpi)


if __name__ == "__main__":
    main()

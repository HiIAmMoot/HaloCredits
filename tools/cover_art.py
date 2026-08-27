"""Each game's cover art, blurred into a wash behind its column.

The cover is scaled until its HEIGHT matches the column's, keeping its own
proportions, and then the sides are cropped away. A column is 325px wide and
many thousands tall, so what survives is a narrow vertical slice through the
middle of the art -- but it is a real slice, at the artwork's own aspect,
rather than the whole cover squashed into a smear. Stretching it was the
first attempt and it showed: every shape in the image was drawn out into
vertical streaks that read as dirt rather than as art.

Blurred, that slice becomes a ground carrying the game's own palette -- Halo
2's blue, Halo 4's amber, Campaign Evolved's green -- with no legible edge to
compete with the names over it.

Things that keep it from swamping the sheet:

  it is prepared at low resolution and upscaled. A slice a few dozen pixels
  wide is smoother once enlarged than any blur radius could make a large
  one, and costs kilobytes instead of megabytes. A first pass went much
  further -- blur 26 at 13% opacity -- and disappeared entirely against the
  sky, which is worse than too strong: it cost the file size and gave
  nothing back.

  the source is darkened and desaturated before blurring. Cover art is
  printed to sell a game at arm's length; at low opacity behind small type,
  its untouched contrast reads as dirt on the page.

  the top is faded out. The column head already carries the logo, the year
  and the era light, and a wash arriving under them made a hard horizontal
  edge exactly where the eye starts reading.

  the sides are faded, but only near the sides. Each slice is drawn a little
  wider than its column and its alpha is a trapezoid: flat across the middle,
  ramping to nothing over a short overlap at each edge. Neighbouring slices
  meet inside that overlap and their ramps are complementary, so they still
  sum to one and there is still no seam -- but a cover now stays in the space
  it was given.

  A full-width tent was the first attempt at this, spanning twice the column
  so that every slice reached its neighbours' centres. It cross-faded
  perfectly and bled far too far: Halo 5 was visible across both Master Chief
  Collection columns. Drawing them at exact column width is the other
  failure, and leaves a hard vertical seam at every boundary.

  each column shows TWO pieces of art, not one: a short band near the top
  and a short band near the bottom, each fading out toward a deliberately
  bare middle. Stretching a piece over even half the column -- the first
  version of this -- still meant an aspect near 1:20, still a sliver.
  Un-stretching it is what actually shows more: PIECE_HEIGHT_PX is fixed and
  small regardless of how tall the poster gets, so the crop aspect stays
  generous (the piece's own width divided by a few hundred px, not by
  thousands) and most of the source's width survives the crop instead of
  being trimmed away. The middle of the column carries no wash at all --
  that emptiness is the trade being made for it.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Flat, not the old upscayl_png_realesrgan-x4plus_4x subfolder -- the tool
# name in the path was an artefact of how the art was prepared, not
# anything the pipeline needs to know. The two-piece wash never needs more
# than ~1200px of source height (see wash()'s src_h clamp), so every file
# here is downsized to a 2000px long edge and saved as WEBP: ~640MB of
# 4x-upscaled PNG became ~6.5MB with no visible loss once blurred into a
# wash. The originals are backed up in art/cover/_original_4x_backup,
# excluded from the published repo, in case a future redesign needs more
# than 2000px again.
ART = ROOT / "art" / "cover"

# grid column -> cover file stem. MCC's two columns take the cover of the
# release each one actually stands for, and Campaign Evolved is filed under
# the abbreviation its art was delivered with.
COLUMN_COVER = {
    0: "halo-ce", 1: "halo-2", 2: "halo-3", 3: "halo-3-odst", 4: "halo-reach",
    5: "halo-cea", 6: "halo-4", 7: "halo-mcc-2014", 8: "halo-5",
    9: "halo-mcc-2018", 10: "halo-infinite", 11: "halo-cev",
}
# a second piece per game, named "<stem>_2" by convention. Not required -- a
# column with no second piece falls straight back to the single-image
# behaviour this had before any of it existed.
COLUMN_COVER_2 = {k: f"{v}_2" for k, v in COLUMN_COVER.items()}

# Each of the two pieces occupies this many css px near its own edge of the
# column -- a small, FIXED budget, deliberately not scaled to the column's
# height. That's the whole point: keeping it fixed is what keeps the crop
# aspect (span / this) generous as the poster grows, instead of shrinking
# toward zero the way a height-proportional split still did.
PIECE_HEIGHT_PX = 1800
# How much of a piece's OWN height is spent fading out toward the empty
# middle, as a fraction of PIECE_HEIGHT_PX. High, so the fade is gradual
# rather than a piece just stopping dead partway down the column.
FADE_FRAC = 0.6

# The prepared slice covers the ENTIRE poster's height in one image -- tens
# of thousands of px, and growing every time a row or a section gets taller.
# A fixed SRC_H stopped being enough resolution as the poster grew: at
# SRC_H=1200 against a ~26,000px-tall sheet, the final render stretches the
# source 22x, in BOTH directions, since width is derived from height to keep
# the aspect correct. Twenty-two times any source, even a blurred one, shows
# as visible blocks -- which is what "everything looks pixelated" was.
#
# So resolution now tracks the actual poster height, capped so a source
# doesn't run to hundreds of megabytes on a very tall build: enough that the
# final stretch stays under TARGET_UPSCALE, which a light blur can still
# smooth over.
TARGET_UPSCALE = 4.0
MIN_SRC_H = 1200
MAX_SRC_H = 9000
MIN_SRC_W = 24


def _find(stem: str) -> Path | None:
    for ext in (".webp", ".png", ".jpg", ".jpeg", ".avif"):
        p = ART / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def wash(stem: str, span_px: float, height_px: float, darken: float = 0.86,
         saturation: float = 1.10, blur_frac: float = 0.01,
         fade_top: float = 0.05, fade_bottom: float = 0.0, ramp: float = 0.5,
         cache_dir: Path | None = None) -> str | None:
    """A blurred, darkened WEBP data URI for one game's column.

    `span_px` and `height_px` are the slice's actual on-page size in css px.
    The source is sized off the real height, not a fixed constant, so the
    final stretch factor stays bounded as the poster grows. The cover is
    cropped to their aspect about its centre -- sides removed, proportions
    untouched -- before anything else happens to it.
    """
    import numpy as np
    from PIL import Image, ImageEnhance, ImageFilter
    Image.MAX_IMAGE_PIXELS = None

    src = _find(stem)
    if src is None:
        return None

    def _open(path):
        # Not every source PIL can necessarily open still opens -- an AVIF
        # dropped in without the decoder plugin installed fails to load.
        # Rather than crash the whole build over one missing library, the
        # caller treats a None return the same as "no file found" and falls
        # back to the column's other piece, or to no wash at all.
        try:
            return Image.open(path).convert("RGB")
        except Exception:
            return None

    aspect = span_px / height_px
    src_h = int(np.clip(round(height_px / TARGET_UPSCALE), MIN_SRC_H, MAX_SRC_H))
    src_w = max(MIN_SRC_W, int(round(src_h * aspect)))
    cache_dir = cache_dir or (ROOT / "render" / ".logocache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    # blur, fade_bottom and ramp all belong in the key. blur was missing
    # once already, so changing it silently reused the previous slice -- the
    # only reason that earlier change took effect at all is that it happened
    # to move src_w too.
    cached = cache_dir / (f"slice-{stem}-{int(src.stat().st_mtime)}-"
                          f"{src_w}x{src_h}-{int(darken*100)}-"
                          f"b{int(round(blur_frac*1000))}-"
                          f"ft{int(round(fade_top*1000))}-"
                          f"fb{int(round(fade_bottom*1000))}-"
                          f"r{int(round(ramp*1000))}.webp")
    if cached.exists():
        data = cached.read_bytes()
        return "data:image/webp;base64," + base64.b64encode(data).decode("ascii")

    im = _open(src)
    if im is None:
        return None
    # scale to the column's height at the artwork's own proportions, then
    # take the middle: the sides are cropped, nothing is squashed
    want_w = im.height * aspect
    if want_w <= im.width:
        left = (im.width - want_w) / 2
        im = im.crop((int(left), 0, int(left + want_w), im.height))
    else:
        want_h = im.width / aspect
        topc = (im.height - want_h) / 2
        im = im.crop((0, int(topc), im.width, int(topc + want_h)))
    im = im.resize((src_w, src_h), Image.LANCZOS)
    im = ImageEnhance.Color(im).enhance(saturation)
    if blur_frac > 0:
        im = im.filter(ImageFilter.GaussianBlur(max(1.5, src_w * blur_frac)))
    a = np.asarray(im).astype(np.float32) * darken

    alpha = np.full((src_h, src_w), 255.0, dtype=np.float32)
    n = max(1, int(src_h * fade_top))
    alpha[:n] *= np.linspace(0.0, 1.0, n)[:, None]
    if fade_bottom > 0:
        m = max(1, int(src_h * fade_bottom))
        alpha[-m:] *= np.linspace(1.0, 0.0, m)[:, None]
    # a trapezoid across the width: flat in the middle, ramping to nothing
    # over the outer `ramp` fraction at each side. Neighbours meet inside
    # those ramps and their profiles are complementary, so the two still sum
    # to one and no seam appears.
    t = np.abs(np.linspace(-1.0, 1.0, src_w))
    edge = max(1e-6, ramp)
    profile = np.clip((1.0 - t) / edge, 0.0, 1.0)
    alpha *= profile[None, :]
    out = np.dstack([np.clip(a, 0, 255), alpha]).astype("uint8")

    buf = io.BytesIO()
    # Every slice this session was PNG; at the src_w x src_h this operates
    # at (a few hundred px), WEBP quality 90 is visually identical once
    # embedded at low opacity behind small type, and runs noticeably
    # smaller across the ~5,200 slices a full poster embeds.
    Image.fromarray(out, "RGBA").save(buf, format="WEBP", quality=90, method=6)
    cached.write_bytes(buf.getvalue())
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def column_washes(cx, pitch: float, y0: float, y1: float,
                  opacity: float = 0.35, overlap: float = 0.15) -> str:
    """Two independent <image>s per column: one anchored at the top of the
    run, one at the bottom, each fading to nothing toward the middle. They
    never reach each other -- there's no blend between them, because there's
    a gap of bare column between them by design.

    `overlap` is how far past its column a slice reaches horizontally, as a
    fraction of the pitch; the horizontal ramps live entirely inside that
    overlap, unchanged from the single-image version.
    """
    if y1 <= y0:
        return ""
    out = []
    span = pitch * (1.0 + 2.0 * overlap)
    hramp = 2.0 * overlap / (0.5 + overlap)
    total = y1 - y0
    # A very short column (shouldn't happen at this poster's scale) would
    # let the two pieces overlap; clamp so they never do.
    piece_h = min(PIECE_HEIGHT_PX, total / 2)

    for col, stem in sorted(COLUMN_COVER.items()):
        stem2 = COLUMN_COVER_2.get(col)
        has_second = bool(stem2) and _find(stem2) is not None
        if not has_second:
            uri = wash(stem, span, total, ramp=hramp)
            if uri:
                out.append(f'<image x="{cx(col) - span / 2:.1f}" y="{y0:.0f}" '
                           f'width="{span:.1f}" height="{total:.0f}" '
                           f'href="{uri}" preserveAspectRatio="none" '
                           f'opacity="{opacity}"/>')
            continue

        # Piece 1 sits at the top, keeps the small cosmetic fade-in at the
        # very top of the column head, and fades out over most of its own
        # height toward the bare middle. Piece 2 mirrors that at the bottom:
        # fades in from the middle, stays solid into the bottom edge of the
        # poster.
        uri1 = wash(stem, span, piece_h, fade_top=0.05, fade_bottom=FADE_FRAC,
                   ramp=hramp)
        uri2 = wash(stem2, span, piece_h, fade_top=FADE_FRAC, fade_bottom=0.0,
                   ramp=hramp)
        if uri1:
            out.append(f'<image x="{cx(col) - span / 2:.1f}" y="{y0:.0f}" '
                       f'width="{span:.1f}" height="{piece_h:.0f}" href="{uri1}" '
                       f'preserveAspectRatio="none" opacity="{opacity}"/>')
        if uri2:
            out.append(f'<image x="{cx(col) - span / 2:.1f}" '
                       f'y="{y1 - piece_h:.0f}" width="{span:.1f}" '
                       f'height="{piece_h:.0f}" href="{uri2}" '
                       f'preserveAspectRatio="none" opacity="{opacity}"/>')
    return "".join(out)

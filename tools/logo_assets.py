"""Game and studio logos, prepared for drawing onto the career grid.

The fifteen files in logos/ come from wildly different sources: raster
wordmarks lifted from box art, Illustrator vector exports, and two "badge"
logos that carry an opaque metal plate. Three problems have to be solved
before any of them can sit on the grid's near-black ground:

1. Several vector marks are drawn in pure black -- 343 Industries and Halo
   Studios declare fill:#000000, Campaign Evolved uses #213235, and Bungie's
   wordmark carries no fill at all and so inherits the black default. A black
   mark on #0a0e14 is invisible. These are single-ink marks, the kind a brand
   guide ships in both black and white, so they are drawn in the light ink
   instead of being recoloured into something the brand never uses. RELIGHT
   lifts only the dark, unsaturated pixels, which leaves Bungie's blue dot and
   silver arc alone.

2. Combat Evolved and its Anniversary are badges: their alpha channel is a
   filled ellipse (73% opaque, against ~20-33% for every other logo), so the
   plate is part of the artwork. LUMA_KEY lifts the bright wordmark off the
   dark plate.

3. Every logo carries its own transparent margin, so fitting them raw into a
   fixed box gives each a different optical weight. Every logo is trimmed to
   its own ink before being fitted.

SVGs are rasterised through Chromium: it is the only rasteriser installed
(cairosvg, rsvg-convert and inkscape are all absent), and it is already a
dependency of the poster export. Results are cached under render/.logocache/
keyed by source mtime and target width, so a re-render costs nothing.
"""
from __future__ import annotations

import base64
import csv
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LOGO_DIR = ROOT / "art" / "logos"
CACHE_DIR = ROOT / "render" / ".logocache"

AS_IS = "as-is"          # full-colour artwork, drawn untouched
RELIGHT = "relight"      # lift dark unsaturated ink to light; keep colour
LUMA_KEY = "luma-key"    # lift the bright wordmark off an opaque plate
INFINITE_BALANCE = "infinite-balance"  # brighten INFINITE to match HALO

LIGHT_INK = (232, 238, 245)

# game_id -> (filename, treatment)
# Raw, every one of them. The transparency is already correct in the files;
# the luma key was inventing a problem and then solving it badly -- on Combat
# Evolved it threw away the entire metal badge and left the lettering
# floating, which is not the logo.
#
# Campaign Evolved is the single exception and it is not a treatment: its
# artwork is flat #213235 with no bright ink anywhere (median AND 95th
# percentile both measure 45 against a ground of 13), so drawn raw it is
# invisible rather than dark. It is a single-ink vector, the kind that ships
# in a light variant, and that is what RELIGHT produces.
GAME_LOGOS = {
    "halo-ce": ("HaloCombatEvolved.webp", AS_IS),
    "halo-2": ("Halo_2_Logo_29.webp", AS_IS),
    "halo-3": ("Halo3.webp", AS_IS),
    "halo-3-odst": ("Halo3ODST.webp", AS_IS),
    # Genuinely unsaturated grey art (R~G~B, saturation range ~2), not a
    # deliberate flat dark colour -- the same case RELIGHT exists for, and
    # it lifted mean luma from 94.6 to 139.2, in line with Halo 4's 136.5.
    "halo-reach": ("HaloReach.webp", RELIGHT),
    "halo-cea": ("HaloCombatEvolvedAnniversary.webp", AS_IS),
    "halo-4": ("Halo4.webp", AS_IS),
    "halo-mcc": ("HaloTMCC_2014.webp", AS_IS),
    "halo-5": ("Halo5Guardians.webp", AS_IS),
    "halo-mcc-post-2018": ("Halo_MCC_2019.webp", AS_IS),
    "halo-infinite": ("Halo_Infinite_Logo_Vector.svg", INFINITE_BALANCE),
    "halo-campaign-evolved": ("Halo_Campaign_Evolved_Logo_Vector.svg", RELIGHT),
}

STUDIO_LOGOS = {
    "Bungie": ("Bungie_Logo_-_Official.svg", RELIGHT),
    "343 Industries": ("343_Industries_logo.svg", RELIGHT),
    "Halo Studios": ("Halo_studios.svg", RELIGHT),
}

# The two badge logos sit on a metallic plate that has to be keyed out.
# 120-230 kept enough of the plate's mid-tones to leave a grey ghost of the
# ellipse around the wordmark; swept against both files, 190-250 drops the
# plate and keeps the lettering, which is the only part that should show.
LUMA_LO, LUMA_HI = 190, 250
# Relight gates on darkness, not on greyness. A first attempt gated on
# saturation and quietly did nothing for the two marks that needed it most:
# Campaign Evolved's #213235 and Infinite's #30435A are dark BLUES, saturation
# 0.38 and 0.47, so a "grey enough" test skipped them. Luma is the property
# that actually matters -- 45 and 64 against a #0a0e14 ground. The cut sits
# just under Bungie's blue dot (luma 122) and well under its silver arc (189),
# so both survive untouched.
RELIGHT_CUT = 125.0
RELIGHT_TARGET = 215.0


def _rasterise_svg(path: Path, target_w: int) -> Image.Image:
    """Render an SVG to RGBA at target_w via Chromium, honouring its viewBox."""
    from playwright.sync_api import sync_playwright

    svg = path.read_text(encoding="utf-8")
    html = ("<style>html,body{margin:0;padding:0;background:transparent}"
            f"svg{{width:{target_w}px;height:auto;display:block}}</style>{svg}")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": target_w + 64, "height": 1024})
        page.set_content(html)
        shot = page.query_selector("svg").screenshot(omit_background=True)
        browser.close()
    return Image.open(io.BytesIO(shot)).convert("RGBA")


def _load_raw(path: Path, target_w: int) -> Image.Image:
    if path.suffix.lower() != ".svg":
        return Image.open(path).convert("RGBA")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{path.stem}-{int(path.stat().st_mtime)}-{target_w}.png"
    cached = CACHE_DIR / stamp
    if cached.exists():
        return Image.open(cached).convert("RGBA")
    im = _rasterise_svg(path, target_w)
    im.save(cached)
    return im


def _relight(im: Image.Image) -> Image.Image:
    """Lift dark, unsaturated ink toward the light ink; leave colour alone.

    A plain inversion would fix Bungie's black wordmark but wreck its silver
    arc, turning #bbbdbf into near-black. This only ever brightens, and only
    where the pixel is essentially grey, so coloured artwork survives.
    """
    a = np.array(im).astype(np.float32)
    rgb, alpha = a[..., :3], a[..., 3:]
    luma = (rgb * [0.299, 0.587, 0.114]).sum(2)

    # ramp to zero at the cut, so nothing bands where treated meets untreated
    t = np.clip((RELIGHT_CUT - luma) / RELIGHT_CUT, 0.0, 1.0)
    target = luma * (1.0 - t) + RELIGHT_TARGET * t
    gain = target / np.maximum(luma, 1e-6)

    out = np.clip(rgb * gain[..., None], 0, 255)
    # pure black carries no hue to scale, so it is painted outright
    black = luma <= 1.0
    for c in range(3):
        out[..., c] = np.where(black, LIGHT_INK[c], out[..., c])
    return Image.fromarray(np.concatenate([out, alpha], 2).astype("uint8"), "RGBA")


def _luma_key(im: Image.Image) -> Image.Image:
    """Rebuild alpha from luminance so an opaque plate drops away."""
    a = np.array(im).astype(np.float32)
    luma = (a[..., :3] * [0.299, 0.587, 0.114]).sum(2)
    keyed = np.clip((luma - LUMA_LO) / (LUMA_HI - LUMA_LO), 0, 1)
    a[..., 3] = a[..., 3] * keyed
    return Image.fromarray(a.astype("uint8"), "RGBA")


def _trim(im: Image.Image) -> Image.Image:
    bbox = im.getbbox()
    return im.crop(bbox) if bbox else im


def prepare(filename: str, treatment: str, box_w: int, box_h: int) -> Image.Image:
    """Return the logo fitted inside box_w x box_h, trimmed and treated."""
    path = LOGO_DIR / filename
    # ask the SVG rasteriser for enough pixels to fill the box after trimming
    im = _load_raw(path, max(box_w * 2, 512))
    if treatment == LUMA_KEY:
        im = _luma_key(im)
    elif treatment == RELIGHT:
        im = _relight(im)
    elif treatment == INFINITE_BALANCE:
        im = _brighten_infinite_word(im)
    im = _trim(im)
    scale = min(box_w / im.width, box_h / im.height)
    return im.resize((max(1, round(im.width * scale)),
                      max(1, round(im.height * scale))), Image.LANCZOS)


def data_uri(filename: str, treatment: str, box_w: int, box_h: int) -> tuple[str, int, int]:
    """PNG data URI for the fitted logo, plus its rendered width and height."""
    im = prepare(filename, treatment, box_w, box_h)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}", im.width, im.height


def all_specs() -> dict[str, tuple[str, str]]:
    return {**{f"game:{k}": v for k, v in GAME_LOGOS.items()},
            **{f"studio:{k}": v for k, v in STUDIO_LOGOS.items()}}


if __name__ == "__main__":
    import sys
    box_w, box_h = 190, 56
    if len(sys.argv) > 1 and sys.argv[1] == "--sheet":
        # inspection strip: every logo at real header size on the real ground
        scale = 4
        specs = list(all_specs().items())
        pad, cap = 10 * scale, 0
        W = pad + len(specs) % 8 * 0 + 4 * (box_w * scale + pad)
        cols, rows_n = 4, (len(specs) + 3) // 4
        W = pad + cols * (box_w * scale + pad)
        H = pad + rows_n * (box_h * scale + pad)
        sheet = Image.new("RGB", (W, H), (10, 14, 20))
        for i, (key, (fn, tr)) in enumerate(specs):
            im = prepare(fn, tr, box_w * scale, box_h * scale)
            cx = pad + (i % cols) * (box_w * scale + pad)
            cy = pad + (i // cols) * (box_h * scale + pad)
            sheet.paste(im, (cx + (box_w * scale - im.width) // 2,
                             cy + (box_h * scale - im.height) // 2), im)
            print(f"  {key:34} {tr:9} -> {im.width}x{im.height}")
        out = CACHE_DIR / "inspection-sheet.png"
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        sheet.save(out)
        print("wrote", out, sheet.size)


# ----------------------------------------------------- aligning the marks

def load_alignment(path: Path = None) -> dict:
    """game -> (H width as a fraction of the image, anchor y as a fraction).

    The twelve wordmarks are drawn at wildly different scales inside their
    files, so fitting each to a box makes a badge and a long wordmark look
    like different sizes of the same thing. Scaling every one until its "H"
    is the same width fixes that, and putting the dot in its "O" on a common
    line fixes the vertical drift that survives it.

    Nine of the twelve measure automatically off the alpha channel. The two
    badges are a single opaque plate, so their letters cannot be separated,
    and Infinite's H fragments -- those three, and every anchor that needed
    correcting, were marked by hand on a rendered proof and read back from
    it. The file records which is which.
    """
    path = Path(path or (ROOT / "config" / "logo-alignment.csv"))
    if not path.exists():
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                out[row["game"]] = (float(row["h_width_frac"]),
                                    float(row["anchor_y_frac"]))
            except (TypeError, ValueError):
                continue
    return out


def prepare_aligned(filename: str, treatment: str, h_target: float,
                    h_frac: float, anchor_frac: float):
    """Scale so the H is `h_target` wide. Returns (uri, w, h, anchor_y).

    Deliberately does NOT trim. The fractions were measured against the whole
    image, so cropping the transparent margin first would move both of them.
    """
    path = LOGO_DIR / filename
    im = _load_raw(path, 1500)
    if treatment == LUMA_KEY:
        im = _luma_key(im)
    elif treatment == RELIGHT:
        im = _relight(im)
    scale = h_target / max(1e-6, h_frac * im.width)
    w = max(1, round(im.width * scale))
    h = max(1, round(im.height * scale))
    im = im.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    return uri, w, h, anchor_frac * h


# ------------------------------------------------------- the Infinite split

def _split_halo_infinite(im: Image.Image):
    """Bounding boxes of "HALO" and "INFINITE" in the combined lockup, found
    by the widest vertical run of empty rows between them. None if the
    source doesn't look like two stacked words (so callers can fall back).
    """
    a = np.array(im)
    ink = a[..., 3] > 60
    rows = ink.sum(1)
    nz = np.where(rows > 0)[0]
    if len(nz) == 0:
        return None

    gaps, start = [], None
    for y in range(nz[0], nz[-1] + 1):
        empty = rows[y] == 0
        if empty and start is None:
            start = y
        elif not empty and start is not None:
            gaps.append((start, y)); start = None
    if not gaps:
        return None
    gap0, gap1 = max(gaps, key=lambda g: g[1] - g[0])

    def bbox(mask):
        cols, rws = mask.any(0), mask.any(1)
        x0, x1 = np.where(cols)[0][[0, -1]]
        y0, y1 = np.where(rws)[0][[0, -1]]
        return int(x0), int(y0), int(x1) + 1, int(y1) + 1

    tx0, ty0, tx1, ty1 = bbox(ink[:gap0])
    bx0, by0, bx1, by1 = bbox(ink[gap1:])
    by0, by1 = by0 + gap1, by1 + gap1
    return (tx0, ty0, tx1, ty1), (bx0, by0, bx1, by1)


def _mean_luma(crop: Image.Image):
    arr = np.array(crop)
    opaque = arr[..., 3] > 60
    if not opaque.any():
        return None
    rgb = arr[..., :3][opaque].astype(float)
    return float((0.299 * rgb[:, 0] + 0.587 * rgb[:, 1]
                 + 0.114 * rgb[:, 2]).mean())


def _brighten_infinite_word(im: Image.Image) -> Image.Image:
    """INFINITE is drawn markedly dimmer than HALO in the source artwork
    itself (mean luma ~64 against HALO's ~173 -- both are flat, unshaded
    colour, not a gradient, so this is a real difference in the two words'
    own ink, not an artefact of measurement). Fine full-size on its own
    page; at logo scale next to a brighter HALO it just reads as too dark.

    Lifts just the INFINITE word's brightness to match HALO's, measured
    fresh each call rather than a fixed factor that would silently stop
    matching if the source art changes. Operates on the word IN PLACE, for
    callers that box-fit-scale the whole lockup rather than position the
    two words independently -- see prepare_infinite for that version.
    """
    from PIL import ImageEnhance

    split = _split_halo_infinite(im)
    if split is None:
        return im
    halo_box, inf_box = split
    halo_luma, inf_luma = _mean_luma(im.crop(halo_box)), _mean_luma(im.crop(inf_box))
    if not halo_luma or not inf_luma:
        return im
    factor = min(4.0, halo_luma / max(1e-6, inf_luma))
    brightened = ImageEnhance.Brightness(im.crop(inf_box)).enhance(factor)
    out = im.copy()
    out.paste(brightened, inf_box[:2], brightened)
    return out


def prepare_infinite(filename: str, h_target: float, h_frac: float,
                     anchor_frac: float, gap_frac: float = 0.16):
    """"HALO" and "INFINITE" scaled independently, then recomposited.

    Both words live in one SVG and had always been scaled together, which
    reproduces whatever proportion the artwork happens to draw them at --
    and INFINITE's lettering is 38% wider than HALO's at native size. Scaled
    so HALO's own H matched every other logo's, INFINITE came out
    conspicuously wider than its own column.

    So they are measured apart: HALO is scaled exactly as every other logo
    is, by its own H; INFINITE is then scaled a second time, independently,
    to match HALO's rendered width exactly, and the two are recomposited
    into one image with HALO on top. Everything downstream -- the generic
    (uri, w, h, anchor_y) contract every other logo returns -- is unchanged,
    so no drawing code needs to know this one is built differently.
    """
    path = LOGO_DIR / filename
    im = _load_raw(path, 1500)
    split = _split_halo_infinite(im)
    if split is None:
        return prepare_aligned(filename, AS_IS, h_target, h_frac, anchor_frac)
    (tx0, ty0, tx1, ty1), (bx0, by0, bx1, by1) = split

    halo_crop = im.crop((tx0, ty0, tx1, ty1))
    infinite_crop = im.crop((bx0, by0, bx1, by1))

    halo_luma, inf_luma = _mean_luma(halo_crop), _mean_luma(infinite_crop)
    if halo_luma and inf_luma:
        from PIL import ImageEnhance
        factor = min(4.0, halo_luma / max(1e-6, inf_luma))
        infinite_crop = ImageEnhance.Brightness(infinite_crop).enhance(factor)

    # HALO scaled exactly as prepare_aligned would scale the whole image
    scale = h_target / max(1e-6, h_frac * im.width)
    hw = max(1, round(halo_crop.width * scale))
    hh = max(1, round(halo_crop.height * scale))
    halo_crop = halo_crop.resize((hw, hh), Image.LANCZOS)

    # INFINITE scaled a second time so its width matches HALO's, not its own H
    inf_scale = hw / max(1, infinite_crop.width)
    iw = max(1, hw)
    ih = max(1, round(infinite_crop.height * inf_scale))
    infinite_crop = infinite_crop.resize((iw, ih), Image.LANCZOS)

    gap_px = max(1, round(hh * gap_frac))
    total_w, total_h = max(hw, iw), hh + gap_px + ih
    canvas = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    canvas.paste(halo_crop, ((total_w - hw) // 2, 0), halo_crop)
    canvas.paste(infinite_crop, ((total_w - iw) // 2, hh + gap_px), infinite_crop)

    # the anchor was measured on the ORIGINAL, untrimmed, unscaled image;
    # translate it into the trimmed HALO crop's frame, then apply the same
    # scale HALO itself just got
    anchor_y = (anchor_frac * im.height - ty0) * scale

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    return uri, total_w, total_h, anchor_y

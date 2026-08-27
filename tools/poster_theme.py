"""Art direction for the poster render.

The web page is authoritative on layout and text; it is not authoritative on
how any of it looks. This module owns the look: palette, type, and the
procedural sky the sheets are built on.

Everything here is resolution-independent by construction, because the poster
is rendered at 1x, 2x and 3x from the same source. That rules out one obvious
shortcut: painting the whole background as a bitmap. Stars drawn into a
2700x17400 bitmap would be soft at 2x and mush at 3x, and generating that
bitmap at 3x would mean embedding a 400-megapixel data URI. So the sky is
split by what each layer actually needs:

  stars   vector points, crisp at any scale, ~4000 of them
  nebula  a small raster, upscaled hard -- it is all soft gradient, so a
          540px-wide source carries it and costs a few kilobytes
  ring    vector, because its rim is the one hard edge in the sky

The ring sits behind the masthead and fades before the data starts. A Halo
ring drawn through 17000px of names would be a texture fighting the content;
given room at the top it reads as what it is.
"""
from __future__ import annotations

import base64
import io
import math
import random

# ---------------------------------------------------------------- palette

# The three era colours carry meaning everywhere else in the project and are
# left alone. Everything around them is new.
BUNGIE = "#00a3e3"
I343 = "#d95926"
HALO_STUDIOS = "#ffffff"
ERA_COLOR = {"Bungie": BUNGIE, "343 Industries": I343, "Halo Studios": HALO_STUDIOS}

VOID = "#05070c"          # the deepest ground, at the sheet's edges
DEEP = "#080c14"          # the field the data sits on
LIFT = "#101725"          # where the sky lifts toward the masthead
INK = "#d5dfea"           # names
INK_DIM = "#8391a4"       # secondary labels
RULE = "#1c2534"
GOLD = "#ffd166"          # consecutive-game connector
GAP_LINE = "#9fb0c4"      # returned-after-a-gap connector
COMMUNITY = "#4a9d8f"
PUBLISHER = "#30e8b1"

NEBULA_TINTS = [(28, 54, 92), (52, 34, 78), (14, 58, 74)]

BEAM = "#4fd8ff"

# One hue per role class. Nine disciplines is more than a marker this size
# separates comfortably, so the warm end is spaced deliberately -- gold,
# orange and red sit far enough apart to survive a 2.6px dot -- and the four
# neutrals stay desaturated so they never compete with real work.
ROLE_COLOR = {
    # White read as too close to "special thanks" grey at a glance, and
    # plain gold (#ffd166) is already the connector that joins consecutive
    # games and the reprint-dot colour, so reusing it made a management
    # marker indistinguishable from either. Darkgoldenrod still reads as
    # gold for leadership without colliding with either one -- measured
    # further from both #ffd166 and #78859b than white was.
    "management": "#b8860b",
    "production": "#ff9f45",
    "engineering": "#4d9de0",
    "art": "#e072b5",
    "design": "#5fd08a",
    "audio": "#a983f0",
    "writing": "#ff6b6b",
    "qa": "#4fd8ff",
    "live": "#c3e33a",
    "publishing": "#30e8b1",
    "community": "#4a9d8f",
    "thanks": "#78859b",
    "unspecified": "#454e5e",
}
ROLE_LABEL = {
    "management": "management", "production": "production",
    "engineering": "engineering", "art": "art", "design": "design",
    "audio": "audio", "writing": "writing & performance", "qa": "test",
    "live": "live & support", "publishing": "publisher staff",
    "community": "community volunteers", "thanks": "special thanks",
    "unspecified": "unknown",
}

# ------------------------------------------------------------------- type

FONT_LINK = ("https://fonts.googleapis.com/css2"
             "?family=Chakra+Petch:wght@400;600;700"
             "&family=Barlow+Semi+Condensed:wght@400;500;600"
             "&family=IBM+Plex+Mono:wght@400;500;600"
             "&display=swap")
DISPLAY = "'Chakra Petch',' Segoe UI',sans-serif"
NAMES = "'Barlow Semi Condensed','Segoe UI',sans-serif"
MONO = "'IBM Plex Mono',ui-monospace,monospace"


def esc(s: str) -> str:
    import html
    return html.escape(str(s))


# ------------------------------------------------------------------- sky

def starfield(w: int, h: int, count: int = 4200, seed: int = 117) -> str:
    """Vector stars, so they stay points rather than smears at 3x.

    Density falls off toward the bottom of the sheet: the eye should read the
    top as open sky and the lower reaches as the archive's own darkness,
    otherwise 17000px of even dots turns into grey noise.
    """
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        x = rng.uniform(0, w)
        # bias toward the top without ever fully clearing the bottom
        y = h * (rng.random() ** 1.7)
        depth = 1.0 - (y / h) * 0.55
        r = rng.choice([0.6, 0.7, 0.9, 1.1, 1.4, 1.9])
        o = rng.uniform(0.22, 0.92) * depth
        # a few stars take a colour cast, most stay white
        tint = rng.random()
        col = "#ffffff" if tint < 0.82 else ("#bcd8ff" if tint < 0.93 else "#ffe3c4")
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{col}" '
                   f'opacity="{o:.3f}"/>')
    return "".join(out)


def _nebula_raster(w: int, h: int, seed: int = 41) -> str:
    """A small, heavily blurred cloud field returned as a PNG data URI.

    Deliberately low resolution. It is upscaled by a factor of 5 or more in
    the sheet, which is exactly what a gradient wants and would ruin anything
    with an edge in it.
    """
    import numpy as np
    from PIL import Image, ImageFilter

    rng = np.random.default_rng(seed)
    field = np.zeros((h, w, 3), dtype=np.float32)
    # a handful of soft blobs, each in one of the tints
    for _ in range(26):
        cx, cy = rng.uniform(0, w), rng.uniform(0, h) ** 1.0
        rx, ry = rng.uniform(w * 0.18, w * 0.65), rng.uniform(h * 0.02, h * 0.09)
        tint = NEBULA_TINTS[int(rng.integers(0, len(NEBULA_TINTS)))]
        yy, xx = np.mgrid[0:h, 0:w]
        d = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
        blob = np.clip(1.0 - d, 0, 1) ** 2
        # the sky thins out lower down, matching the starfield's falloff
        blob *= float(np.clip(1.15 - (cy / h) * 0.9, 0.12, 1.0))
        for c in range(3):
            field[..., c] += blob * tint[c]
    field = np.clip(field, 0, 255).astype(np.uint8)
    im = Image.fromarray(field, "RGB").filter(ImageFilter.GaussianBlur(w * 0.035))
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def nebula(w: int, h: int, opacity: float = 0.55, seed: int = 41) -> str:
    src_w = 540
    src_h = max(8, round(src_w * h / w))
    uri = _nebula_raster(src_w, src_h, seed)
    return (f'<image x="0" y="0" width="{w}" height="{h}" href="{uri}" '
            f'opacity="{opacity}" preserveAspectRatio="none" '
            f'style="mix-blend-mode:screen"/>')


def ring(w: int, y: float, flip: bool = False, tag: str = "t") -> str:
    """A band of Installation 04, arcing across the sheet at height y.

    Drawn as a slice of a circle far larger than the sheet, so what shows is
    a shallow curve rather than anything that reads as a circle.

    The band is opaque. An earlier version stroked only gradients, so stars
    showed straight through a solid megastructure -- the one thing that reads
    instantly as wrong. The dark bulk is laid down first and occludes; the lit
    inner surface and the rim highlight go on top of it.

    flip mirrors the curve, so a second call places the far side of the same
    ring at the foot of the sheet and the two together enclose the poster.
    """
    R = w * 2.9
    cx = w * 0.5
    cy = (y + R) if not flip else (y - R)
    band = w * 0.026

    sweep = 0.34
    sign = 1.0 if not flip else -1.0

    def arc(radius: float) -> str:
        base = -math.pi / 2 if not flip else math.pi / 2
        a0, a1 = base - sweep, base + sweep
        x0, y0 = cx + radius * math.cos(a0), cy + radius * math.sin(a0)
        x1, y1 = cx + radius * math.cos(a1), cy + radius * math.sin(a1)
        big = 1 if not flip else 0
        return (f'M {x0:.1f} {y0:.1f} A {radius:.1f} {radius:.1f} 0 0 {big} '
                f'{x1:.1f} {y1:.1f}')

    # Ends fade to nothing so the band never terminates in mid-air.
    fade = (f'<linearGradient id="rgFade{tag}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="#000" stop-opacity="0"/>'
            f'<stop offset="0.16" stop-color="#fff" stop-opacity="1"/>'
            f'<stop offset="0.84" stop-color="#fff" stop-opacity="1"/>'
            f'<stop offset="1" stop-color="#000" stop-opacity="0"/>'
            f'</linearGradient>')
    return (
        f'<defs>{fade}'
        f'<mask id="rgMask{tag}" maskUnits="userSpaceOnUse" x="0" '
        f'y="{min(y - w, y + w):.0f}" width="{w}" height="{w * 2:.0f}">'
        f'<rect x="0" y="{min(y - w, y + w):.0f}" width="{w}" '
        f'height="{w * 2:.0f}" fill="url(#rgFade{tag})"/></mask>'
        f'<linearGradient id="ringSurf{tag}" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="#0d1420"/>'
        f'<stop offset="0.30" stop-color="#243449"/>'
        f'<stop offset="0.54" stop-color="#3c5570"/>'
        f'<stop offset="0.72" stop-color="#2b3d54"/>'
        f'<stop offset="1" stop-color="#0d1420"/>'
        f'</linearGradient>'
        f'<linearGradient id="ringHaze{tag}" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{BUNGIE}" stop-opacity="0"/>'
        f'<stop offset="0.5" stop-color="#6fa8cf" stop-opacity="0.10"/>'
        f'<stop offset="1" stop-color="{BUNGIE}" stop-opacity="0"/>'
        f'</linearGradient>'
        f'<linearGradient id="ringRim{tag}" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="#ffffff" stop-opacity="0"/>'
        f'<stop offset="0.34" stop-color="#dcefff" stop-opacity="0.50"/>'
        f'<stop offset="0.56" stop-color="#ffffff" stop-opacity="0.78"/>'
        f'<stop offset="0.78" stop-color="#bcd8ef" stop-opacity="0.34"/>'
        f'<stop offset="1" stop-color="#ffffff" stop-opacity="0"/>'
        f'</linearGradient></defs>'
        f'<g mask="url(#rgMask{tag})">'
        # haze sits outside the structure, so it goes down first
        f'<path d="{arc(R)}" fill="none" stroke="url(#ringHaze{tag})" '
        f'stroke-width="{band * 6:.1f}"/>'
        # the bulk: opaque, so it occludes the star field behind it
        f'<path d="{arc(R)}" fill="none" stroke="url(#ringSurf{tag})" '
        f'stroke-width="{band:.1f}"/>'
        # lit inner surface, a touch inboard of the centreline
        f'<path d="{arc(R - band * 0.18 * sign)}" fill="none" '
        f'stroke="url(#ringRim{tag})" stroke-width="{band * 0.30:.1f}" '
        f'opacity="0.22"/>'
        # the two rims
        f'<path d="{arc(R + band * 0.5 * sign)}" fill="none" '
        f'stroke="url(#ringRim{tag})" stroke-width="1.3"/>'
        f'<path d="{arc(R - band * 0.5 * sign)}" fill="none" '
        f'stroke="url(#ringRim{tag})" stroke-width="0.9" opacity="0.45"/>'
        f'</g>')


def sky_gradient(w: int, h: int, top_h: float) -> str:
    """The ground itself: lifted where the masthead sits, void further down."""
    stop = max(0.02, min(0.5, top_h / h))
    return (
        f'<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{LIFT}"/>'
        f'<stop offset="{stop * 0.75:.4f}" stop-color="{DEEP}"/>'
        f'<stop offset="{min(1.0, stop * 2.2):.4f}" stop-color="{DEEP}"/>'
        f'<stop offset="1" stop-color="{VOID}"/>'
        f'</linearGradient></defs>'
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="url(#sky)"/>')


def vignette(w: int, h: int, margin: float | None = None) -> str:
    """Darkens the outer margins so the data field reads as lit from within.

    `margin` caps how far the dark band reaches in from each edge. Left at
    6% of the canvas it reached to ~308px on a 5142px-wide poster -- past
    the 150px MARGIN the lower sections' own content starts at, so external-
    studio chips sitting near that edge were rendered under as much as 44%
    black on top of their own fill. The band should never reach past the
    point real content starts; callers with a narrower margin than 6% of
    their own width pass it explicitly.
    """
    band = w * 0.06 if margin is None else min(w * 0.06, margin)
    return (
        f'<defs><linearGradient id="vigL" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{VOID}" stop-opacity="0.85"/>'
        f'<stop offset="1" stop-color="{VOID}" stop-opacity="0"/></linearGradient>'
        f'<linearGradient id="vigR" x1="1" y1="0" x2="0" y2="0">'
        f'<stop offset="0" stop-color="{VOID}" stop-opacity="0.85"/>'
        f'<stop offset="1" stop-color="{VOID}" stop-opacity="0"/></linearGradient>'
        f'</defs>'
        f'<rect x="0" y="0" width="{band:.0f}" height="{h}" fill="url(#vigL)"/>'
        f'<rect x="{w - band:.0f}" y="0" width="{band:.0f}" height="{h}" '
        f'fill="url(#vigR)"/>')


# ----------------------------------------------------------- charge burst

def charge_burst(cx: float, cy: float, r: float = 560.0, seed: int = 7,
                 tag: str = "c", opacity: float = 1.0) -> str:
    """The array charging: a hot core throwing straight spikes of light.

    Taken from the cutscene rather than invented -- the effect is not a
    starburst with even rays but a scatter of thin streaks at unequal
    lengths, each brightest at its OUTER tip, which is what makes it read as
    matter being flung outward rather than as a drawn sun. The reference core
    is white-gold; this one is blue, to sit in the poster's palette and to
    answer the beam climbing toward it.

    Drawn behind the grid body so names stay legible on top of it.
    """
    rng = random.Random(seed)
    out = [
        f'<defs>'
        f'<radialGradient id="cbCore{tag}" cx="0.5" cy="0.5" r="0.5">'
        f'<stop offset="0" stop-color="#ffffff" stop-opacity="1"/>'
        f'<stop offset="0.18" stop-color="#dff6ff" stop-opacity="0.95"/>'
        f'<stop offset="0.42" stop-color="#5cc8f5" stop-opacity="0.55"/>'
        f'<stop offset="0.72" stop-color="#1d7fc4" stop-opacity="0.20"/>'
        f'<stop offset="1" stop-color="#0d4f8a" stop-opacity="0"/>'
        f'</radialGradient>'
        f'<radialGradient id="cbHalo{tag}" cx="0.5" cy="0.5" r="0.5">'
        f'<stop offset="0" stop-color="#4fb8f0" stop-opacity="0.30"/>'
        f'<stop offset="0.35" stop-color="#2f8fd8" stop-opacity="0.13"/>'
        f'<stop offset="1" stop-color="#12406e" stop-opacity="0"/>'
        f'</radialGradient></defs>']

    # the wide atmospheric halo
    out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r * 3.1:.0f}" '
               f'fill="url(#cbHalo{tag})" opacity="{0.9 * opacity:.2f}"/>')

    # spikes: unequal lengths, bright at the tip
    n = 56
    for i in range(n):
        a = (i / n) * 2 * math.pi + rng.uniform(-0.035, 0.035)
        r0 = r * rng.uniform(0.16, 0.30)
        r1 = r * rng.uniform(0.62, 1.95)
        w = rng.uniform(1.1, 3.0)
        x0, y0 = cx + r0 * math.cos(a), cy + r0 * math.sin(a)
        x1, y1 = cx + r1 * math.cos(a), cy + r1 * math.sin(a)
        gid = f"cbS{tag}{i}"
        out.append(
            f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" '
            f'x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}">'
            f'<stop offset="0" stop-color="#bfeaff" stop-opacity="0.05"/>'
            f'<stop offset="0.62" stop-color="#9fdcff" stop-opacity="0.42"/>'
            f'<stop offset="0.93" stop-color="#ffffff" stop-opacity="0.95"/>'
            f'<stop offset="1" stop-color="#ffffff" stop-opacity="0"/>'
            f'</linearGradient>')
        out.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" '
                   f'y2="{y1:.1f}" stroke="url(#{gid})" stroke-width="{w:.1f}" '
                   f'stroke-linecap="round" opacity="{opacity:.2f}"/>')
        # the bright head each streak carries
        out.append(f'<circle cx="{x1:.1f}" cy="{y1:.1f}" '
                   f'r="{w * rng.uniform(0.7, 1.3):.1f}" fill="#ffffff" '
                   f'opacity="{rng.uniform(0.5, 0.95) * opacity:.2f}"/>')

    # the core last, so it burns through its own spikes
    out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r * 0.86:.0f}" '
               f'fill="url(#cbCore{tag})" opacity="{opacity:.2f}"/>')
    # a small solid disc read as a hard-edged circle; it is now a short
    # gradient of its own so the centre has no visible boundary at all
    out.append(f'<defs><radialGradient id="cbHot{tag}" cx="0.5" cy="0.5" r="0.5">'
               f'<stop offset="0" stop-color="#ffffff" stop-opacity="1"/>'
               f'<stop offset="0.45" stop-color="#ffffff" stop-opacity="0.85"/>'
               f'<stop offset="1" stop-color="#eaf9ff" stop-opacity="0"/>'
               f'</radialGradient></defs>'
               f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r * 0.20:.0f}" '
               f'fill="url(#cbHot{tag})" opacity="{opacity:.2f}"/>')
    return "".join(out)


BEAM = "#4fd8ff"


def atmosphere(w: int, y0: float, y1: float) -> str:
    """The sky thickening as the poster falls toward the ring's surface.

    Space has no horizon, so the transition has to be carried entirely by
    hue: the void warms through deep indigo into a lit blue, the way an
    atmosphere does seen from above. It stays dark throughout -- the section
    below is full of small type, and a bright sky would cost every word its
    contrast.
    """
    return (
        f'<defs><linearGradient id="atmo" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#05070c" stop-opacity="0"/>'
        f'<stop offset="0.18" stop-color="#0a1526" stop-opacity="0.55"/>'
        f'<stop offset="0.45" stop-color="#102741" stop-opacity="0.75"/>'
        f'<stop offset="0.72" stop-color="#16405f" stop-opacity="0.72"/>'
        f'<stop offset="0.90" stop-color="#1d5a7c" stop-opacity="0.60"/>'
        f'<stop offset="1" stop-color="#26708f" stop-opacity="0.42"/>'
        f'</linearGradient></defs>'
        f'<rect x="0" y="{y0:.0f}" width="{w}" height="{y1 - y0:.0f}" '
        f'fill="url(#atmo)"/>')


def ring_surface(w: int, y: float, bottom: float) -> str:
    """The ring's near arc as ground, not as a band.

    The far side reads correctly as a thin band because it is thousands of
    kilometres away. The near side is underfoot, so drawing it the same way
    left the beam tower standing on a hairline with empty sky beneath it.
    This closes the arc down to the foot of the sheet and lights its upper
    edge, which is where the surface actually catches the sun.

    Land, water and structures belong on this plane. It is deliberately left
    as a lit surface for now so that art can be laid over it later without
    the geometry moving.
    """
    R = w * 2.9
    cx, cy = w * 0.5, y - R
    sweep = 0.42
    a0, a1 = math.pi / 2 - sweep, math.pi / 2 + sweep
    x0, y0 = cx + R * math.cos(a0), cy + R * math.sin(a0)
    x1, y1 = cx + R * math.cos(a1), cy + R * math.sin(a1)
    # walk the arc the short way, then close through the bottom corners
    path = (f'M {x1:.1f} {y1:.1f} A {R:.1f} {R:.1f} 0 0 0 {x0:.1f} {y0:.1f} '
            f'L {w + 40:.0f} {bottom + 40:.0f} L {-40:.0f} {bottom + 40:.0f} Z')
    rim = (f'M {x1:.1f} {y1:.1f} A {R:.1f} {R:.1f} 0 0 0 {x0:.1f} {y0:.1f}')
    return (
        f'<defs><linearGradient id="rsFill" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#2c4f68" stop-opacity="0.92"/>'
        f'<stop offset="0.30" stop-color="#1b3346" stop-opacity="0.95"/>'
        f'<stop offset="1" stop-color="#0a141f" stop-opacity="1"/>'
        f'</linearGradient>'
        f'<linearGradient id="rsRim" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="#7fc4e8" stop-opacity="0"/>'
        f'<stop offset="0.30" stop-color="#bfe6ff" stop-opacity="0.55"/>'
        f'<stop offset="0.52" stop-color="#eaf8ff" stop-opacity="0.75"/>'
        f'<stop offset="0.74" stop-color="#bfe6ff" stop-opacity="0.45"/>'
        f'<stop offset="1" stop-color="#7fc4e8" stop-opacity="0"/>'
        f'</linearGradient></defs>'
        f'<path d="{path}" fill="url(#rsFill)"/>'
        f'<path d="{rim}" fill="none" stroke="url(#rsRim)" stroke-width="2.4"/>'
        f'<path d="{rim}" fill="none" stroke="url(#rsRim)" stroke-width="12" '
        f'opacity="0.16"/>')


# --------------------------------------------------- beam tower (real art)

TOWER_STRUCTURE = "beam-tower-structure.webp"
TOWER_LIGHTS = "beam-tower-lights.webp"

# The beam axis, as fractions of the art. These are measured constants, not
# guesses -- taken off the art back when the shaft was still painted into the
# lights layer, spanning x 1151..1366 and ending at y 4044 of a 3100x5036
# image. The shaft has since been stripped out so the poster can draw the
# whole thing, which means the layers no longer contain anything to measure.
# Recording the numbers is the only way the emitter stays where the artist
# put it. Both layers share one canvas, so these hold for either.
# Measured off the STRUCTURE layer, not the lights: the widest interior gap
# between the two blades, sampled down the tower, centres at 0.414-0.430 and
# averages 0.4216. The earlier 0.4060 came from the old flattened artwork's
# painted shaft and sat about 15px left of the channel, which is what the
# by-eye nudge had been compensating for. The lights strip is at 0.378 and is
# the mast ladder, not the beam -- using it would have been further wrong.
BEAM_AXIS_X = 0.4216          # centre of the channel the shaft leaves through
BEAM_AXIS_W = 0.0694          # its width
BEAM_EMITTER_Y = 0.8480       # where it leaves the structure


def beam_tower_image(target_h: int, darken: float = 0.34, cache_dir=None):
    """Prepare the beam tower art, structure and lights as separate layers.

    The art arrives already split, which is what makes this honest. The
    structure is concept art at median luma 196 against a ground of 13 --
    dropped in untouched it reads as a white cutout brighter than the title
    -- so it is darkened and pushed slightly blue, lit as if only by the ring
    and its own beam. The lights layer is left alone: it is the one thing in
    the frame that should be bright.

    An earlier version had to separate the beam out of a single flattened
    image by hue, which worked but could only ever approximate the edges.
    With real layers the darkening cannot touch the beam at all.

    Returns both layers plus the beam geometry, measured off the lights
    layer, so the sheet can continue the beam upward from exactly where the
    art stops emitting it.
    """
    import base64
    import io
    from pathlib import Path as _P

    import numpy as np
    from PIL import Image

    root = _P(__file__).resolve().parents[1]
    Image.MAX_IMAGE_PIXELS = None
    cache_dir = cache_dir or (root / "render" / ".logocache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    lights = Image.open(root / "art" / "beam-tower" / TOWER_LIGHTS).convert("RGBA")

    src = root / "art" / "beam-tower" / TOWER_STRUCTURE
    stamp = f"twr-{int(src.stat().st_mtime)}-{target_h}-{int(darken * 100)}.png"
    cached = cache_dir / stamp
    if cached.exists():
        st_im = Image.open(cached).convert("RGBA")
    else:
        st = Image.open(src).convert("RGBA")
        a0 = np.array(st).astype(np.float32)
        tint = np.array([0.82, 0.93, 1.12], dtype=np.float32)
        rgb = np.clip(a0[..., :3] * darken * tint, 0, 255)
        arr = np.concatenate([rgb, a0[..., 3:]], 2).astype("uint8")
        tw = max(1, round(target_h * st.width / st.height))
        st_im = Image.fromarray(arr, "RGBA").resize((tw, target_h), Image.LANCZOS)
        st_im.save(cached, optimize=True)

    lw = max(1, round(target_h * lights.width / lights.height))
    li_im = lights.resize((lw, target_h), Image.LANCZOS)

    def uri(img):
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(
            buf.getvalue()).decode("ascii")

    return {"structure": uri(st_im), "lights": uri(li_im),
            "w": st_im.width, "h": st_im.height,
            "beam_x": BEAM_AXIS_X, "beam_w": BEAM_AXIS_W,
            "emitter": BEAM_EMITTER_Y}


def tower_beam(x: float, glow_from: float, core_from: float, y_to: float,
               core_w: float, tag: str = "tb") -> str:
    """Continue the art's beam upward to the charging array.

    The two halves of this beam have to meet invisibly, and they fail in two
    different ways, so they start at two different heights:

      the CORE must match the art's shaft exactly in width and brightness,
      so it begins precisely where the art stops emitting and fades upward
      from there. Any overlap would double the opacity and show as a bright
      band; any gap would show as a break.

      the GLOW must not appear at a stroke. The art's shaft has none, so a
      glow switched on at the junction reads as a seam even when the core
      matches. It starts far down inside the art and ramps up from nothing,
      hidden behind the structure, and is already established by the time
      the shaft clears the tower.
    """
    out = [f'<defs>'
           f'<linearGradient id="tbX{tag}" x1="0" y1="0" x2="1" y2="0">'
           f'<stop offset="0" stop-color="#000"/>'
           f'<stop offset="0.5" stop-color="#fff"/>'
           f'<stop offset="1" stop-color="#000"/></linearGradient>'
           f'<linearGradient id="tbV{tag}" x1="0" y1="1" x2="0" y2="0">'
           f'<stop offset="0" stop-color="{BEAM}" stop-opacity="0"/>'
           f'<stop offset="0.03" stop-color="{BEAM}" stop-opacity="0.07"/>'
           f'<stop offset="0.07" stop-color="{BEAM}" stop-opacity="0.19"/>'
           f'<stop offset="0.12" stop-color="{BEAM}" stop-opacity="0.30"/>'
           f'<stop offset="0.19" stop-color="{BEAM}" stop-opacity="0.38"/>'
           f'<stop offset="0.28" stop-color="{BEAM}" stop-opacity="0.35"/>'
           f'<stop offset="0.42" stop-color="{BEAM}" stop-opacity="0.26"/>'
           f'<stop offset="0.62" stop-color="{BEAM}" stop-opacity="0.16"/>'
           f'<stop offset="0.82" stop-color="{BEAM}" stop-opacity="0.09"/>'
           f'<stop offset="1" stop-color="{BEAM}" stop-opacity="0.04"/>'
           f'</linearGradient>'
           f'<linearGradient id="tbC{tag}" x1="0" y1="1" x2="0" y2="0">'
           f'<stop offset="0" stop-color="{BEAM}" stop-opacity="0.88"/>'
           f'<stop offset="0.05" stop-color="#5cdcff" stop-opacity="0.84"/>'
           f'<stop offset="0.13" stop-color="#6fe0ff" stop-opacity="0.74"/>'
           f'<stop offset="0.24" stop-color="#82e5ff" stop-opacity="0.62"/>'
           f'<stop offset="0.38" stop-color="#8ae7ff" stop-opacity="0.50"/>'
           f'<stop offset="0.55" stop-color="#7bdcfa" stop-opacity="0.37"/>'
           f'<stop offset="0.74" stop-color="#68d1f6" stop-opacity="0.25"/>'
           f'<stop offset="1" stop-color="{BEAM}" stop-opacity="0.12"/>'
           f'</linearGradient></defs>']

    def band(y0, y1, half, grad, op, i):
        h = y0 - y1
        if h <= 0:
            return ""
        return (f'<mask id="tbM{tag}{i}" maskUnits="userSpaceOnUse" '
                f'x="{x - half:.1f}" y="{y1:.0f}" width="{half * 2:.1f}" '
                f'height="{h:.0f}"><rect x="{x - half:.1f}" y="{y1:.0f}" '
                f'width="{half * 2:.1f}" height="{h:.0f}" '
                f'fill="url(#tbX{tag})"/></mask>'
                f'<rect x="{x - half:.1f}" y="{y1:.0f}" width="{half * 2:.1f}" '
                f'height="{h:.0f}" fill="url(#{grad}{tag})" opacity="{op}" '
                f'mask="url(#tbM{tag}{i})"/>')

    out.append(band(glow_from, y_to, core_w * 3.6, "tbV", 0.32, 0))
    out.append(band(glow_from, y_to, core_w * 1.25, "tbV", 0.72, 1))
    # the core: exactly the art's width, starting exactly where it leaves off
    out.append(band(core_from, y_to, core_w * 0.5, "tbC", 1.0, 2))
    return "".join(out)


# ------------------------------------------------- the ring, as one circle

def ring_pair(w: int, y_top: float, y_bottom: float, band_frac: float = 0.030):
    """Both visible arcs of ONE ring, derived from a single circle.

    The earlier version drew two unrelated arcs at an invented radius, which
    is not a ring: nothing tied the curve at the top of the sheet to the curve
    at the foot, so the two could not have belonged to the same object.

    Here the circle is defined by where the poster meets it. Its top sits at
    y_top and its bottom at y_bottom, so

        R  = (y_bottom - y_top) / 2
        c  = (w/2, (y_top + y_bottom) / 2)

    and the two arcs are literally the top and bottom of that circle. The
    consequence the geometry has to satisfy is the obvious one: make the
    sheet as wide as it is tall and the arcs close into a full circle,
    because then R equals w/2 and the curves meet at the left and right
    edges. Any other radius would be a drawing of a ring rather than a ring.

    Returns (svg, R). At poster proportions R is enormous and both arcs are
    correspondingly shallow, which is exactly right for something whose
    diameter is measured in thousands of kilometres.
    """
    R = (y_bottom - y_top) / 2.0
    cx, cy = w / 2.0, (y_top + y_bottom) / 2.0
    band = w * band_frac
    half = min(w / 2.0, R * 0.999)
    # x offset from the centre where the circle leaves the sheet
    dx = half
    dy = math.sqrt(max(R * R - dx * dx, 0.0))

    def arc(radius: float, top: bool) -> str:
        d = math.sqrt(max(radius * radius - dx * dx, 0.0))
        y = cy - d if top else cy + d
        ytip = cy - radius if top else cy + radius
        sweep = 1 if top else 0
        return (f'M {cx - dx:.1f} {y:.1f} A {radius:.1f} {radius:.1f} 0 0 '
                f'{sweep} {cx + dx:.1f} {y:.1f}')

    out = []
    for tag, top in (("t", True), ("b", False)):
        sign = -1.0 if top else 1.0
        out.append(
            f'<defs>'
            f'<linearGradient id="rgFade{tag}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="#000" stop-opacity="0"/>'
            f'<stop offset="0.14" stop-color="#fff" stop-opacity="1"/>'
            f'<stop offset="0.86" stop-color="#fff" stop-opacity="1"/>'
            f'<stop offset="1" stop-color="#000" stop-opacity="0"/>'
            f'</linearGradient>'
            f'<mask id="rgMask{tag}" maskUnits="userSpaceOnUse" x="0" '
            f'y="{cy - R - band * 4:.0f}" width="{w}" '
            f'height="{2 * R + band * 8:.0f}">'
            f'<rect x="0" y="{cy - R - band * 4:.0f}" width="{w}" '
            f'height="{2 * R + band * 8:.0f}" fill="url(#rgFade{tag})"/></mask>'
            f'<linearGradient id="rgSurf{tag}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="#0d1420"/>'
            f'<stop offset="0.30" stop-color="#243449"/>'
            f'<stop offset="0.54" stop-color="#3c5570"/>'
            f'<stop offset="0.72" stop-color="#2b3d54"/>'
            f'<stop offset="1" stop-color="#0d1420"/></linearGradient>'
            f'<linearGradient id="rgHaze{tag}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="{BUNGIE}" stop-opacity="0"/>'
            f'<stop offset="0.5" stop-color="#6fa8cf" stop-opacity="0.10"/>'
            f'<stop offset="1" stop-color="{BUNGIE}" stop-opacity="0"/>'
            f'</linearGradient>'
            f'<linearGradient id="rgRim{tag}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="#ffffff" stop-opacity="0"/>'
            f'<stop offset="0.32" stop-color="#dcefff" stop-opacity="0.50"/>'
            f'<stop offset="0.55" stop-color="#ffffff" stop-opacity="0.80"/>'
            f'<stop offset="0.78" stop-color="#bcd8ef" stop-opacity="0.34"/>'
            f'<stop offset="1" stop-color="#ffffff" stop-opacity="0"/>'
            f'</linearGradient></defs>'
            f'<g mask="url(#rgMask{tag})">'
            f'<path d="{arc(R, top)}" fill="none" stroke="url(#rgHaze{tag})" '
            f'stroke-width="{band * 6:.1f}"/>'
            f'<path d="{arc(R, top)}" fill="none" stroke="url(#rgSurf{tag})" '
            f'stroke-width="{band:.1f}"/>'
            f'<path d="{arc(R + band * 0.5 * sign, top)}" fill="none" '
            f'stroke="url(#rgRim{tag})" stroke-width="1.6"/>'
            f'<path d="{arc(R - band * 0.5 * sign, top)}" fill="none" '
            f'stroke="url(#rgRim{tag})" stroke-width="1.0" opacity="0.45"/>'
            f'</g>')
    return "".join(out), R


def clouds(w: int, y0: float, y1: float, seed: int = 63) -> str:
    """Stylised weather over the ring, drawn as banks rather than as fog.

    The first attempt was a blurred noise field, which is what an atmosphere
    looks like from inside and not what a cloud looks like from above: it read
    as haze on the lens. These are flat lenticular banks with a lit crown and
    a flat underside, stacked and thinning upward, which is the shape the eye
    actually names as cloud.

    The band it occupies stops at the ring's surface line, and it is drawn
    before the surface, so the weather sits in the sky behind the ring instead
    of lying across it.
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    sw = 900
    sh = max(16, round(sw * (y1 - y0) / w))
    rng = np.random.default_rng(seed)
    canvas = Image.new("L", (sw, sh), 0)
    d = ImageDraw.Draw(canvas)

    for band in range(5):
        # lower banks are wider, denser and brighter; higher ones thin out
        t = band / 4.0
        yc = sh * (0.95 - t * 0.60)
        val = int(255 * (0.95 - t * 0.55))
        for _ in range(int(7 - t * 3)):
            cx = rng.uniform(-0.15, 1.15) * sw
            rx = rng.uniform(sw * 0.10, sw * 0.26) * (1.0 - t * 0.35)
            ry = rx * rng.uniform(0.10, 0.19)
            yy = yc + rng.uniform(-sh * 0.035, sh * 0.035)
            # a bank is a run of overlapping lobes sitting on a flat base
            for k in range(4):
                lx = cx + (k - 1.5) * rx * 0.52
                lr = rx * (0.55 + 0.45 * rng.random()) * 0.6
                lry = ry * (0.75 + 0.6 * rng.random())
                d.ellipse([lx - lr, yy - lry, lx + lr, yy + lry * 0.55], fill=val)
            d.rectangle([cx - rx, yy, cx + rx, yy + ry * 0.5], fill=val)

    soft = canvas.filter(ImageFilter.GaussianBlur(sw * 0.006))
    a = np.asarray(soft).astype(np.float32) / 255.0
    # fade in from the top so the highest bank does not end on a line
    a = a * np.clip(np.linspace(0.0, 1.0, sh) * 2.2, 0, 1)[:, None]
    rgba = np.zeros((sh, sw, 4), dtype=np.float32)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = 176.0, 205.0, 228.0
    rgba[..., 3] = a * 150
    buf = io.BytesIO()
    Image.fromarray(rgba.astype("uint8"), "RGBA").save(buf, format="PNG",
                                                       optimize=True)
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    return (f'<image x="0" y="{y0:.0f}" width="{w}" height="{y1 - y0:.0f}" '
            f'href="{uri}" preserveAspectRatio="none" opacity="0.5"/>')

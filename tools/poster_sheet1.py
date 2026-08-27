"""The poster: masthead, career grid, and the sections that follow it.

This module reuses build_career_grid's LAYOUT -- which row a person lands on,
which column slots they occupy, where the overflow blocks start -- and draws
none of its presentation. The layout is the part that carries meaning; the
flat bands, the 8px Segoe and the hard-edged markers were only ever one way
of showing it.

Geometry is restated rather than imported. The page packs columns at a 210px
pitch because a browser has to scroll it; a poster does not, and at 210 the
game logos overran their columns. The pitch here is 260, which also buys the
name gutter another 50px for the 42-character worst case.

Draw order matters and is not incidental:

    sky -> rings -> era washes -> bays -> column rules
        -> masthead type -> grid body -> vignette -> LOGOS LAST

The logos go last because everything else on the sheet is translucent.
Anything drawn over a logo greys it out, and these are the one element that
has to look like itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import cover_art
import poster_theme as T
from build_career_grid import (COLUMNS, OVERFLOW_PER_ROW, era_of_col, fmt)
from poster_sheet2 import ADV_NAMES_CHIP

# ---------------------------------------------------------------- geometry

MARGIN = 150
X0 = 360                              # centre of the first column
PITCH = 402                           # the page uses 210; the cover slices need the room
# Symmetric about the columns, not about an arbitrary right margin: the
# canvas centre has to BE the grid's centre, because that is where the beam
# and the charging array are drawn. Widening the pitch left the old formula
# with a 197px left margin and a 149px right one, which put the beam 24px off
# the middle of the grid it runs through.
CANVAS_W = X0 + (X0 + PITCH * (len(COLUMNS) - 1))

TITLE_Y = 372
STUDIO_ROW_Y = 986                    # company marks, over the games they made
GAME_ROW_Y = 1068                     # game marks; was 164px below the studio row, now 82
HEAD_LOGO_H = 200                     # room for the tallest aligned mark
LOGO_H_TARGET = 56                    # every wordmark's "H" is drawn this wide; -10%, Halo 4 was clipping
LOGO_ANCHOR_DY = 84                   # the dot in every "O" lands on this line
HEAD_LOGO_W = PITCH - 24

# The name chip: a coloured, bordered box in the same language as the
# external-studio chips on the credits page, with the person's name set
# inside it instead of beside a small marker. Bigger than the 11px the name
# used to be drawn at, since it is now the only label carrying the name.
# Every chip on the sheet is the same width -- see grid_body -- so CHIP_PAD
# only has to clear the SINGLE longest name anywhere on the grid, not each
# chip's own text.
CHIP_SIZE = 13
CHIP_H = 18
CHIP_PAD = 7
CHIP_INK = "#eef3fa"          # whiter than T.INK -- the name is the only
                              # thing in the chip, so it gets full contrast

# The page packs rows at 11px because its markers are thin dots. A chip
# with real text in it needs real line height -- at 11px two consecutive
# rows' chips overlapped into one unreadable smear. This is a poster-only
# override; the page's own ROW_H is untouched.
ROW_H = 22
HEAD_RULE_Y = GAME_ROW_Y + HEAD_LOGO_H + 132
HEADER_TOP = STUDIO_ROW_Y - 74        # where era light starts
ROW_Y0 = HEAD_RULE_Y + 48

RING_TOP_Y = 196                      # where the ring's near edge crosses
RING_BOTTOM_INSET = 430               # the far side, at the foot of the sheet
TOWER_H = 1560                        # the beam tower on the ring's near arc

# The art's emitter sits at 0.406 of its own width, LEFT of its centre, so
# centring the artwork necessarily throws the beam 90px off the sheet's
# middle -- and the charging array it is aimed at is drawn dead centre. The
# beam is therefore the anchor: it is placed on the centre line and the
# artwork is positioned from it, rather than the other way round.
#
# There is no by-eye nudge any more. BEAM_AXIS_X is measured from the gap
# between the artwork's own blades, so the shaft leaves through the channel
# by construction rather than by correction.

ERA_ORDER = ["Bungie", "343 Industries", "Halo Studios"]
ERA_SPAN: dict = {}
for _i, (_g, _l, _y, _e) in enumerate(COLUMNS):
    _lo, _hi = ERA_SPAN.get(_e, (_i, _i))
    ERA_SPAN[_e] = (min(_lo, _i), max(_hi, _i))


def cx(i: int) -> float:
    return X0 + PITCH * i




def era_center(era: str) -> float:
    lo, hi = ERA_SPAN[era]
    return (cx(lo) + cx(hi)) / 2


def era_years(era: str) -> str:
    lo, hi = ERA_SPAN[era]
    a, b = COLUMNS[lo][2], COLUMNS[hi][2]
    return a if a == b else f"{a}–{b}"


# ------------------------------------------------------------------ layers

def era_washes(total_h: float) -> str:
    out = ["<defs>"]
    for era in ERA_ORDER:
        col, key = T.ERA_COLOR[era], era.replace(" ", "")
        out.append(
            f'<linearGradient id="wash{key}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{col}" stop-opacity="0.115"/>'
            f'<stop offset="0.04" stop-color="{col}" stop-opacity="0.055"/>'
            f'<stop offset="0.40" stop-color="{col}" stop-opacity="0.020"/>'
            f'<stop offset="1" stop-color="{col}" stop-opacity="0"/>'
            f'</linearGradient>')
    out.append("</defs>")
    for era in ERA_ORDER:
        lo, hi = ERA_SPAN[era]
        x0, x1 = cx(lo) - PITCH / 2, cx(hi) + PITCH / 2
        key = era.replace(" ", "")
        out.append(f'<rect x="{x0:.0f}" y="{HEADER_TOP:.0f}" '
                   f'width="{x1 - x0:.0f}" height="{total_h - HEADER_TOP:.0f}" '
                   f'fill="url(#wash{key})"/>')
    return "".join(out)


def column_bays(total_h: float) -> str:
    """A shaft of light under each game logo, in that game's era colour.

    A plain rect gives the shaft two hard vertical edges and the column reads
    as a box, so each one is masked with a horizontal ramp.
    """
    out = ["<defs>"]
    for i, (_g, _l, _y, era) in enumerate(COLUMNS):
        col = T.ERA_COLOR[era]
        out.append(
            f'<linearGradient id="bay{i}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{col}" stop-opacity="0.19"/>'
            f'<stop offset="0.045" stop-color="{col}" stop-opacity="0.105"/>'
            f'<stop offset="0.14" stop-color="{col}" stop-opacity="0.050"/>'
            f'<stop offset="0.38" stop-color="{col}" stop-opacity="0.020"/>'
            f'<stop offset="1" stop-color="{col}" stop-opacity="0"/>'
            f'</linearGradient>')
    out.append('<linearGradient id="bayFade" x1="0" y1="0" x2="1" y2="0">'
               '<stop offset="0" stop-color="#000"/>'
               '<stop offset="0.24" stop-color="#fff"/>'
               '<stop offset="0.76" stop-color="#fff"/>'
               '<stop offset="1" stop-color="#000"/></linearGradient></defs>')
    bay_h = min(3000.0, total_h - HEADER_TOP)
    w = PITCH - 8
    for i in range(len(COLUMNS)):
        x0 = cx(i) - w / 2
        out.append(
            f'<mask id="bm{i}" maskUnits="userSpaceOnUse" x="{x0:.0f}" '
            f'y="{HEADER_TOP:.0f}" width="{w}" height="{bay_h:.0f}">'
            f'<rect x="{x0:.0f}" y="{HEADER_TOP:.0f}" width="{w}" '
            f'height="{bay_h:.0f}" fill="url(#bayFade)"/></mask>'
            f'<rect x="{x0:.0f}" y="{HEADER_TOP:.0f}" width="{w}" '
            f'height="{bay_h:.0f}" fill="url(#bay{i})" mask="url(#bm{i})"/>')
    return "".join(out)


def column_rules(bottom: float) -> str:
    out = ['<defs><linearGradient id="colRule" x1="0" y1="0" x2="0" y2="1">'
           f'<stop offset="0" stop-color="{T.INK}" stop-opacity="0.10"/>'
           f'<stop offset="0.5" stop-color="{T.INK}" stop-opacity="0.045"/>'
           f'<stop offset="1" stop-color="{T.INK}" stop-opacity="0.02"/>'
           "</linearGradient></defs>"]
    for i in range(len(COLUMNS)):
        out.append(f'<line x1="{cx(i):.0f}" y1="{HEAD_RULE_Y:.0f}" '
                   f'x2="{cx(i):.0f}" y2="{bottom:.0f}" '
                   f'stroke="url(#colRule)" stroke-width="1"/>')
    return "".join(out)


# -------------------------------------------------------------------- grid

def _ink(p) -> str:
    """Every name is set in the same ink.

    Colouring the name as well as the marker said the same thing twice and
    made two rows of the same grid look like two kinds of type. The marker
    carries the classification; the name is just the person.
    """
    return T.INK


def _mark(p, col: int) -> str:
    """What this person did on this game.

    The poster kept colouring by era after the page had moved to role, so the
    two disagreed about the same grid. Era is already carried by the column,
    the wash and the studio bracket; the marker is the only channel role has.
    """
    roles = p.get("roles")
    if roles:
        cls = roles.get(col)
        if cls:
            return T.ROLE_COLOR.get(cls, T.ROLE_COLOR["unspecified"])
    if p["community"]:
        return T.COMMUNITY
    if p.get("publisher"):
        return T.PUBLISHER
    return T.ERA_COLOR[era_of_col(col)]


def _chip(x: float, y: float, color: str, text: str, chip_w: float,
         badge: bool = False) -> str:
    """A person's name, boxed the way an external-studio credit is: a
    coloured, bordered rectangle with the label set inside it, centred on x
    -- the column this credit belongs to -- so the game a chip sits under
    is readable without tracing a line to either side.

    Every chip on the sheet shares the same `chip_w`, sized to the longest
    name that has to fit anywhere on it. A short name sits in a box wider
    than it needs; the alternative -- every chip its own width -- made
    neighbouring games line up differently column to column, which is worse
    than the wasted space.

    Drawn as an OPAQUE backing rect first, in the sky's own field colour,
    then the translucent coloured rect on top of that. Without the opaque
    backing the connector line running through a person's row showed
    through the chip's fill, since that fill alone is only 16% opaque.

    `badge` marks this person's ONLY credit as also reprinted somewhere,
    without saying where -- see REPRINT_R below for why it can't say more.
    """
    x0 = x - chip_w / 2
    y0 = y - CHIP_H / 2
    out = (f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{chip_w:.1f}" '
          f'height="{CHIP_H:.0f}" rx="3" fill="{T.DEEP}"/>'
          f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{chip_w:.1f}" '
          f'height="{CHIP_H:.0f}" rx="3" fill="{color}" fill-opacity="0.16" '
          f'stroke="{color}" stroke-width="1" stroke-opacity="0.7"/>'
          f'<text x="{x:.1f}" y="{y + CHIP_SIZE * 0.34:.1f}" '
          f'text-anchor="middle" font-size="{CHIP_SIZE}" fill="{CHIP_INK}" '
          f'font-family="{T.NAMES}">{T.esc(text)}</text>')
    if badge:
        # Inside the chip, just past the name's own right edge -- estimated
        # from its length the same way a studio chip's text is measured,
        # since a per-name real measurement isn't available here. Clamped so
        # a name close to chip_w's own limit never pushes the dot outside
        # the box it's meant to sit inside.
        text_w = len(text) * CHIP_SIZE * ADV_NAMES_CHIP
        bx = min(x + text_w / 2 + REPRINT_R + 14,
                x0 + chip_w - REPRINT_R - 3)
        out += (f'<circle cx="{bx:.1f}" cy="{y:.1f}" r="{REPRINT_R + 2:.1f}" '
               f'fill="{T.GOLD}" opacity="0.28"/>'
               f'<circle cx="{bx:.1f}" cy="{y:.1f}" r="{REPRINT_R - 1:.1f}" '
               f'fill="{T.GOLD}" stroke="{T.DEEP}" stroke-width="1"/>')
    return out


# Reprint markers, gold like the connector lines they are deliberately NOT
# drawn as -- see build_career_grid.REPRINT_MAP. A person credited on 2+
# games gets an actual dot in every reprint column, since their row already
# reserves that space. A single-credit person doesn't get one: reserving a
# column for them the way a real second credit would have meant promoting
# ~1,150 people out of the compact single-column packing into full rows of
# their own, which would have grown the grid by roughly its own height
# again just to mark a handful of dots. They get a small badge on their one
# chip instead -- reprinted somewhere, unspecified where.
REPRINT_R = 4.5


def _reprint_dot(x: float, y: float) -> str:
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{REPRINT_R + 3:.1f}" '
           f'fill="{T.GOLD}" opacity="0.18"/>'
           f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{REPRINT_R:.1f}" '
           f'fill="{T.GOLD}"/>')


def _person(p, y: float, chip_w: float) -> list:
    cols, out = p["cols"], []
    for a, b in zip(cols, cols[1:]):
        x1, x2 = cx(a), cx(b)
        if b - a == 1:
            out.append(f'<line x1="{x1:.0f}" y1="{y:.1f}" x2="{x2:.0f}" '
                       f'y2="{y:.1f}" stroke="{T.GOLD}" stroke-width="5" '
                       f'opacity="0.13"/>')
            out.append(f'<line x1="{x1:.0f}" y1="{y:.1f}" x2="{x2:.0f}" '
                       f'y2="{y:.1f}" stroke="{T.GOLD}" stroke-width="1.7" '
                       f'opacity="0.95"/>')
        else:
            out.append(f'<line x1="{x1:.0f}" y1="{y:.1f}" x2="{x2:.0f}" '
                       f'y2="{y:.1f}" stroke="{T.GAP_LINE}" '
                       f'stroke-width="2.4" opacity="0.58" '
                       f'stroke-dasharray="3.5,4.5"/>')
    # A real dot for every reprint column only makes sense for someone who
    # already spans 2+ columns -- their row reserves those cells (see
    # build_career_grid.layout). A single-column person's row reserves
    # nothing beyond their one real column, so the same dot here could land
    # on whatever else was packed into that cell; they get the chip badge
    # instead, same as in the overflow block (_slot).
    if len(cols) >= 2:
        for c in p.get("reprint_cols") or ():
            out.append(_reprint_dot(cx(c), y))
    # The name reappears once per credit, each chip centred on the game it
    # names -- not just at the row's ends -- so reading one column at a time
    # never means looking away from it to find whose row this is.
    for c in cols:
        out.append(_chip(cx(c), y, _mark(p, c), p["name"], chip_w,
                         badge=len(cols) == 1 and bool(p.get("reprint_cols"))))
    return out


def _slot(p, slot: int, y: float, chip_w: float) -> list:
    return [_chip(cx(slot), y, _mark(p, p["cols"][0]), p["name"], chip_w,
                  badge=bool(p.get("reprint_cols")))]


# The page's overflow-block spacing (OVERFLOW_GAP, OVERFLOW_RULE_DY,
# SUB_LABEL_DY, SUB_GAP in build_career_grid.py) was tuned for its own tiny
# type -- an OVERFLOW header a few px tall, column labels smaller still. At
# poster scale, with both bumped up for legibility, those page offsets left
# the header and the first column's own label only ~5px apart: close enough
# to overlap. Overridden here rather than imported, the same way ROW_H is.
OVERFLOW_GAP_POSTER = 110.0
OVERFLOW_RULE_DY = 16.5
SUB_LABEL_DY_POSTER = -22.0
SUB_GAP_POSTER = 46.0


def grid_body(rows, overflow, section_at, studio_small):
    out = []
    # One width for every chip on the sheet, sized off the single longest
    # name that will ever have to fit in one -- see _chip for why uniform
    # beats per-name.
    chip_w = max((len(p["name"]) for row in rows for p in row),
                default=0)
    chip_w = max(chip_w, max((len(p["name"]) for people in overflow.values()
                             for p in people), default=0))
    chip_w = chip_w * CHIP_SIZE * ADV_NAMES_CHIP + CHIP_PAD * 2
    last_y = ROW_Y0 + ROW_H * (len(rows) - 1)
    # where the cover washes and column rules stop: the bottom of the named
    # grid, before the overflow block, so the art does not run underneath it
    grid_before_overflow = last_y
    cursor = last_y + OVERFLOW_GAP_POSTER + 40
    plan = []
    for c in sorted(overflow):
        people = overflow[c]
        n = (len(people) + OVERFLOW_PER_ROW - 1) // OVERFLOW_PER_ROW
        plan.append((c, people, cursor, n))
        cursor += ROW_H * (n - 1) + SUB_GAP_POSTER + 20
    grid_end = (plan[-1][2] + ROW_H * (plan[-1][3] - 1)) if plan else last_y

    for ri, people in enumerate(rows):
        y = ROW_Y0 + ROW_H * ri
        for p in people:
            out.extend(_person(p, y, chip_w))

    if plan:
        ry = last_y + OVERFLOW_RULE_DY + 26
        out.append(f'<line x1="{MARGIN}" y1="{ry:.0f}" '
                   f'x2="{CANVAS_W - MARGIN}" y2="{ry:.0f}" stroke="{T.GOLD}" '
                   f'stroke-width="1.6" opacity="0.5"/>')
        total_ov = sum(len(p) for p in overflow.values())
        out.append(f'<text x="{MARGIN}" y="{ry + 30:.0f}" font-size="19" '
                   f'font-weight="700" fill="{T.GOLD}" letter-spacing="2.4" '
                   f'font-family="{T.DISPLAY}">OVERFLOW</text>')
        out.append(f'<text x="{MARGIN + 190}" y="{ry + 30:.0f}" font-size="13" '
                   f'fill="{T.INK_DIM}" font-family="{T.MONO}">{fmt(total_ov)} '
                   f'more people credited on one game only, no room left '
                   f'above</text>')
        for c, people, first_y, n_rows in plan:
            era = era_of_col(c)
            out.append(f'<text x="{MARGIN}" y="{first_y + SUB_LABEL_DY_POSTER - 6:.1f}" '
                       f'font-size="15" font-weight="600" '
                       f'fill="{T.ERA_COLOR[era]}" letter-spacing="1.4" '
                       f'font-family="{T.DISPLAY}">{T.esc(COLUMNS[c][1])}</text>')
            out.append(f'<text x="{MARGIN + 420}" '
                       f'y="{first_y + SUB_LABEL_DY_POSTER - 6:.1f}" '
                       f'font-size="12" fill="{T.INK_DIM}" '
                       f'font-family="{T.MONO}">{fmt(len(people))} people</text>')
            for idx, p in enumerate(people):
                r, k = divmod(idx, OVERFLOW_PER_ROW)
                out.extend(_slot(p, k, first_y + ROW_H * r, chip_w))
    return "".join(out), grid_end, grid_before_overflow


# ---------------------------------------------------------------- masthead

def _legend(mid: float, y: float) -> str:
    """The key. What a chip's own colour and border mean is explained where
    the role key already answers that; the only thing left to say here is
    what the two connector lines between chips mean."""
    items = [("solid", T.GOLD, "credited on the very next game"),
            ("dash", T.GAP_LINE, "returned after a gap"),
            ("dot", T.GOLD, "credits reprinted from an earlier game")]
    total = sum(64 + len(l) * 9.0 for _k, _c, l in items)
    x = mid - total / 2
    out = [f'<rect x="{x - 48:.0f}" y="{y - 40:.0f}" width="{total + 96:.0f}" '
           f'height="80" rx="3" fill="#0b111c" fill-opacity="0.55" '
           f'stroke="{T.RULE}" stroke-width="1"/>']
    for kind, col, label in items:
        if kind == "solid":
            out.append(f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x + 30:.0f}" '
                       f'y2="{y:.0f}" stroke="{col}" stroke-width="10" '
                       f'opacity="0.15"/>'
                       f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x + 30:.0f}" '
                       f'y2="{y:.0f}" stroke="{col}" stroke-width="3"/>')
        elif kind == "dot":
            out.append(_reprint_dot(x + 15, y))
        else:
            out.append(f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x + 30:.0f}" '
                       f'y2="{y:.0f}" stroke="{col}" stroke-width="2" '
                       f'opacity="0.75" stroke-dasharray="5,5"/>')
        out.append(f'<text x="{x + 42:.0f}" y="{y + 6:.0f}" font-size="18" '
                   f'fill="{T.INK}" opacity="0.85" font-family="{T.NAMES}">'
                   f'{T.esc(label)}</text>')
        x += 64 + len(label) * 9.0
    return "".join(out)


def _role_key(mid: float, y: float, totals=None) -> str:
    """Every role class and its colour, in the order a game is made in.

    The same key the page carries. Without it the marker colours on this
    sheet mean nothing at all -- there is no other place on the poster that
    says what a pink dot is.
    """
    from build_career_grid import ROLE_LABEL, ROLE_ORDER
    import html as _h

    items = [(c, _h.unescape(ROLE_LABEL[c])) for c in ROLE_ORDER]
    widths = [52 + len(lab) * 8.4 for _c, lab in items]
    rows, cur, acc = [], [], 0.0
    limit = 3500.0
    for (cls, lab), wdt in zip(items, widths):
        if acc + wdt > limit and cur:
            rows.append(cur); cur, acc = [], 0.0
        cur.append((cls, lab, wdt)); acc += wdt
    if cur:
        rows.append(cur)

    out = []
    for ri, row in enumerate(rows):
        total = sum(w for _c, _l, w in row)
        x = mid - total / 2
        yy = y + ri * 34
        for cls, lab, wdt in row:
            out.append(f'<rect x="{x:.0f}" y="{yy - 11:.0f}" width="15" '
                       f'height="15" rx="2" fill="{T.ROLE_COLOR[cls]}"/>')
            out.append(f'<text x="{x + 24:.0f}" y="{yy + 2:.0f}" '
                       f'font-size="16" fill="{T.INK_DIM}" '
                       f'font-family="{T.NAMES}">{T.esc(lab)}</text>')
            x += wdt
    return "".join(out)


def masthead_type(a) -> str:
    """Everything in the masthead that is not a logo."""
    W, mid = CANVAS_W, CANVAS_W / 2
    out = []

    out.append(f'<text x="{mid:.0f}" y="{TITLE_Y}" text-anchor="middle" '
               f'font-size="150" font-weight="700" letter-spacing="18" '
               f'fill="{T.INK}" font-family="{T.DISPLAY}">EVERY HALO CREDIT'
               f'</text>')
    out.append(f'<text x="{mid:.0f}" y="{TITLE_Y + 68}" text-anchor="middle" '
               f'font-size="21" letter-spacing="11" fill="#ffffff" '
               f'opacity="0.95" font-family="{T.MONO}">TWENTY-FIVE YEARS '
               f'&#183; TWELVE RELEASES &#183; EVERY NAME</text>')

    n = len(a["people"])
    multi = sum(1 for p in a["people"] if len(p["cols"]) >= 2)
    figures = [(fmt(n), "PEOPLE CREDITED"),
               (fmt(multi), "ON MORE THAN ONE GAME"),
               ("217", "EXTERNAL STUDIOS"),
               (str(len(COLUMNS)), "RELEASES")]
    for frac, (big, lab) in zip([0.185, 0.395, 0.605, 0.815], figures):
        x = W * frac
        out.append(f'<text x="{x:.0f}" y="{TITLE_Y + 224}" text-anchor="middle" '
                   f'font-size="84" font-weight="600" fill="#ffffff" '
                   f'font-family="{T.DISPLAY}">{big}</text>')
        out.append(f'<text x="{x:.0f}" y="{TITLE_Y + 262}" text-anchor="middle" '
                   f'font-size="15" letter-spacing="4" fill="{T.INK}" '
                   f'opacity="0.85" font-family="{T.MONO}">{lab}</text>')

    out.append(_legend(mid, TITLE_Y + 396))
    out.append(_role_key(mid, TITLE_Y + 486))

    # era brackets: each studio's mark spans the games it made
    for era in ERA_ORDER:
        lo, hi = ERA_SPAN[era]
        col = T.ERA_COLOR[era]
        x0, x1 = cx(lo) - PITCH / 2 + 14, cx(hi) + PITCH / 2 - 14
        by = STUDIO_ROW_Y + 54
        out.append(f'<line x1="{x0:.0f}" y1="{by:.0f}" x2="{x1:.0f}" '
                   f'y2="{by:.0f}" stroke="{col}" stroke-width="1.4" '
                   f'opacity="0.5"/>')
        for ex in (x0, x1):
            out.append(f'<line x1="{ex:.0f}" y1="{by:.0f}" x2="{ex:.0f}" '
                       f'y2="{by - 11:.0f}" stroke="{col}" stroke-width="1.4" '
                       f'opacity="0.5"/>')
        out.append(f'<text x="{era_center(era):.0f}" y="{by + 26:.0f}" '
                   f'text-anchor="middle" font-size="19" letter-spacing="6" '
                   f'fill="#ffffff" opacity="0.9" font-family="{T.MONO}">'
                   f'{era_years(era)}</text>')

    for i, (_g, label, year, era) in enumerate(COLUMNS):
        col = T.ERA_COLOR[era]
        base = GAME_ROW_Y + HEAD_LOGO_H
        out.append(f'<text x="{cx(i):.0f}" y="{base + 30:.0f}" '
                   f'text-anchor="middle" font-size="21" font-weight="600" '
                   f'letter-spacing="1.3" fill="#ffffff" '
                   f'font-family="{T.DISPLAY}">{T.esc(label)}</text>')
        out.append(f'<text x="{cx(i):.0f}" y="{base + 56:.0f}" '
                   f'text-anchor="middle" font-size="16" letter-spacing="3" '
                   f'fill="#ffffff" opacity="0.8" font-family="{T.MONO}">'
                   f'{year}</text>')
        out.append(f'<text x="{cx(i):.0f}" y="{base + 90:.0f}" '
                   f'text-anchor="middle" font-size="24" font-weight="600" '
                   f'fill="#ffffff" font-family="{T.MONO}">'
                   f'{fmt(len(a["col_people"][i]))}</text>')
        out.append(f'<text x="{cx(i):.0f}" y="{base + 110:.0f}" '
                   f'text-anchor="middle" font-size="13" letter-spacing="2.6" '
                   f'fill="#ffffff" opacity="0.72" font-family="{T.MONO}">'
                   f'CREDITED</text>')
    out.append(f'<line x1="{MARGIN}" y1="{HEAD_RULE_Y}" '
               f'x2="{CANVAS_W - MARGIN}" y2="{HEAD_RULE_Y}" '
               f'stroke="{T.GOLD}" stroke-width="2.5" opacity="0.65"/>')
    return "".join(out)


def header_logos(studio_big, game_logo) -> str:
    """Drawn last, over everything, so no wash dulls them.

    Game marks are placed on their anchor, not on their bounding box: each is
    already scaled so its "H" is the same width, and each is then dropped so
    the dot in its "O" sits on one line. Centring the boxes instead let a
    badge and a long wordmark drift apart vertically even at matching scale.
    """
    out = []
    for era in ERA_ORDER:
        uri, lw, lh = studio_big[era]
        out.append(f'<image x="{era_center(era) - lw / 2:.0f}" '
                   f'y="{STUDIO_ROW_Y - lh / 2:.0f}" width="{lw}" '
                   f'height="{lh}" href="{uri}"/>')
    anchor = GAME_ROW_Y + LOGO_ANCHOR_DY
    for i in range(len(COLUMNS)):
        uri, lw, lh, ay = game_logo[i]
        out.append(f'<image x="{cx(i) - lw / 2:.1f}" y="{anchor - ay:.1f}" '
                   f'width="{lw}" height="{lh}" href="{uri}"/>')
    return "".join(out)


# ------------------------------------------------------------------- build

def build(a, preview_rows=None):
    from logo_assets import GAME_LOGOS, STUDIO_LOGOS, data_uri

    from logo_assets import load_alignment, prepare_aligned, prepare_infinite
    align = load_alignment()
    game_logo = {}
    for i, (gids, *_r) in enumerate(COLUMNS):
        key = "halo-mcc-post-2018" if len(gids) > 1 else gids[0]
        fn, tr = GAME_LOGOS[key]
        hf, af = align.get(key, (None, None))
        if key == "halo-infinite" and hf:
            # INFINITE runs 38% wider than HALO at native size; scaled
            # together with the rest of the mark that disproportion carried
            # straight through. Split and independently width-matched
            # instead of scaled by one shared factor.
            game_logo[i] = prepare_infinite(fn, LOGO_H_TARGET, hf, af)
        elif hf:
            game_logo[i] = prepare_aligned(fn, tr, LOGO_H_TARGET, hf, af)
        else:
            uri, lw, lh = data_uri(fn, tr, HEAD_LOGO_W, HEAD_LOGO_H)
            game_logo[i] = (uri, lw, lh, lh / 2)
    studio_small = {e: data_uri(fn, tr, 260, 15)
                    for e, (fn, tr) in STUDIO_LOGOS.items()}
    studio_big = {e: data_uri(fn, tr, 420, 88)
                  for e, (fn, tr) in STUDIO_LOGOS.items()}

    rows = a["rows"] if preview_rows is None else a["rows"][:preview_rows]
    overflow = {} if preview_rows is not None else a["overflow"]
    body, grid_end, grid_before_overflow = grid_body(rows, overflow, a["section_at"], studio_small)
    # the array charges mid-grid, and the tower's beam climbs to it
    burst_y = HEAD_RULE_Y + (grid_end - HEAD_RULE_Y) * 0.52

    # the lower half continues the same canvas rather than starting a sheet
    import poster_sheet2
    card_logo = {}
    for i, (gids, *_r) in enumerate(COLUMNS):
        key = "halo-mcc-post-2018" if len(gids) > 1 else gids[0]
        fn, tr = GAME_LOGOS[key]
        card_logo[i] = data_uri(fn, tr, 300, 70)
    sections, sections_end = poster_sheet2.build(
        a, MARGIN, grid_end + 220, CANVAS_W - MARGIN * 2, card_logo)

    # Was sections_end + TOWER_H + 520, which left the tower entirely below
    # the last section. Pulled up further still (to +40) so the tower's own
    # top now rises a few hundred px INTO the notes text above it, rather
    # than just meeting it -- the tower is drawn behind the sections (see
    # `parts` below), so the text already renders on top; notes() adds its
    # own dark backing so that overlap doesn't cost it readability.
    total_h = sections_end + TOWER_H + 40

    # the supplied art, planted so its base sinks under the ring's surface
    art = T.beam_tower_image(TOWER_H)
    ground = total_h - RING_BOTTOM_INSET
    top = ground + 70 - art["h"]
    # The beam is the anchor. It goes on the centre line, where the charging
    # array is, and the artwork is placed so its emitter lands there.
    beam_x = CANVAS_W / 2
    ax = beam_x - art["beam_x"] * art["w"]
    tower_structure = (f'<image x="{ax:.1f}" y="{top:.0f}" width="{art["w"]}" '
                       f'height="{art["h"]}" href="{art["structure"]}"/>')
    tower_lights = (f'<image x="{ax:.1f}" y="{top:.0f}" width="{art["w"]}" '
                    f'height="{art["h"]}" href="{art["lights"]}"/>')
    emitter_y = top + art["h"] * art["emitter"]
    tower_beam = T.tower_beam(
        beam_x,
        glow_from=emitter_y,
        core_from=emitter_y,
        y_to=burst_y,
        core_w=art["beam_w"] * art["w"])


    # One circle, not two arcs: its top meets the sheet at RING_TOP_Y and its
    # bottom at the surface line, so the two curves belong to the same object.
    ring_svg, ring_r = T.ring_pair(CANVAS_W, RING_TOP_Y,
                                   total_h - RING_BOTTOM_INSET,
                                   band_frac=0.012)

    cy = top + art["h"] + 96
    art_credit = (
        f'<line x1="{beam_x - 150:.0f}" y1="{cy - 34:.0f}" '
        f'x2="{beam_x + 150:.0f}" y2="{cy - 34:.0f}" stroke="{T.BEAM}" '
        f'stroke-width="1.2" opacity="0.4"/>'
        f'<text x="{beam_x:.0f}" y="{cy:.0f}" text-anchor="middle" '
        f'font-size="15" letter-spacing="3" fill="#ffffff" opacity="0.62" '
        f'font-family="{T.MONO}">BEAM TOWER CONCEPT ART</text>'
        f'<text x="{beam_x:.0f}" y="{cy + 30:.0f}" text-anchor="middle" '
        f'font-size="21" font-weight="600" letter-spacing="2.4" '
        f'fill="#ffffff" opacity="0.95" font-family="{T.DISPLAY}">'
        f'BEN MAURO</text>'
        f'<text x="{beam_x:.0f}" y="{cy + 54:.0f}" text-anchor="middle" '
        f'font-size="14" letter-spacing="2.4" fill="#ffffff" opacity="0.55" '
        f'font-family="{T.MONO}">HALO INFINITE</text>')

    parts = [
        f'<svg width="{CANVAS_W}" height="{total_h:.0f}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'style="background:{T.VOID};display:block">',
        T.sky_gradient(CANVAS_W, total_h, HEADER_TOP),
        T.nebula(CANVAS_W, total_h, opacity=0.5),
        T.starfield(CANVAS_W, total_h, count=int(3400 + total_h / 12)),
        ring_svg,
        T.atmosphere(CANVAS_W, grid_end + 120, total_h),
        # the near arc and the tower stand in the atmosphere, not behind it
        # sky first, then the surface paints over its lower edge, so the
        # weather sits behind the ring rather than across it
        T.clouds(CANVAS_W, total_h - RING_BOTTOM_INSET - TOWER_H * 0.95,
                 total_h - RING_BOTTOM_INSET + 30),
        T.ring_surface(CANVAS_W, total_h - RING_BOTTOM_INSET, total_h),
        tower_beam, tower_structure, tower_lights, art_credit,
        # the game's own cover, blurred into a ground for its column. Behind
        # the era light so the two tint together rather than fighting.
        cover_art.column_washes(cx, PITCH, HEAD_RULE_Y, grid_before_overflow + 40),
        era_washes(total_h), column_bays(total_h), column_rules(grid_before_overflow + 40),
        # the array charging, mid-sheet, behind the names
        T.charge_burst(CANVAS_W / 2, burst_y, r=CANVAS_W * 0.105,
                       opacity=0.40),
        masthead_type(a),
        body, sections,
        T.vignette(CANVAS_W, total_h, margin=MARGIN),
        header_logos(studio_big, game_logo),
        # A small, personal credit at the foot of the sheet -- deliberately
        # quiet next to the source/tools lines above, which are about the
        # data rather than the person who put it together.
        f'<text x="{MARGIN}" y="{total_h - 40:.0f}" font-size="12" '
        f'fill="{T.INK_DIM}" opacity="0.55" font-family="{T.MONO}">'
        f'X: @HiIAmMoot</text>'
        f'<text x="{MARGIN}" y="{total_h - 22:.0f}" font-size="12" '
        f'fill="{T.INK_DIM}" opacity="0.55" font-family="{T.MONO}">'
        f'GitHub: HiIAmMoot</text>',
        "</svg>"]
    return "".join(parts), total_h

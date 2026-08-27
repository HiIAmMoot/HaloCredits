"""Generate the career-grid SVG/HTML from the credits dataset.

Reverse-engineered from `final-grid-v4.html`, which was authored directly in a
visual-brainstorming session with no generator script. This module reproduces
that layout exactly so the same design can be re-rendered against updated data
instead of being hand-rebuilt (or silently redesigned) every time.

Layout, as decoded from v4
--------------------------
Twelve columns, one per shipped credit roll, with MCC's three post-2018
releases collapsed into a single column (they share one continuity position;
see docs/superpowers/specs/2026-08-22-identity-and-statistics-design.md §5).

    col_x[i]  = 261 + 210*i          column centre
    name_x[i] = col_x[i] - 8         right-aligned name label
    row_y(n)  = 71.5 + 11*n          uniform 11px rows

Every person occupies exactly one row-slot spanning their first credited
column through their last. Within a row:

    circle  r=2.6   a credit that is not their last
    square  5.6sq   their final credit
    line    gold    credited again on the very next column
            violet  returned after a gap (dashed)

Rows are built from the people credited on 2+ columns -- one row each, grouped
into "FIRST CREDITED UNDER <era>" sections and sorted by
(first column, most columns first, name). People credited on a single column
are then packed into whatever column-slots those rows leave free, per column,
alphabetically. Whatever no longer fits lands in an OVERFLOW block at the
bottom, grouped by game, 12 per row -- which is why the overflow names pick up
alphabetically from wherever the grid ran out.
"""
import csv
import html as htmllib
import re
from collections import defaultdict
from pathlib import Path

from halocredits.identity import _slug, normalise_name

# (game_ids, label, year label, era)
COLUMNS = [
    (["halo-ce"], "Halo: Combat Evolved", "2001", "Bungie"),
    (["halo-2"], "Halo 2", "2004", "Bungie"),
    (["halo-3"], "Halo 3", "2007", "Bungie"),
    (["halo-3-odst"], "Halo 3: ODST", "2009", "Bungie"),
    (["halo-reach"], "Halo: Reach", "2010", "Bungie"),
    (["halo-cea"], "Halo: CE Anniversary", "2011", "343 Industries"),
    (["halo-4"], "Halo 4", "2012", "343 Industries"),
    (["halo-mcc"], "Halo: TMCC (2014)", "2014", "343 Industries"),
    (["halo-5"], "Halo 5: Guardians", "2015", "343 Industries"),
    (["halo-mcc-2018", "halo-mcc-2021", "halo-mcc-2025"], "Halo: TMCC (Post-2018)",
     "2018–25", "343 Industries"),
    (["halo-infinite"], "Halo Infinite", "2021", "343 Industries"),
    (["halo-campaign-evolved"], "Halo: Campaign Evolved", "2026", "Halo Studios"),
]
GAME_TO_COL = {g: i for i, (gids, *_r) in enumerate(COLUMNS) for g in gids}

# Releases whose credits roll was reprinted verbatim into a later
# compilation rather than re-rolled for it. Someone credited on the source
# game is understood to be credited on the target too, unless they already
# have a separate, real credit of their own there.
REPRINT_SOURCES = {
    "halo-ce": ["halo-cea", "halo-mcc", "halo-mcc-2018", "halo-campaign-evolved"],
    # MCC's own "Combat Evolved" runs on Anniversary's remade assets, not the
    # 2001 original -- CEA's roll reprints into MCC the same way CE's does,
    # so anyone credited there and nowhere else still needs the dot, even a
    # bare single first-name credit with nothing else to match it against.
    "halo-cea": ["halo-mcc", "halo-mcc-2018"],
    "halo-2": ["halo-mcc", "halo-mcc-2018"],
    "halo-3": ["halo-mcc", "halo-mcc-2018"],
    "halo-3-odst": ["halo-mcc-2018"],
    "halo-reach": ["halo-mcc-2018"],
    "halo-4": ["halo-mcc", "halo-mcc-2018"],
    # TMCC (2018+) is an update to TMCC (2014), not a new compilation --
    # its own roll (credit for the compilation itself, not any one game in
    # it) reprints 2014's the same way 2014 reprinted each individual game.
    "halo-mcc": ["halo-mcc-2018"],
}
REPRINT_MAP = {GAME_TO_COL[src]: sorted({GAME_TO_COL[t] for t in targets})
              for src, targets in REPRINT_SOURCES.items()}


def reprint_cols(p):
    """Columns where this person's credit is a reprint of one of their real
    ones, minus any column they are separately, actually credited on."""
    out = set()
    for c in p["cols"]:
        out.update(REPRINT_MAP.get(c, ()))
    return sorted(out - set(p["cols"]))


ERA_COLOR = {"Bungie": "#00a3e3", "343 Industries": "#d95926", "Halo Studios": "#ffffff"}
ERA_LABEL = {"Bungie": "BUNGIE", "343 Industries": "343 INDUSTRIES",
             "Halo Studios": "HALO STUDIOS"}
COMMUNITY_COLOR = "#4a9d8f"

# One hue per role class, matching the poster. The marker carries what the
# person did; the column already carries which game and the section header
# already carries which studio era, so spending the marker on era too said
# the same thing three times and left the grid blue-on-blue.
ROLE_COLOR = {
    # White read as too close to "special thanks" grey at a glance, and
    # plain gold (#ffd166) is already the connector that joins consecutive
    # games and the reprint-dot colour, so reusing it made a management
    # marker indistinguishable from either. Darkgoldenrod still reads as
    # gold for leadership without colliding with either one -- measured
    # further from both #ffd166 and #78859b than white was.
    "management": "#b8860b", "production": "#ff9f45",
    "engineering": "#4d9de0", "art": "#e072b5", "design": "#5fd08a",
    "audio": "#a983f0", "writing": "#ff6b6b", "qa": "#4fd8ff",
    "live": "#c3e33a", "publishing": "#30e8b1", "community": "#4a9d8f",
    "thanks": "#78859b", "unspecified": "#454e5e",
}
ROLE_LABEL = {
    "management": "management", "production": "production",
    "engineering": "engineering", "art": "art", "design": "design",
    "audio": "audio", "writing": "writing &amp; performance", "qa": "test",
    "live": "live &amp; support", "publishing": "publisher staff",
    "community": "community volunteers", "thanks": "special thanks",
    "unspecified": "unknown",
}
ROLE_ORDER = [
    # the order a game is actually made in, so the legend reads as a pipeline
    # rather than as a ranking by headcount. It drives the grid's banding too,
    # so the colours down a column follow the same sequence as the key.
    "management", "production", "design", "engineering", "art", "audio",
    "writing", "qa", "live",
    # then the three classes that were not on the development team, and last
    # the credits that named no work at all
    "publishing", "community", "thanks", "unspecified",
]
# The publisher's own staff. Credited on the game, so they are counted and
# drawn -- but marked, because they were not on the team that built it.
PUBLISHER_COLOR = "#30e8b1"

COL_X = [261 + 210 * i for i in range(len(COLUMNS))]
NAME_X = [x - 8 for x in COL_X]
ROW_Y0 = 71.5
ROW_H = 11.0
CANVAS_W = 2700
RULE_X2 = 2686
OVERFLOW_GAP = 48.0          # last grid row -> first overflow row
OVERFLOW_RULE_DY = 16.5      # last grid row -> overflow rule
OVERFLOW_LABEL_DY = 26.5     # last grid row -> overflow label
SUB_LABEL_DY = -8.4          # group's first row -> its sub-label baseline
SUB_GAP = 33.0               # group's last row -> next group's first row
OVERFLOW_PER_ROW = 12

# Logo headers are opt-in. The page build leaves them off, so its SVG stays
# the lean one the browser has to scroll through; the poster export turns
# them on and pays the ~1MB of embedded PNG for them.
LOGO_BOX_W, LOGO_BOX_H = 190, 54     # a column is 210 wide; this leaves margin
LOGO_TOP = 9
LOGO_HEAD_DY = LOGO_TOP + LOGO_BOX_H + 9    # everything below shifts by this
ERA_LOGO_H = 11                      # inline mark in a section header's row
ERA_LOGO_X = 102                     # clears "FIRST CREDITED UNDER " at 7.5px mono

INK = "#c8d4e0"
BAND = "#0d121a"
BG = "#0a0e14"
GOLD = "#ffd166"
# the gap connector. Silver rather than a hue, so it reads as an absence
# next to the solid line that marks a run of consecutive games.
GAP_LINE = "#b9c6d3"

# Non-person rows that were still in data/people.csv when v4 was rendered. They
# are company names the extraction fabricated as people and have since been
# fixed at the source; kept here so the v4 reproduction is exact.
LEGACY_NON_PEOPLE = {
    "Axis Animation", "Digic Pictures", "Hollywood Studio Symphony",
    "House of Moves", "Image Metrics", "Miles Sound System",
    "NewBreed Visual FX", "Northwest Sinfornia", "Omni Interactive Audio",
    "Polygon", "Schematic", "Studio X", "Technicolor Game-Sound Services",
    "Vicon",
}


def esc(s):
    """html.escape, quotes included -- non-ASCII is left as literal UTF-8."""
    return htmllib.escape(s)


def fmt(n):
    return f"{n:,}"


def load_people(people_csv, exclude=frozenset()):
    """-> [{name, cols, community}] for everyone with at least one column."""
    out = []
    with open(people_csv, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            name = r["display_name"]
            if name in exclude:
                continue
            cols = sorted({GAME_TO_COL[g] for g in r["games"].split("|")
                           if g in GAME_TO_COL})
            if not cols:
                continue
            out.append({"name": name, "cols": cols, "community": False,
                        "publisher": False, "pid": r["person_id"]})
    return out


def load_marked(credits_dir, inclusion, key, aliases=None):
    """People the credits list who are not development staff.

    They are excluded from data/people.csv, which is built core-only, so they
    are read straight from the credit rows -- which means identity resolution
    has to be redone here. Without it the same person arrives twice under two
    spellings: Halo 3: ODST credits "Aaron Elliot" on its wiki roll and
    "Aaron Elliott" on its MobyGames page, and both would be drawn.
    config/aliases.csv already rules on those; normalise_name catches the
    case and punctuation differences it does not list.
    """
    aliases = aliases or {}
    seen, display = {}, {}
    for path in sorted(Path(credits_dir).glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["inclusion_class"] != inclusion:
                    continue
                col = GAME_TO_COL.get(row["game_id"])
                if col is None:
                    continue
                name = row["name_raw"]
                ident = aliases.get(name) or _slug(normalise_name(name))
                seen.setdefault(ident, set()).add(col)
                # keep the longest spelling seen, the way display_name does
                if len(name) > len(display.get(ident, "")):
                    display[ident] = name
    out = []
    for ident, cols in seen.items():
        rec = {"name": display[ident], "cols": sorted(cols), "community": False,
               "publisher": False, "pid": ident}
        rec[key] = True
        out.append(rec)
    return out


def load_community(credits_dir):
    """MCC's Feb-2025 Reclaimer volunteers: credited alongside staff but never
    employed, so they are excluded from data/people.csv's core registry and
    drawn separately, in teal, in the column their release belongs to."""
    path = Path(credits_dir) / "halo-mcc-2025.csv"
    if not path.exists():
        return []
    seen, out = set(), []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["inclusion_class"] != "community":
                continue
            name = row["name_raw"]
            if name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "cols": [GAME_TO_COL["halo-mcc-2025"]],
                        "community": True, "publisher": False,
                        "pid": _slug(normalise_name(name))})
    return out


def era_of_col(c):
    return COLUMNS[c][3]


def _class_rank(p):
    """Development staff, then publisher staff, then community volunteers.

    Applied within a group rather than across the whole grid: everyone who
    shares a first and last game stays together, with the marked classes at
    the foot of that run instead of interleaved through it.
    """
    if p.get("publisher"):
        return 1
    if p["community"]:
        return 2
    return 0


_ROLE_RANK = {c: i for i, c in enumerate(ROLE_ORDER)}


def _role_rank(p, col):
    """Where this person's role on this game sits in the legend's order.

    Missing roles all rank equal, so a grid built without a role lookup sorts
    exactly as it did before -- which is what keeps the v4 reproduction
    byte-identical.
    """
    roles = p.get("roles")
    cls = roles.get(col) if roles else None
    return _ROLE_RANK.get(cls, len(ROLE_ORDER))


def _role_sig(p):
    """The person's roles across their whole career, in column order.

    Used as a tiebreak AFTER career shape, so it only ever reorders people
    who occupy exactly the same columns. Two people with the same career and
    the same craft become adjacent, which turns a column of scattered hues
    into bands -- most visibly among the single-game people, who are the bulk
    of the grid and were previously ordered by name alone.
    """
    return tuple(_role_rank(p, c) for c in p["cols"])


def _sort_key(p, group_by_shape=True, sink_marked=True):
    """Longest-surviving careers first: people whose final credit is the most
    recent game head the section, so the top of the grid reads as "still here".
    Then earliest start.

    Within one (first game, last game) section, `group_by_shape` keeps people
    with the same career in one block by continuing the same "latest game
    first" rule inwards -- compare the second-to-last game, then the third,
    and so on. Everyone who was there for the whole stretch rises to the top
    of the section, and identical careers end up adjacent instead of being
    interleaved alphabetically, so the connecting lines stack into solid
    bands rather than a comb.

    v4 ordered these by game count then name, which scattered a handful of
    odd shapes through the 68 people who all went Halo 4 -> Halo 5 ->
    Infinite. Pass False to reproduce that.
    """
    if group_by_shape:
        # Shape match outranks class rank: two people who share the exact
        # same run of games belong together at the top of their (last,
        # first) section regardless of which of them is publisher-marked --
        # class rank only breaks the tie WITHIN one exact shape, sinking a
        # marked person below their non-marked shape-mates rather than
        # pulling them out to the foot of the whole broader section the way
        # ranking by class first did. A publisher-staff credit shouldn't
        # cost someone their place next to everyone who shares their career.
        return (-p["cols"][-1], p["cols"][0],
                tuple(-c for c in reversed(p["cols"])),
                _class_rank(p) if sink_marked else 0,
                _role_sig(p), p["name"])
    return (-p["cols"][-1], p["cols"][0], -len(p["cols"]), p["name"])


def layout(people, group_by_shape=True, sink_marked=True):
    """Assign every person a row. Returns (rows, overflow_groups, section_at).

    rows          list of lists of person-records, index == row number
    overflow      {col: [person, ...]} in alphabetical order
    section_at    {row_index: era} where a section header is drawn
    """
    for p in people:
        p["reprint_cols"] = reprint_cols(p)

    multi = [p for p in people if len(p["cols"]) >= 2]
    single = [p for p in people if len(p["cols"]) == 1]

    key = lambda p: _sort_key(p, group_by_shape, sink_marked)
    bungie = sorted([p for p in multi if era_of_col(p["cols"][0]) == "Bungie"], key=key)
    later = sorted([p for p in multi if era_of_col(p["cols"][0]) != "Bungie"], key=key)

    ordered = bungie + later
    section_at = {}
    if bungie:
        section_at[0] = "Bungie"
    if later:
        section_at[len(bungie)] = era_of_col(later[0]["cols"][0])

    rows = [[p] for p in ordered]
    # a multi-column person blocks every column they span, not just the ones
    # they are credited on -- their connecting line crosses the gaps. A
    # reprint dot draws no line, but still has to sit somewhere real, so any
    # reprint column outside [first, last] extends the reservation too --
    # otherwise it could land in a cell another person was already packed
    # into. Single-column people don't get individual reprint dots (see
    # poster_sheet1's chip badge instead), so their reprint_cols never
    # reaches this reservation at all.
    occupied = []
    for p in ordered:
        pts = p["cols"] + p["reprint_cols"]
        occupied.append(set(range(min(pts), max(pts) + 1)))

    by_col = defaultdict(list)
    for p in single:
        by_col[p["cols"][0]].append(p)

    overflow = {}
    for c in range(len(COLUMNS)):
        col_people = by_col.get(c, [])
        if sink_marked:
            # Single-game people are the bulk of every column and had no
            # ordering beyond the alphabet, so their colours arrived shuffled.
            # Grouping by role first turns each column into bands of craft.
            dev = sorted((p for p in col_people if _class_rank(p) == 0),
                         key=lambda p: (_role_rank(p, c), p["name"]))
            marked = sorted((p for p in col_people if _class_rank(p) != 0),
                            key=lambda p: (_class_rank(p), _role_rank(p, c),
                                           p["name"]))
        else:
            # v4 interleaved everyone alphabetically in one queue
            dev = sorted(col_people, key=lambda p: p["name"])
            marked = []

        free = [ri for ri in range(len(rows)) if c not in occupied[ri]]
        # Development staff take the earliest free slots, so the top of the
        # column reads as the team that built the game; the marked classes
        # continue straight on from there. Filling the LAST free slots
        # instead would push them lower still, but it strands a run of empty
        # slots between the final developer and the first volunteer, and a
        # column that just stops and restarts reads as missing data.
        take_dev = free[:len(dev)]
        take_marked = free[len(dev):len(dev) + len(marked)]

        for ri, person in zip(take_dev, dev):
            occupied[ri].add(c)
            rows[ri].append(person)
        for ri, person in zip(take_marked, marked):
            occupied[ri].add(c)
            rows[ri].append(person)

        left = dev[len(take_dev):] + marked[len(take_marked):]
        if left:
            overflow[c] = left
    return rows, overflow, section_at


def _logo_images(logos):
    """Fitted logo images for the headers, or empty dicts when logos are off.

    Imported lazily: the page build never asks for logos, and pulling in
    numpy/Pillow/playwright for it would make the common path pay for the
    rare one.
    """
    if not logos:
        return {}, {}
    from logo_assets import GAME_LOGOS, STUDIO_LOGOS, data_uri

    games = {}
    for i, (gids, *_r) in enumerate(COLUMNS):
        key = "halo-mcc-post-2018" if len(gids) > 1 else gids[0]
        fn, treatment = GAME_LOGOS[key]
        games[i] = data_uri(fn, treatment, LOGO_BOX_W, LOGO_BOX_H)
    studios = {era: data_uri(fn, tr, 240, ERA_LOGO_H)
               for era, (fn, tr) in STUDIO_LOGOS.items()}
    return games, studios


def render_svg(rows, overflow, section_at, col_headcount, logos=False):
    game_logo, studio_logo = _logo_images(logos)
    head_dy = LOGO_HEAD_DY if logos else 0
    row_y0 = ROW_Y0 + head_dy
    n_grid = len(rows)
    last_grid_y = row_y0 + ROW_H * (n_grid - 1)

    # ---- overflow block geometry ----
    ov_parts, ov_rows_total = [], 0
    cursor = last_grid_y + OVERFLOW_GAP
    ov_plan = []
    for c in sorted(overflow):
        people = overflow[c]
        n_rows = (len(people) + OVERFLOW_PER_ROW - 1) // OVERFLOW_PER_ROW
        ov_plan.append((c, people, cursor, n_rows))
        cursor += ROW_H * (n_rows - 1) + SUB_GAP
        ov_rows_total += n_rows
    total_h = (ov_plan[-1][2] + ROW_H * (ov_plan[-1][3] - 1) + 38.5
               if ov_plan else last_grid_y + 38.5)

    out = [f'<svg width="{CANVAS_W}" height="{total_h:.0f}" '
           f'style="background:{BG};display:block;">']

    # column headers, with an alternating band drawn behind every other column
    band_h = total_h - 70 - head_dy
    for i, (gids, label, year, era) in enumerate(COLUMNS):
        x = COL_X[i]
        if i % 2 == 0:
            out.append(f'<rect x="{COL_X[i] - 105}" y="{48 + head_dy}" width="210" '
                       f'height="{band_h:.0f}" fill="{BAND}"/>')
        if logos:
            uri, lw, lh = game_logo[i]
            out.append(f'<image x="{x - lw / 2:.1f}" '
                       f'y="{LOGO_TOP + (LOGO_BOX_H - lh) / 2:.1f}" '
                       f'width="{lw}" height="{lh}" href="{uri}"/>')
        out.append(
            f'<text x="{x}" y="{24 + head_dy}" text-anchor="middle" font-size="9" '
            f'font-weight="700" fill="{ERA_COLOR[era]}" '
            f'font-family="Segoe UI,sans-serif">{esc(label)}</text>'
            f'<text x="{x}" y="{38 + head_dy}" text-anchor="middle" font-size="8" '
            f'fill="#5c6b7f" font-family="monospace">{year}</text>'
            f'<text x="{x}" y="{52 + head_dy}" text-anchor="middle" font-size="8" '
            f'fill="#8b93a3" font-family="monospace">'
            f'{fmt(col_headcount[i])} credited</text>')
    out.append(f'<line x1="6" y1="{54 + head_dy}" x2="{RULE_X2}" '
               f'y2="{54 + head_dy}" stroke="#232a35"/>')

    # ---- grid rows ----
    for ri, people in enumerate(rows):
        y = row_y0 + ROW_H * ri
        if ri in section_at:
            era = section_at[ri]
            out.append(f'<line x1="6" y1="{y - 6.5:.0f}" x2="{RULE_X2}" '
                       f'y2="{y - 6.5:.0f}" stroke="#3a4656" stroke-width="1.4"/>')
            if logos:
                # the studio's own mark stands in for its name
                uri, lw, lh = studio_logo[era]
                out.append(f'<text x="6" y="{y + 2.5:.0f}" font-size="7.5" '
                           f'font-weight="700" fill="{GOLD}" opacity="0.9" '
                           f'font-family="monospace">FIRST CREDITED UNDER</text>')
                out.append(f'<image x="{ERA_LOGO_X}" y="{y - 5.5:.1f}" '
                           f'width="{lw}" height="{lh}" href="{uri}"/>')
            else:
                out.append(f'<text x="6" y="{y + 2.5:.0f}" font-size="7.5" '
                           f'font-weight="700" fill="{GOLD}" opacity="0.9" '
                           f'font-family="monospace">FIRST CREDITED UNDER '
                           f'{ERA_LABEL[era]}</text>')
        # the row's multi-column owner is drawn first, then whichever
        # single-column people were packed into its free slots, left to right
        for p in people:
            out.extend(_render_person(p, y))

    # ---- overflow ----
    if ov_plan:
        ry = last_grid_y
        out.append(f'<line x1="6" y1="{ry + OVERFLOW_RULE_DY:.0f}" x2="{RULE_X2}" '
                   f'y2="{ry + OVERFLOW_RULE_DY:.0f}" stroke="#4a5566" stroke-width="2"/>')
        total_ov = sum(len(p) for p in overflow.values())
        out.append(f'<text x="6" y="{ry + OVERFLOW_LABEL_DY:.0f}" font-size="8" '
                   f'font-weight="700" fill="{GOLD}" font-family="monospace">'
                   f'OVERFLOW &#183; {fmt(total_ov)} MORE PEOPLE CREDITED ON ONE '
                   f'GAME ONLY, NO ROOM LEFT ABOVE</text>')
        for c, people, first_y, n_rows in ov_plan:
            era = era_of_col(c)
            out.append(f'<text x="6" y="{first_y + SUB_LABEL_DY:.1f}" font-size="7.5" '
                       f'font-weight="700" fill="{ERA_COLOR[era]}" opacity="0.9" '
                       f'font-family="monospace">{esc(COLUMNS[c][1])} &#183; '
                       f'{fmt(len(people))} people</text>')
            for idx, p in enumerate(people):
                r, k = divmod(idx, OVERFLOW_PER_ROW)
                y = first_y + ROW_H * r
                out.extend(_marker(p, k, y))
    out.append("</svg>")
    return "".join(out)


def _color(p, col):
    """The marker's colour: what this person did on this game.

    Falls back to the era only when no role could be determined at all, and
    to the old publisher/community colours when the grid is built without a
    role lookup -- which is what keeps the v4 reproduction working.
    """
    roles = p.get("roles")
    if roles:
        cls = roles.get(col)
        if cls:
            return ROLE_COLOR.get(cls, ROLE_COLOR["unspecified"])
    if p["community"]:
        return COMMUNITY_COLOR
    if p.get("publisher"):
        return PUBLISHER_COLOR
    return ERA_COLOR[era_of_col(col)]


def _reprint_triangle(x: float, y: float, r: float = 3.2) -> str:
    """A reprint marker: gold, like the connector lines, and a different
    SHAPE from the circle (a real mid-career credit) and the square (a real
    final credit) rather than a third colour, since this grid already draws
    both of those in gold-adjacent tones elsewhere and a dot-vs-dot
    distinction would be easy to miss at this scale."""
    return (f'<polygon points="{x:.1f},{y - r:.1f} {x - r * 0.87:.1f},'
           f'{y + r * 0.6:.1f} {x + r * 0.87:.1f},{y + r * 0.6:.1f}" '
           f'fill="{GOLD}"/>')


def _render_person(p, y):
    """One person on one grid row: name, connectors, credits, final marker."""
    cols, out = p["cols"], []
    for c in (p.get("reprint_cols") or ()) if len(cols) >= 2 else ():
        out.append(_reprint_triangle(COL_X[c], y))
    # Once the marker carries the role -- and community and publisher staff
    # are two of the role classes -- colouring the NAME as well says the same
    # thing twice and makes two rows of one grid look like two kinds of type.
    # Without a role lookup the old ink is kept, so v6 is unchanged.
    ink = INK if p.get("roles") else (
        COMMUNITY_COLOR if p["community"]
        else PUBLISHER_COLOR if p.get("publisher") else INK)
    if len(cols) >= 2:
        out.append(f'<text x="{NAME_X[cols[0]]}" y="{y + 2.7:.1f}" '
                   f'text-anchor="end" font-size="8" fill="{ink}" '
                   f'font-family="Segoe UI,sans-serif">{esc(p["name"])}</text>')
        for a, b in zip(cols, cols[1:]):
            x1, x2 = COL_X[a], COL_X[b]
            if b - a == 1:
                out.append(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" '
                           f'stroke="{GOLD}" stroke-width="1.8" opacity="0.95"/>')
            else:
                out.append(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" '
                           f'stroke="{GAP_LINE}" stroke-width="1" opacity="0.5" '
                           f'stroke-dasharray="2,2"/>')
        for c in cols[:-1]:
            out.append(f'<circle cx="{COL_X[c]}" cy="{y}" r="2.6" '
                       f'fill="{_color(p, c)}"/>')
        last = cols[-1]
        out.append(f'<rect x="{COL_X[last] - 3}" y="{y - 2.8:.1f}" width="5.6" '
                   f'height="5.6" fill="{_color(p, last)}"/>')
    else:
        c = cols[0]
        out.append(f'<rect x="{COL_X[c] - 3}" y="{y - 2.8:.1f}" width="5.6" '
                   f'height="5.6" fill="{_color(p, c)}"/>')
        if p.get("reprint_cols"):
            # No reserved row-space to put a real triangle on the reprint's
            # own column (see build()), so a single-column person gets a
            # small badge on their one marker instead -- reprinted
            # somewhere, unspecified where.
            out.append(_reprint_triangle(COL_X[c] + 5, y - 4, r=2.4))
        out.append(f'<text x="{NAME_X[c]}" y="{y + 2.7:.1f}" text-anchor="end" '
                   f'font-size="8" fill="{ink}" '
                   f'font-family="Segoe UI,sans-serif">{esc(p["name"])}</text>')
    return out


def _marker(p, slot, y):
    c = p["cols"][0]
    out = [
        f'<rect x="{COL_X[slot] - 3}" y="{y - 2.8:.1f}" width="5.6" height="5.6" '
        f'fill="{_color(p, c)}"/>',
    ]
    if p.get("reprint_cols"):
        out.append(_reprint_triangle(COL_X[slot] + 5, y - 4, r=2.4))
    out.append(
        f'<text x="{NAME_X[slot]}" y="{y + 2.7:.1f}" text-anchor="end" '
        f'font-size="8" fill="{COMMUNITY_COLOR if p["community"] else INK}" '
        f'font-family="Segoe UI,sans-serif">{esc(p["name"])}</text>')
    return out


def build(people_csv, credits_dir, exclude=frozenset(), group_by_shape=True,
          include_publishers=True, aliases=None, sink_marked=True, logos=False,
          roles=None, include_thanks=True):
    people = load_people(people_csv, exclude) + load_community(credits_dir)
    if include_publishers:
        # v4 predates this and left the publisher's own staff out of the grid
        # entirely; pass False to reproduce it.
        people += load_marked(credits_dir, "publishing", "publisher", aliases)
    if include_thanks:
        # Special-thanks credits were excluded from every stage before this
        # -- not just missing a marker, missing from the roster entirely,
        # for anyone whose only credit on a game was a special-thanks line
        # (1,642 distinct raw names across the corpus). "thanks" is already
        # a role class with its own colour, so no bespoke marker is needed
        # the way publisher/community once required -- being IN people at
        # all is what was missing.
        people += load_marked(credits_dir, "special-thanks", "special_thanks",
                              aliases)
    # Someone credited both as staff and on the publisher's (or special-
    # thanks) side is one person, and the two rolls rarely spell them the
    # same way -- Halo 3: ODST's marketing credits "Christopher Lee" for the
    # man its development credits call "Chris Lee". Matching on the resolved
    # identity rather than the spelling is what stops him being drawn twice.
    #
    # The development record wins the display name, but its OWN games are
    # not the whole story: Michael Salvatori is core dev staff on seven
    # games and special-thanks-only on Halo 5, a credit that used to vanish
    # here because only the first record survived. cols (and the marked
    # flags) are unioned instead, so a game where someone is ONLY
    # special-thanks or ONLY publisher staff still counts as a real credit
    # on that column, on top of whatever their core record already has.
    seen: dict = {}
    deduped = []
    for rec in people:
        ident = rec.get("pid") or _slug(normalise_name(rec["name"]))
        existing = seen.get(ident)
        if existing is not None:
            existing["cols"] = sorted(set(existing["cols"]) | set(rec["cols"]))
            for flag in ("community", "publisher", "special_thanks"):
                if rec.get(flag):
                    existing[flag] = True
            continue
        seen[ident] = rec
        deduped.append(rec)
    people = deduped
    if roles:
        for rec in people:
            found = roles.get(rec["name"])
            if found:
                rec["roles"] = found
    rows, overflow, section_at = layout(people, group_by_shape, sink_marked)
    headcount = [0] * len(COLUMNS)
    for p in people:
        for c in p["cols"]:
            headcount[c] += 1
    svg = render_svg(rows, overflow, section_at, headcount, logos=logos)
    return svg, people, rows, overflow


if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    svg, people, rows, overflow = build(
        root / "data" / "people.csv", root / "data" / "credits")
    multi = sum(1 for p in people if len(p["cols"]) >= 2)
    print(f"people={len(people)} multi={multi} rows={len(rows)} "
          f"overflow={sum(len(v) for v in overflow.values())}")
    print(f"svg bytes={len(svg)}")

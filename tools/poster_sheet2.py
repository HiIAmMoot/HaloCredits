"""The lower half of the poster: the numbers, the studios, the highlights,
the method.

Everything the web page carries below the grid, rebuilt for print. It is not
a second sheet -- it continues the same canvas, and the sky descends into
atmosphere as it goes, so the poster reads as a fall from orbit toward the
ring's surface where the beam tower stands.

Text is wrapped here rather than by the renderer. SVG has no flow layout: a
<text> element is one line and will happily run off the sheet, so every
paragraph is measured and broken before it is emitted. The measure is an
approximation from the type's average advance width, checked against the
longest strings in the corpus rather than assumed.
"""
from __future__ import annotations

import json
import sys
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import poster_theme as T
from build_career_grid import COLUMNS, fmt

MARGIN = 150
GAP = 40


def role_index(root: Path = ROOT):
    """Everything halocredits.roles needs, loaded once."""
    from halocredits.roles import (load_category_patterns, load_heading_index,
                                   load_heading_patterns, load_mobygames_roles,
                                   load_name_tags, load_vendor_types)
    return dict(
        vendor_types=load_vendor_types(root / "config" / "vendor-types.csv"),
        heading_patterns=load_heading_patterns(root / "config" / "role-headings.csv"),
        heading_index=load_heading_index(root / "data" / "source-headings.csv"),
        name_tags=load_name_tags(root / "data" / "name-role-tags.csv"),
        mobygames_roles=load_mobygames_roles(root / "data" / "mobygames-roles.csv"),
        category_patterns=load_category_patterns(root / "config" / "category-map.csv"),
    )


def role_counts(root: Path = ROOT):
    """(per game_id Counter, whole-corpus Counter) of role class."""
    import csv as _csv
    import glob
    from collections import defaultdict
    from halocredits.roles import resolve

    ix = role_index(root)
    pairs = defaultdict(list)
    for path in glob.glob(str(root / "data" / "credits" / "*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in _csv.DictReader(fh):
                pairs[(r["name_raw"], r["game_id"])].append(
                    (r["category"], r["studio"], r["source_ref"],
                     r["role_raw"], r["inclusion_class"]))
    per, total = defaultdict(Counter), Counter()
    for (name, game), rows in pairs.items():
        cls, _prov = resolve(rows, ix["vendor_types"], ix["heading_patterns"],
                             game, ix["heading_index"], name, ix["name_tags"],
                             ix["mobygames_roles"], ix["category_patterns"])
        per[game][cls] += 1
        total[cls] += 1
    return per, total

# Average advance as a fraction of font-size, measured off the rendered faces.
ADV_NAMES = 0.436

# A second, more precisely measured advance ratio for the studio chips only.
# ADV_NAMES above is deliberately generous, because wrap() uses it to decide
# where a PARAGRAPH breaks and overestimating there only wraps a line a
# little early -- safe. Using that same generous number to size a chip's own
# background box left visible empty space on the right of every one of them,
# since a chip has to fit its text, not merely avoid overflowing it. Measured
# directly against rendered Barlow Semi Condensed at 12px across six sample
# strings ("Volt  75" through "The Skywalker Symphony Orchestra  41"): actual
# advance is 0.372, not 0.436.
ADV_NAMES_CHIP = 0.372
ADV_MONO = 0.600


def measure_widths(texts, size: float, family: str = None,
                   cache_path: Path | None = None) -> dict:
    """Real rendered widths for a batch of strings, via getComputedTextLength.

    ADV_NAMES_CHIP above is an AVERAGE advance measured across six sample
    strings. A studio chip sized off that average comes out too narrow for
    any string that skews wider than the sample -- all-caps company names
    ("YOH SERVICES LLC") are exactly that, being all wide capitals with no
    narrow lowercase letters to bring the average down, and overflowed their
    own box. This measures the ACTUAL string instead of estimating it, using
    the same SVG text engine the chip itself renders with.

    Cached to disk (keyed on family/size/text) since the corpus repeats the
    same vendor name across many games, and a full pass is one headless
    launch regardless of how many distinct strings it covers.
    """
    family = family or T.NAMES
    cache_path = cache_path or (ROOT / "render" / ".textcache.json")
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    key_of = lambda t: f"{family}|{size}|{t}"
    todo = [t for t in set(texts) if key_of(t) not in cache]
    if todo:
        from playwright.sync_api import sync_playwright
        spans = "".join(
            f'<text id="t{i}" x="0" y="20" font-size="{size}" '
            f'font-family="{family}">{T.esc(t)}</text>'
            for i, t in enumerate(todo))
        html = (f'<!doctype html><meta charset="utf-8">'
               f'<link rel="stylesheet" href="{T.FONT_LINK}">'
               f'<svg xmlns="http://www.w3.org/2000/svg">{spans}</svg>')
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(600)  # webfont load
            widths = page.eval_on_selector_all(
                "text", "els => els.map(e => e.getComputedTextLength())")
            browser.close()
        for t, w in zip(todo, widths):
            cache[key_of(t)] = w
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return {t: cache[key_of(t)] for t in set(texts)}


def wrap(text: str, max_px: float, size: float, adv: float = ADV_NAMES) -> list:
    """Greedy wrap. SVG will not do it for us."""
    per = max(1, int(max_px / (size * adv)))
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if len(trial) <= per:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def para(x: float, y: float, text: str, max_px: float, size: float,
         fill: str, lh: float = 1.45, family: str = None,
         anchor: str = "start", weight: str = "400") -> tuple:
    family = family or T.NAMES
    out = []
    for i, line in enumerate(wrap(text, max_px, size)):
        out.append(f'<text x="{x:.0f}" y="{y + i * size * lh:.1f}" '
                   f'font-size="{size}" fill="{fill}" font-weight="{weight}" '
                   f'text-anchor="{anchor}" font-family="{family}">'
                   f'{T.esc(line)}</text>')
    n = len(wrap(text, max_px, size))
    return "".join(out), y + n * size * lh


def section_head(x: float, y: float, title: str, subtitle: str,
                 width: float) -> tuple:
    """A section's big title, with a small descriptive line underneath it."""
    out = [f'<line x1="{x:.0f}" y1="{y - 40:.0f}" x2="{x + width:.0f}" '
           f'y2="{y - 40:.0f}" stroke="{T.GOLD}" stroke-width="2.5" '
           f'opacity="0.65"/>',
           f'<text x="{x:.0f}" y="{y + 20:.0f}" font-size="58" '
           f'font-weight="700" letter-spacing="4" fill="{T.INK}" '
           f'font-family="{T.DISPLAY}">{T.esc(title)}</text>',
           f'<text x="{x:.0f}" y="{y + 46:.0f}" font-size="13" '
           f'letter-spacing="5" fill="{T.BUNGIE}" opacity="0.8" '
           f'font-family="{T.MONO}">{T.esc(subtitle)}</text>']
    return "".join(out), y + 96


def dataset_numbers(x0: float, y0: float, width: float, a) -> tuple:
    """The same eleven headline facts the web page leads with, in a four
    column grid. Pulled from hero_stats_data(a) rather than recomputed, so
    the two pages can never quietly disagree with each other.
    """
    import re
    import html as _html
    from build_grid_page import hero_stats_data

    cols_n = 4
    col_w = (width - GAP * (cols_n - 1)) / cols_n
    facts = hero_stats_data(a)
    out = []
    y = y0
    for start in range(0, len(facts), cols_n):
        row = facts[start:start + cols_n]
        bottoms = []
        for j, (num, label) in enumerate(row):
            x = x0 + j * (col_w + GAP)
            out.append(f'<text x="{x:.0f}" y="{y + 34:.0f}" font-size="36" '
                       f'font-weight="700" fill="{T.INK}" '
                       f'font-family="{T.DISPLAY}">{T.esc(num)}</text>')
            plain = _html.unescape(re.sub(r"</?i>", "", label))
            blk, bottom = para(x, y + 62, plain, col_w, 14, T.INK_DIM, lh=1.4)
            out.append(blk)
            bottoms.append(bottom)
        y = max(bottoms) + 34
    return "".join(out), y - 10


def card_behind(blk: str, x0: float, top: float, bottom: float,
                width: float) -> str:
    """Wrap already-built section content in the same dark card every other
    section uses (the highlight cards, and the method/notes card): fill,
    opacity and border all match, so a section either gets its own small
    card per item (the numbers cards) or this one shared field -- never bare
    sky, which was the odd one out next to sections that do have a ground.
    """
    rect = (f'<rect x="{x0 - 24:.0f}" y="{top:.0f}" width="{width + 48:.0f}" '
           f'height="{bottom - top:.0f}" rx="4" fill="#0a1019" '
           f'fill-opacity="0.55" stroke="{T.RULE}" stroke-width="1"/>')
    return rect + blk


# ------------------------------------------------------------- game cards

def _composition(a, i: int, named_vendors, named_order, type_color, type_order):
    """The stacked bar for one game, as (colour, count, label) segments."""
    names = a["col_people"][i]
    total = len(names)
    if not total:
        return [], {}
    era = COLUMNS[i][3]
    vend = sum(1 for n in names if i in a["person_vendor"].get(n, ()))
    npub = sum(1 for n in names if a["by_name"][n].get("publisher"))
    ncom = sum(1 for n in names if a["by_name"][n]["community"])
    nthanks = sum(1 for n in names if a["by_name"][n].get("special_thanks"))
    first_party = total - vend - npub - ncom - nthanks

    seg = []
    if first_party:
        seg.append((T.ERA_COLOR[era], first_party, "core team"))
    named_here, typed = {}, Counter()
    for n in names:
        if i not in a["person_vendor"].get(n, ()):
            continue
        key = a["person_named_vendor"].get((n, i))
        if key:
            named_here.setdefault(key, set()).add(n)
        else:
            for ty in sorted(a["person_vendor_type"].get((n, i),
                                                         {"development"}))[:1]:
                typed[ty] += 1
    for key in named_order:
        if key in named_here:
            label_, color = named_vendors[key]
            seg.append((color, len(named_here[key]), label_))
    for ty in type_order:
        if typed.get(ty):
            seg.append((type_color[ty], typed[ty], ty))
    if npub:
        seg.append((T.PUBLISHER, npub, "publisher staff"))
    if ncom:
        seg.append((T.COMMUNITY, ncom, "community"))
    if nthanks:
        seg.append((T.ROLE_COLOR["thanks"], nthanks, "special thanks"))

    newcomers = sum(1 for n in names if a["by_name"][n]["cols"][0] == i)
    facts = {"total": total, "new": newcomers, "returning": total - newcomers,
             "core": first_party, "vendor": vend, "publisher": npub,
             "community": ncom, "thanks": nthanks,
             "studios": len({a["person_named_vendor"].get((n, i))
                             for n in names
                             if a["person_named_vendor"].get((n, i))})}
    return seg, facts


def studio_legend(x0: float, y0: float, width: float) -> tuple:
    """The colour key for every card's 'by employer' bar, generated from the
    same NAMED_VENDORS / TYPE_COLOR / ERA_COLOR the bars themselves are
    built from -- the same thing build_grid_page.py's stats_legend() does
    for the page, so this can never quietly drift out of sync with what the
    cards actually draw the way a hand-typed key could.
    """
    from build_grid_page import (NAMED_ORDER, NAMED_VENDORS, TYPE_COLOR,
                                 TYPE_LABEL, TYPE_ORDER)
    from build_career_grid import COMMUNITY_COLOR, ERA_COLOR, PUBLISHER_COLOR

    entries = [(f"{era} (core team)", ERA_COLOR[era])
              for era in ("Bungie", "343 Industries", "Halo Studios")]
    entries += [(name, color) for name, color in (NAMED_VENDORS[k] for k in NAMED_ORDER)]
    entries += [(TYPE_LABEL[t][0].upper() + TYPE_LABEL[t][1:], TYPE_COLOR[t])
               for t in TYPE_ORDER]
    entries += [("Publisher staff", PUBLISHER_COLOR),
               ("Community volunteers", COMMUNITY_COLOR),
               ("Special thanks", T.ROLE_COLOR["thanks"])]

    out, x, y, sw = [], x0, y0, 13
    for label, color in entries:
        w = sw + 10 + len(label) * 8.2 + 30
        if x + w > x0 + width:
            x, y = x0, y + 28
        out.append(f'<rect x="{x:.0f}" y="{y - sw + 2:.0f}" width="{sw}" '
                   f'height="{sw}" rx="2" fill="{color}"/>')
        out.append(f'<text x="{x + sw + 10:.0f}" y="{y:.0f}" font-size="12.5" '
                   f'fill="{T.INK_DIM}" font-family="{T.NAMES}">'
                   f'{T.esc(label)}</text>')
        x += w
    return "".join(out), y + 30


def game_cards(a, x0: float, y0: float, width: float, game_logo,
               per_game_roles=None) -> tuple:
    from build_grid_page import (NAMED_ORDER, NAMED_VENDORS, TYPE_COLOR,
                                 TYPE_ORDER)
    from build_career_grid import ROLE_ORDER as ALL_CLASSES
    cols_n = 4
    cw = (width - GAP * (cols_n - 1)) / cols_n
    # 470 was sized before the by-role list existed. The busiest card (13
    # role classes present, 7 rows of it) now needs ~558px; padded a little
    # rather than fit exactly, since every card in a row shares one height
    # and the busiest one sets it for all of them.
    ch = 580
    out = []
    for i in range(len(COLUMNS)):
        _g, label, year, era = COLUMNS[i]
        r, c = divmod(i, cols_n)
        x = x0 + c * (cw + GAP)
        y = y0 + r * (ch + GAP)
        col = T.ERA_COLOR[era]
        seg, facts = _composition(a, i, NAMED_VENDORS, NAMED_ORDER,
                                  TYPE_COLOR, TYPE_ORDER)
        if not facts:
            continue
        out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{cw:.0f}" '
                   f'height="{ch}" rx="4" fill="#0a1019" fill-opacity="0.62" '
                   f'stroke="{T.RULE}" stroke-width="1"/>')
        out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{cw:.0f}" height="3" '
                   f'fill="{col}" opacity="0.85"/>')
        # The logo box is a fixed height and the logo is centred inside it,
        # so a tall mark and a wide one both clear the title beneath. Sizing
        # the box to each logo let the tall ones run into the type.
        uri, lw, lh = game_logo[i]
        box_top, box_h = y + 26, 82
        out.append(f'<image x="{x + (cw - lw) / 2:.0f}" '
                   f'y="{box_top + (box_h - lh) / 2:.0f}" '
                   f'width="{lw}" height="{lh}" href="{uri}"/>')
        ty = box_top + box_h + 34
        out.append(f'<text x="{x + cw / 2:.0f}" y="{ty:.0f}" '
                   f'text-anchor="middle" font-size="18" font-weight="600" '
                   f'letter-spacing="1" fill="#ffffff" '
                   f'font-family="{T.DISPLAY}">{T.esc(label)}</text>')
        out.append(f'<text x="{x + cw / 2:.0f}" y="{ty + 24:.0f}" '
                   f'text-anchor="middle" font-size="12" letter-spacing="3" '
                   f'fill="{T.INK_DIM}" font-family="{T.MONO}">{year}</text>')
        out.append(f'<text x="{x + cw / 2:.0f}" y="{ty + 74:.0f}" '
                   f'text-anchor="middle" font-size="46" font-weight="600" '
                   f'fill="{T.INK}" font-family="{T.DISPLAY}">'
                   f'{fmt(facts["total"])}</text>')
        out.append(f'<text x="{x + cw / 2:.0f}" y="{ty + 96:.0f}" '
                   f'text-anchor="middle" font-size="10.5" letter-spacing="2.6" '
                   f'fill="{T.INK_DIM}" font-family="{T.MONO}">CREDITED</text>')

        # composition bar
        bx, bw, by = x + 24, cw - 48, ty + 122
        cursor = bx
        for color, count, _lab in seg:
            sw = bw * count / facts["total"]
            out.append(f'<rect x="{cursor:.2f}" y="{by:.0f}" '
                       f'width="{max(0.8, sw):.2f}" height="13" '
                       f'fill="{color}"/>')
            cursor += sw
        out.append(f'<rect x="{bx:.0f}" y="{by:.0f}" width="{bw:.0f}" '
                   f'height="13" fill="none" stroke="{T.RULE}" '
                   f'stroke-width="0.8"/>')

        # second bar: the same roster read by role rather than by employer.
        # Always the union of every game_id in this column, not just the
        # first -- a column like "TMCC (Post-2018)" carries three ids, and
        # looking up only gids[0] silently dropped the other two whenever
        # that first id happened to already have SOME credits of its own
        # (44, against an actual combined roster of 926): the bar rendered,
        # just built from 5% of the people who should have been in it.
        roles = Counter()
        for gid in COLUMNS[i][0]:
            roles.update((per_game_roles or {}).get(gid, {}))
        stat_y = by + 100
        if roles:
            rtot = sum(roles.values())
            ry2, cursor = by + 22, bx
            for cls in ALL_CLASSES:
                if not roles.get(cls):
                    continue
                sw = bw * roles[cls] / rtot
                out.append(f'<rect x="{cursor:.2f}" y="{ry2:.0f}" '
                           f'width="{max(0.8, sw):.2f}" height="13" '
                           f'fill="{T.ROLE_COLOR[cls]}"/>')
                cursor += sw
            out.append(f'<rect x="{bx:.0f}" y="{ry2:.0f}" width="{bw:.0f}" '
                       f'height="13" fill="none" stroke="{T.RULE}" '
                       f'stroke-width="0.8"/>')
            out.append(f'<text x="{bx:.0f}" y="{by - 6:.0f}" font-size="10" '
                       f'letter-spacing="1.8" fill="{T.INK_DIM}" '
                       f'font-family="{T.MONO}">BY EMPLOYER</text>')
            out.append(f'<text x="{bx:.0f}" y="{ry2 + 26:.0f}" font-size="10" '
                       f'letter-spacing="1.8" fill="{T.INK_DIM}" '
                       f'font-family="{T.MONO}">BY ROLE</text>')

            # The bar shows proportion and nothing else -- two slivers of
            # similar width can't be told apart, and neither carries a
            # number. The page pairs its own role bar with exactly this list
            # (role_rows in build_grid_page.py); the poster had the bar
            # without it.
            rows_y = ry2 + 44
            # Highest share first, not the fixed pipeline order the bar
            # above uses -- the bar's order carries meaning (art before qa,
            # the order the game was made in), but this list's job is to be
            # scanned for what mattered most on this particular game.
            present = sorted((cls for cls in ALL_CLASSES if roles.get(cls)),
                             key=lambda c: -roles[c])
            row_h, col_gap = 17, 14
            col_w = (bw - col_gap) / 2
            for idx, cls in enumerate(present):
                rr, rc = divmod(idx, 2)
                rrx = bx + rc * (col_w + col_gap)
                rry = rows_y + rr * row_h
                pct = 100 * roles[cls] / rtot
                # A share that's genuinely present but rounds to "0%" reads
                # as a data error; it's a real sliver, just a small one.
                pct_label = "<1%" if pct < 0.5 else f"{pct:.0f}%"
                out.append(f'<rect x="{rrx:.0f}" y="{rry - 9:.0f}" width="8" '
                           f'height="8" rx="1.5" fill="{T.ROLE_COLOR[cls]}"/>')
                out.append(f'<text x="{rrx + 14:.0f}" y="{rry:.0f}" '
                           f'font-size="11" fill="{T.INK_DIM}" '
                           f'font-family="{T.NAMES}">'
                           f'{T.esc(T.ROLE_LABEL[cls])}</text>')
                out.append(f'<text x="{rrx + col_w:.0f}" y="{rry:.0f}" '
                           f'text-anchor="end" font-size="11" fill="{T.INK}" '
                           f'font-family="{T.MONO}">'
                           f'{pct_label}  ({fmt(roles[cls])})</text>')
            n_rows = (len(present) + 1) // 2
            stat_y = rows_y + n_rows * row_h + 34

        # publisher staff is one of the role classes and is in the bar above;
        # listing it here too stated the same people from a different count
        rows = [("core team", facts["core"]),
                ("vendor / contractor", facts["vendor"]),
                ("new to the franchise", facts["new"]),
                ("returning", facts["returning"])]
        ry = stat_y
        for lab, val in rows:
            if lab == "publisher staff" and not val:
                continue
            pctv = 100 * val / facts["total"]
            out.append(f'<text x="{bx:.0f}" y="{ry:.0f}" font-size="14" '
                       f'fill="{T.INK_DIM}" font-family="{T.NAMES}">'
                       f'{T.esc(lab)}</text>')
            out.append(f'<text x="{bx + bw:.0f}" y="{ry:.0f}" '
                       f'text-anchor="end" font-size="14" fill="{T.INK}" '
                       f'font-family="{T.MONO}">{pctv:.0f}%  '
                       f'{fmt(val)}</text>')
            ry += 25
    rows_n = (len(COLUMNS) + cols_n - 1) // cols_n
    return "".join(out), y0 + rows_n * (ch + GAP)


# --------------------------------------------------------------- spotlights

def spotlights(x0: float, y0: float, width: float) -> tuple:
    data = json.loads((ROOT / "config" / "spotlights.json")
                      .read_text(encoding="utf-8"))
    import html as H
    cols_n = 3
    cw = (width - GAP * (cols_n - 1)) / cols_n
    # Sized to the longest fact in spotlights.json (measured at ~164px of
    # wrapped text) plus room to breathe, not to an arbitrary round number --
    # the shortest facts only need about 118px, and a card fixed at 252
    # left roughly half of most of them blank.
    ch = 205
    out = []
    for i, s in enumerate(data):
        r, c = divmod(i, cols_n)
        x, y = x0 + c * (cw + GAP), y0 + r * (ch + GAP)
        out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{cw:.0f}" '
                   f'height="{ch}" rx="4" fill="#0a1019" fill-opacity="0.55" '
                   f'stroke="{T.RULE}" stroke-width="1"/>')
        out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="4" height="{ch}" '
                   f'fill="{T.GOLD}" opacity="0.7"/>')
        name = H.unescape(s["name"])
        fact = H.unescape(s["fact"])
        blk, ny = para(x + 26, y + 46, name, cw - 52, 22, T.GOLD,
                       family=T.DISPLAY, weight="600", lh=1.3)
        out.append(blk)
        blk, _ = para(x + 26, ny + 20, fact, cw - 52, 15.5, T.INK, lh=1.5)
        out.append(blk)
    rows_n = (len(data) + cols_n - 1) // cols_n
    return "".join(out), y0 + rows_n * (ch + GAP)


# -------------------------------------------------------------- studio field

def studio_field(a, x0: float, y0: float, width: float) -> tuple:
    """Every studio credited on each game, with its headcount."""
    from build_grid_page import NAMED_VENDORS, TYPE_COLOR
    CHIP_PAD = 8
    CHIP_GAP = 8

    # Every chip's text, up front, so its real width can be measured in one
    # headless pass rather than estimated per-chip -- see measure_widths for
    # why the estimate wasn't safe to keep.
    all_txt = []
    for i in range(len(COLUMNS)):
        for name, people in a["col_studio_people"][i].items():
            disp = a["studio_display"].get(name, name)
            n = len(people)
            all_txt.append(f"{disp}  {fmt(n)}" if n else f"{disp}  ∅")
    tw = measure_widths(all_txt, 12)

    out = []
    y = y0
    for i in range(len(COLUMNS)):
        studios = a["col_studio_people"][i]
        studio_text = "STUDIO" if len(studios) == 1 else "STUDIOS"
        if not studios:
            continue
        _g, label, year, era = COLUMNS[i]
        out.append(f'<text x="{x0:.0f}" y="{y:.0f}" font-size="17" '
                   f'font-weight="600" letter-spacing="1" '
                   f'fill="{T.ERA_COLOR[era]}" font-family="{T.DISPLAY}">'
                   f'{T.esc(label)}</text>')
        out.append(f'<text x="{x0 + 400:.0f}" y="{y:.0f}" font-size="12" '
                   f'letter-spacing="2" fill="{T.INK_DIM}" '
                   f'font-family="{T.MONO}">{len(studios)} {T.esc(studio_text)}</text>')
        y += 26
        cx_ = x0
        for name, people in sorted(studios.items(),
                                   key=lambda kv: (-len(kv[1]), kv[0].lower())):
            disp = a["studio_display"].get(name, name)
            n = len(people)
            txt = f"{disp}  {fmt(n)}" if n else f"{disp}  ∅"
            wpx = tw[txt] + CHIP_PAD * 2

            if cx_ + wpx > x0 + width:
                cx_ = x0
                y += 26
            key = name.strip().lower()
            color = NAMED_VENDORS.get(key, (None, None))[1]
            if not color:
                types = a["vtypes"].get(key) or {"development"}
                color = TYPE_COLOR.get(sorted(types)[0], "#6b6b78")
            out.append(f'<rect x="{cx_:.0f}" y="{y - 14:.0f}" '
                       f'width="{wpx:.0f}" height="20" rx="2" '
                       f'fill="{color}" fill-opacity="0.14" stroke="{color}" '
                       f'stroke-width="1" stroke-opacity="0.65"/>')
            out.append(f'<text x="{cx_ + CHIP_PAD:.0f}" y="{y:.0f}" '
                       f'font-size="12" fill="{T.INK}" opacity="0.92" '
                       f'font-family="{T.NAMES}">{T.esc(txt)}</text>')
            cx_ += wpx + CHIP_GAP
        y += 46
    return "".join(out), y


# ------------------------------------------------------------ role totals

def role_breakdown(total, x0: float, y0: float, width: float) -> tuple:
    """Every role class, counted. The legend and the statistic are the same
    object: a reader needs the colours anyway, so spending a second block on
    a separate key would say everything twice."""
    from build_career_grid import ROLE_ORDER as ALL_CLASSES
    shown = [c for c in ALL_CLASSES if total.get(c)]
    grand = sum(total[c] for c in shown)
    out = []

    # one full-width bar first, so the shape reads before the numbers do
    bw = width
    cursor = x0
    for cls in shown:
        sw = bw * total[cls] / grand
        out.append(f'<rect x="{cursor:.2f}" y="{y0:.0f}" '
                   f'width="{max(1.0, sw):.2f}" height="26" '
                   f'fill="{T.ROLE_COLOR[cls]}"/>')
        cursor += sw
    out.append(f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{bw:.0f}" height="26" '
               f'fill="none" stroke="{T.RULE}" stroke-width="1"/>')

    # Each entry is a fixed-width unit rather than a share of the row. Spread
    # across quarters of a 3,900px sheet, the count ended up a whole column
    # away from the label it belonged to.
    cols_n = 4
    entry_w = 430
    step = (width - entry_w) / (cols_n - 1)
    y = y0 + 76
    for i, cls in enumerate(shown):
        r, c = divmod(i, cols_n)
        x = x0 + c * step
        yy = y + r * 44
        out.append(f'<rect x="{x:.0f}" y="{yy - 15:.0f}" width="17" '
                   f'height="17" rx="2" fill="{T.ROLE_COLOR[cls]}"/>')
        out.append(f'<text x="{x + 28:.0f}" y="{yy:.0f}" font-size="17" '
                   f'fill="{T.INK}" font-family="{T.NAMES}">'
                   f'{T.esc(T.ROLE_LABEL[cls])}</text>')
        out.append(f'<text x="{x + entry_w - 74:.0f}" y="{yy:.0f}" '
                   f'text-anchor="end" font-size="17" fill="#ffffff" '
                   f'font-family="{T.MONO}">{fmt(total[cls])}</text>')
        out.append(f'<text x="{x + entry_w:.0f}" y="{yy:.0f}" '
                   f'text-anchor="end" font-size="13" fill="{T.INK_DIM}" '
                   f'font-family="{T.MONO}">{100*total[cls]/grand:.1f}%</text>')
    rows_n = (len(shown) + cols_n - 1) // cols_n
    out.append(f'<text x="{x0:.0f}" y="{y + rows_n * 44 + 22:.0f}" '
               f'font-size="14" fill="{T.INK_DIM}" font-family="{T.MONO}">'
               f'{fmt(grand)} credits across {len(shown)} categories. A person '
               f'counted once per game, under the most specific role the '
               f'credits give them.</text>')
    return "".join(out), y + rows_n * 44 + 44


def method_prose(x0: float, y0: float, width: float) -> tuple:
    """One continuous piece of writing, left-aligned in a single column at
    the full section width -- not split into two, which just left the right
    side of the section looking bare under a paragraph short enough to
    never reach it.
    """
    copy = json.loads((ROOT / "config" / "page-copy.json")
                      .read_text(encoding="utf-8"))
    import html as H
    text = H.unescape(copy.get("method") or "")
    # Same width the left column had back when this was two -- full section
    # width made for an unreadably long line; this keeps a normal line
    # length while the text now simply runs on rather than jumping columns.
    cw = (width - GAP * 2) / 2
    size, lh = 16, 1.55
    blk, bottom = para(x0, y0, text, cw, size, T.INK, lh=lh)
    return blk, bottom


# -------------------------------------------------------------------- notes

def notes(x0: float, y0: float, width: float, card_top: float | None = None) -> tuple:
    copy = json.loads((ROOT / "config" / "page-copy.json")
                      .read_text(encoding="utf-8"))
    import html as H
    cols_n = 2
    cw = (width - GAP * 2) / cols_n
    items = [H.unescape(f) for f in copy["footnote"]]
    half = (len(items) + 1) // 2
    columns = [items[:half], items[half:]]
    out = [f'<text x="{x0:.0f}" y="{y0:.0f}" font-size="11" '
          f'letter-spacing="2" fill="{T.INK_DIM}" font-family="{T.MONO}">'
          f'NOTES</text>']
    y0 += 28
    bottom = y0
    for c, group in enumerate(columns):
        x = x0 + c * (cw + GAP * 2)
        y = y0
        for j, text in enumerate(group):
            idx = c * half + j + 1
            out.append(f'<text x="{x:.0f}" y="{y:.0f}" font-size="15" '
                       f'font-weight="600" fill="{T.BUNGIE}" opacity="0.75" '
                       f'font-family="{T.MONO}">{idx:02d}</text>')
            blk, y = para(x + 42, y, text, cw - 42, 15, T.INK_DIM, lh=1.5)
            out.append(blk)
            y += 22
        bottom = max(bottom, y)
    out.append(f'<text x="{x0:.0f}" y="{bottom + 34:.0f}" font-size="14" '
               f'fill="{T.INK_DIM}" opacity="0.8" font-family="{T.MONO}">'
               f'{T.esc(H.unescape(copy["source"]))}</text>')
    # The source line's own baseline sits at bottom+34; total_bottom has to
    # clear that (plus its descenders) or the backing card's bottom edge
    # lands right at that text instead of past it.
    total_bottom = bottom + 50
    # The beam tower is planted rising into this block from below (see
    # total_h in poster_sheet1), and it's drawn behind every section, so the
    # text already paints on top of it -- but the tower's own glow and
    # structure are busy enough to cost the small footnote type its
    # contrast. A dark backing card, inserted so it paints before (under)
    # everything already appended above, gives the text a flat field again.
    # Styled to match the highlight cards (same fill, opacity and border)
    # rather than its own one-off colour, and stretched up to `card_top` --
    # the top of THE METHOD, one section back -- so the method prose that
    # sits just above these notes gets the same protection and the two read
    # as one card, not two.
    top = y0 - 34 if card_top is None else card_top
    out.insert(0, f'<rect x="{x0 - 24:.0f}" y="{top:.0f}" '
              f'width="{width + 48:.0f}" height="{total_bottom - top + 26:.0f}" '
              f'rx="4" fill="#0a1019" fill-opacity="0.55" '
              f'stroke="{T.RULE}" stroke-width="1"/>')
    return "".join(out), total_bottom


# -------------------------------------------------------------------- build

def build(a, x0: float, y0: float, width: float, game_logo) -> tuple:
    out, y = [], y0
    per_game, total_roles = role_counts()

    # The eleven headline facts come first, same as the web page: a reader
    # gets the whole dataset's shape before anything else, not after
    # scrolling past the grid or the per-game breakdown to find it.
    blk, y = section_head(x0, y, "THE WHOLE DATASET", "IN NUMBERS", width)
    out.append(blk)
    numbers_top = y - 10
    blk, y = dataset_numbers(x0, y + 20, width, a)
    out.append(card_behind(blk, x0, numbers_top, y + 20, width))

    # The whole-corpus breakdown comes first, so a reader has the shape of
    # "what everyone did" in mind before the per-game cards break the same
    # thing down game by game -- the aggregate is the context the per-game
    # numbers get read against, not an afterthought below them.
    y += 90
    blk, y = section_head(x0, y, "THE WORK", "PART TWO", width)
    out.append(blk)
    work_top = y - 10
    blk, y = role_breakdown(total_roles, x0, y + 24, width)
    out.append(card_behind(blk, x0, work_top, y + 20, width))

    y += 90
    blk, y = section_head(x0, y, "THE NUMBERS", "GAME BY GAME", width)
    out.append(blk)
    blk, y = studio_legend(x0, y + 20, width)
    out.append(blk)
    blk, y = game_cards(a, x0, y + 24, width, game_logo, per_game)
    out.append(blk)

    y += 90
    blk, y = section_head(x0, y, "THE EXTERNAL STUDIOS", "WHO ELSE WAS THERE",
                          width)
    out.append(blk)
    studios_top = y - 10
    # Same colour scheme as the numbers cards' "by employer" bar -- a named
    # vendor keeps its own colour, everyone else is grouped by the kind of
    # work. Repeated here rather than trusted to memory from the section
    # above, since a reader who jumps straight to this one shouldn't have to
    # scroll back up to know what a chip's border colour means.
    legend_blk, y = studio_legend(x0, y + 20, width)
    field_blk, y = studio_field(a, x0, y + 6, width)
    out.append(card_behind(legend_blk + field_blk, x0, studios_top, y + 20, width))

    y += 70
    blk, y = section_head(x0, y, "THE HIGHLIGHTS", "SIX FINDINGS", width)
    out.append(blk)
    blk, y = spotlights(x0, y + 20, width)
    out.append(blk)

    y += 70
    blk, y = section_head(x0, y, "THE METHOD", "HOW IT WAS BUILT", width)
    out.append(blk)
    method_top = y + 24
    blk, y = method_prose(x0, method_top, width)
    out.append(blk)
    copy = json.loads((ROOT / "config" / "page-copy.json").read_text(encoding="utf-8"))
    if copy.get("tools"):
        import html as H
        blk, y = para(x0, y + 40, H.unescape(copy["tools"]), width, 13,
                     T.INK_DIM, lh=1.5)
        out.append(blk)
    blk, y = notes(x0, y + 40, width, card_top=method_top - 34)
    out.append(blk)
    return "".join(out), y

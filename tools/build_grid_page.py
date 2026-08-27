"""Render the complete career-grid page (grid + derived statistics).

`build_career_grid` owns the SVG; this module owns everything around it. Both
were reverse-engineered from `final-grid-v4.html` and verified by regenerating
that file byte-for-byte from the dataset it was originally built against, so
the design survives a data refresh instead of being re-derived by hand.

Everything here is computed over the same 12-column spine the grid uses, NOT
the raw 14-game sequence -- "new to the franchise" means "first credited in
this column", so MCC's post-2018 releases cannot make a returning maintainer
look like a newcomer.
"""
import csv
import html as htmllib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from halocredits.identity import load_aliases
from halocredits.studios import classify_studio, load_studio_classes, normalise_studio
from build_career_grid import (COLUMNS, COL_X, COMMUNITY_COLOR, ERA_COLOR,
                               GAME_TO_COL, GAP_LINE, GOLD, LEGACY_NON_PEOPLE,
                               ROLE_COLOR, ROLE_LABEL, ROLE_ORDER,
                               PUBLISHER_COLOR, build, esc, fmt)

# Vendors worth tracking by name rather than by kind of work: either they
# recur across the franchise (Aquent on 8 games, Volt on 6) or they put a
# large crew on a single game (Virtuos Chengdu's 304 on Campaign Evolved,
# Blur's 241 on MCC) -- a block that big disappears if it is folded into a
# generic "other development" segment.
#
# Colors only have to be distinguishable between vendors that appear on the
# SAME game, so they are assigned against actual co-occurrence: at most nine
# of these ever share a card. Verified to leave no similar pair co-occurring,
# and to stay clear of the era colors, the gold/violet connectors and the
# teal used for community volunteers.
NAMED_VENDORS = {
    "experis": ("Experis", "#e0538a"),                        # 740p 5g
    "saber interactive": ("Saber Interactive", "#b03060"),    # 334p 3g
    "virtuos chengdu": ("Virtuos Chengdu", "#8fd14f"),        # 304p 1g
    "certain affinity": ("Certain Affinity", "#7fbf5f"),      # 257p 4g
    "blur": ("Blur", "#c9c93a"),                              # 241p 1g
    "skybox labs": ("SkyBox Labs", "#e8825c"),                # 189p 3g
    "volt": ("Volt", "#9fd0a0"),                              # 187p 6g
    "digic": ("Digic", "#ff8fa3"),                            # 167p 1g
    "insight global": ("Insight Global", "#4caf50"),          # 154p 5g
    "sperasoft": ("Sperasoft", "#7fd0d0"),                    # 154p 1g
    "virtuos sparx": ("Virtuos Sparx", "#e07be0"),            # 145p 1g
    "keywords studios": ("Keywords Studios", "#d9b038"),      # 127p 2g
    "abbey road studios": ("Abbey Road Studios", "#d96f9a"),  # 124p 1g
    "lionbridge games": ("Lionbridge Games", "#8c6239"),      # 116p 1g
    "splash damage": ("Splash Damage", "#e8825c"),            # 106p 1g
    "axis studios": ("Axis Studios", "#d9b038"),              # 105p 1g
    "yoh services": ("YOH Services", "#d119e6"),              #  91p 4g
    "aquent": ("Aquent", "#5b7fd9"),                          #  78p 8g
}
TYPE_COLOR = {"development": "#6b6b78", "testing": "#5a7d9a",
              "publishing": "#30e8b1", "cinematic-sound": "#7a5ec9"}
TYPE_LABEL = {"development": "other development", "testing": "testing / QA",
              "publishing": "publishing", "cinematic-sound": "cinematic / sound"}
# segbar order follows the legend, not headcount, so the same company sits in
# the same place on every card
NAMED_ORDER = list(NAMED_VENDORS)
TYPE_ORDER = ["development", "testing", "publishing", "cinematic-sound"]


def pct(n, d):
    return f"{round(100 * n / d)}%" if d else "0%"


def load_vendor_types(root):
    out = {}
    with open(root / "config" / "vendor-types.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[normalise_studio(r["studio"])] = r["type"]
    return out


def load_studio_only(root):
    rows = []
    with open(root / "config" / "studio-only-credits.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    return rows


def analyse(root, people_csv, credits_dir, exclude, group_by_shape=True,
            include_publishers=True):
    """Everything the page needs, keyed to the 12-column spine."""
    classes = load_studio_classes(root / "config" / "studio-classes.csv")
    vtypes = load_vendor_types(root)
    # the same aliases.csv identity resolution data/people.csv already had --
    # publisher staff and volunteers are read straight from the credit rows,
    # so without it the same person arrives twice under two spellings
    role_by_person, role_totals, role_by_col = _roles(root)
    svg, people, rows, overflow = build(people_csv, credits_dir, exclude,
                                       group_by_shape, include_publishers,
                                       load_aliases(root / "config" / "aliases.csv"),
                                       roles=role_by_person)

    core = [p for p in people if not p["community"]]
    by_name = {p["name"]: p for p in people}

    # name -> every variant, so credit rows can be attributed back to a person
    variant_to_name = {}
    with open(people_csv, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["display_name"] in exclude:
                continue
            for v in r["variants"].split("|"):
                variant_to_name[v] = r["display_name"]

    col_people = defaultdict(set)
    col_studio_people = defaultdict(lambda: defaultdict(set))   # col -> studio -> names
    person_vendor = defaultdict(set)                            # name -> {col}
    person_vendor_type = defaultdict(set)                       # (name,col) -> {type}
    studio_spellings = defaultdict(Counter)                     # key -> raw spellings
    person_named_vendor = {}                                    # (name,col) -> key
    col_publishing = defaultdict(set)                           # col -> names

    for gid, col in GAME_TO_COL.items():
        path = Path(credits_dir) / f"{gid}.csv"
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["inclusion_class"] == "publishing":
                    # the publisher's own staff -- Xbox, Microsoft Game
                    # Studios, marketing, localization. They are credited on
                    # the game but were never on its development team, so the
                    # career grid excludes them; counting them here is the
                    # only place they are visible.
                    col_publishing[col].add(row["name_raw"])
                nm = variant_to_name.get(row["name_raw"])
                if nm is None:
                    if row["inclusion_class"] != "community":
                        continue
                    nm = row["name_raw"]
                    if nm not in by_name:
                        continue
                # only attribute a credit row to a column the grid actually
                # draws this person in -- a special-thanks or publishing row
                # must not add someone to a roster they aren't counted in
                if col not in by_name[nm]["cols"]:
                    continue
                studio = row["studio"]
                if studio and classify_studio(studio, classes) == "vendor":
                    # key on the normalised name: the same company is credited
                    # as "Experis"/"EXPERIS" and "SkyBox Labs, Inc."/"Skybox
                    # Labs, Inc." across rolls, and keying on the raw string
                    # splits one vendor into several chips.
                    key = normalise_studio(studio)
                    col_studio_people[col][key].add(nm)
                    if key in NAMED_VENDORS:
                        person_named_vendor[(nm, col)] = key
                    studio_spellings[key][studio] += 1
                    person_vendor[nm].add(col)
                    person_vendor_type[(nm, col)].add(vtypes.get(key, "development"))

    # a person "belongs" to a column if the grid draws them there
    for p in people:
        for c in p["cols"]:
            col_people[c].add(p["name"])

    studio_only = defaultdict(list)
    for r in load_studio_only(root):
        col = GAME_TO_COL.get(r["game_id"])
        if col is not None:
            studio_only[col].append(r)

    return dict(role_totals=role_totals, role_by_col=role_by_col,
                svg=svg, people=people, core=core, rows=rows, overflow=overflow,
                by_name=by_name, col_people=col_people,
                col_studio_people=col_studio_people, person_vendor=person_vendor,
                person_vendor_type=person_vendor_type, studio_only=studio_only,
                vtypes=vtypes, classes=classes,
                person_named_vendor=person_named_vendor,
                col_publishing=col_publishing,
                # display each vendor under whichever spelling credits the most
                # people, so the chip carries the company's usual name
                studio_display={k: c.most_common(1)[0][0]
                                for k, c in studio_spellings.items()})


def chips_for_column(a, col):
    """Named vendors first, then by headcount, then the credited-but-unnamed."""
    counts = {k: len(v) for k, v in a["col_studio_people"][col].items()}
    named, other = [], []
    for key, n in counts.items():
        studio = a["studio_display"].get(key, key)
        if key in NAMED_VENDORS:
            named.append((NAMED_VENDORS[key][1], NAMED_VENDORS[key][0], n))
        else:
            other.append((studio, n))
    named.sort(key=lambda t: -t[2])
    other.sort(key=lambda t: -t[1])

    out = []
    for color, studio, n in named:
        out.append(f'<span class="studiochip" style="border-color:{color};'
                   f'color:{color};">{esc(studio)} <b>{n}</b></span>')
    for studio, n in other:
        t = a["vtypes"].get(normalise_studio(studio), "development")
        out.append(f'<span class="studiochip" style="border-color:{TYPE_COLOR[t]}44;'
                   f'color:#c8d4e0;" title="{TYPE_LABEL[t]}">{esc(studio)} '
                   f'<b>{n}</b></span>')
    for r in a["studio_only"].get(col, []):
        t = r["type"]
        out.append(f'<span class="studiochip studiochip-only" '
                   f'style="border-color:{TYPE_COLOR[t]};color:#8b93a3;" '
                   f'title="{TYPE_LABEL[t]} &#183; {esc(r["role"])} &#183; credited, '
                   f'no individual named">{esc(r["studio"])} <b>&#8709;</b></span>')
    return out, len(counts) + len(a["studio_only"].get(col, []))


def _roles(root):
    """Role class per person per grid column, plus the counts.

    The grid is indexed by column, and a column can cover several releases --
    MCC's 2018, 2021 and 2025 updates share one -- so a person's role is
    resolved per game and then folded onto the column they land in. Where the
    same person did different work on two releases inside one column, the
    most specific claim wins, the same rule the resolver uses within a game.
    """
    import csv as _csv
    import glob as _glob
    from collections import Counter, defaultdict
    from halocredits.roles import (PRIORITY, load_category_patterns,
                                   load_heading_index, load_heading_patterns,
                                   load_mobygames_roles, load_name_tags,
                                   load_vendor_types, resolve)

    vt = load_vendor_types(root / "config" / "vendor-types.csv")
    hp = load_heading_patterns(root / "config" / "role-headings.csv")
    ix = load_heading_index(root / "data" / "source-headings.csv")
    nt = load_name_tags(root / "data" / "name-role-tags.csv")
    mb = load_mobygames_roles(root / "data" / "mobygames-roles.csv")
    cp = load_category_patterns(root / "config" / "category-map.csv")
    rank = {c: i for i, c in enumerate(PRIORITY)}

    pairs = defaultdict(list)
    for path in _glob.glob(str(root / "data" / "credits" / "*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in _csv.DictReader(fh):
                pairs[(r["name_raw"], r["game_id"])].append(
                    (r["category"], r["studio"], r["source_ref"],
                     r["role_raw"], r["inclusion_class"]))

    by_person = defaultdict(dict)
    totals, by_col = Counter(), defaultdict(Counter)
    for (name, game), rws in pairs.items():
        cls, _prov = resolve(rws, vt, hp, game, ix, name, nt, mb, cp)
        totals[cls] += 1
        col = GAME_TO_COL.get(game)
        if col is None:
            continue
        by_col[col][cls] += 1
        held = by_person[name].get(col)
        if held is None or rank.get(cls, 99) < rank.get(held, 99):
            by_person[name][col] = cls
    return dict(by_person), totals, dict(by_col)


ROLE_CSS = """
.rolekey{display:flex;flex-wrap:wrap;gap:4px 18px;margin:8px 0 14px;
  font-size:11px;color:#8b93a3;}
.rolekey .rk{display:inline-flex;align-items:center;gap:6px;}
.rolekey .rk i{width:9px;height:9px;border-radius:2px;display:inline-block;}
.rolekey .rk b{color:#c8d4e0;font-weight:600;font-variant-numeric:tabular-nums;}
.rolekey .rk u{text-decoration:none;color:#5c6b7f;font-size:10px;}
.barlab{font-size:9px;letter-spacing:1.4px;color:#5c6b7f;margin:6px 0 2px;
  text-transform:uppercase;}
.rolerows{display:grid;grid-template-columns:1fr 1fr;gap:0 14px;margin:6px 0 2px;}
.rolerows .rrow{display:flex;justify-content:space-between;align-items:center;
  font-size:10px;color:#8b93a3;padding:1px 0;}
.rolerows .rrow i{width:7px;height:7px;border-radius:2px;display:inline-block;
  margin-right:5px;}
.rolerows .rrow b{color:#c8d4e0;font-weight:600;font-variant-numeric:tabular-nums;}
.rolerows .rrow b i{color:#5c6b7f;font-style:normal;font-weight:400;
  width:auto;height:auto;margin:0;}
"""


def _inject_role_css(h):
    """Add the role key's rules to the template's stylesheet, once."""
    if ".rolekey{" in h:
        return h
    i = h.rfind("</style>")
    return h if i < 0 else h[:i] + ROLE_CSS + h[i:]


def role_legend(a):
    """The role key, counted. The reader needs the colours anyway, so the
    legend and the statistic are one block rather than two."""
    total = a["role_totals"]
    grand = sum(total.values())
    items = []
    for cls in ROLE_ORDER:
        if not total.get(cls):
            continue
        items.append(
            f'<span class="rk"><i style="background:{ROLE_COLOR[cls]}"></i>'
            f'{ROLE_LABEL[cls]}<b>{fmt(total[cls])}</b>'
            f'<u>{100*total[cls]/grand:.1f}%</u></span>')
    return ('<div class="rolekey">' + "".join(items) + '</div>')


def role_rows(a, col):
    """The same roster as the bar, in figures.

    A bar shows proportion and nothing else: it cannot be read off, and two
    slivers of similar width are indistinguishable. Every class present gets
    its count and share, so the composition of one game can actually be
    quoted rather than only glanced at.
    """
    counts = a["role_by_col"].get(col) or {}
    tot = sum(counts.values())
    if not tot:
        return ""
    out = []
    for cls in ROLE_ORDER:
        n = counts.get(cls)
        if not n:
            continue
        out.append(
            f'<div class="rrow"><span><i style="background:'
            f'{ROLE_COLOR[cls]}"></i>{ROLE_LABEL[cls]}</span>'
            f'<b>{pct(n, tot)} <i>({fmt(n)})</i></b></div>')
    return '<div class="rolerows">' + "".join(out) + "</div>"


def role_bar(a, col):
    """One game's roster read by role rather than by employer."""
    counts = a["role_by_col"].get(col) or {}
    tot = sum(counts.values())
    if not tot:
        return ""
    seg = []
    for cls in ROLE_ORDER:
        if not counts.get(cls):
            continue
        seg.append(f'<div style="width:{100*counts[cls]/tot:.2f}%;'
                   f'background:{ROLE_COLOR[cls]};" title="{ROLE_LABEL[cls]}: '
                   f'{fmt(counts[cls])}"></div>')
    return ('<div class="barlab">by role</div>'
            '<div class="segbar">' + "".join(seg) + '</div>')


def grid_legend():
    """The key above the grid. Generated, so the markers can never drift from
    the ones the grid draws. It shows each marker rather than naming its
    color, since the marker is what the reader has to find."""
    return (
        '<div class="lg">'
        '<span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" '
        f'stroke="{GOLD}" stroke-width="1.8"/></svg>&nbsp;credited on the very '
        'next game</span>'
        '<span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" '
        f'stroke="{GAP_LINE}" stroke-width="1.2" stroke-dasharray="2,2"/></svg>'
        '&nbsp;returned after a gap</span>'
        '<span><span class="sw" style="background:#8b93a3;border-radius:50%;">'
        '</span>credited</span>'
        '<span><span class="sw" style="background:#8b93a3;"></span>last '
        'credit</span>'
        f'<span><svg width="10" height="10"><polygon points="5,1 1,8 9,8" '
        f'fill="{GOLD}"/></svg>&nbsp;credits reprinted from an earlier '
        'game</span>'
        # Publisher staff and community volunteers used to need their own
        # swatch here, back when they were the only two classes drawn
        # outside the era colours. Both are role classes now, so role_legend
        # (concatenated right after this) already names and counts them --
        # repeating them here just said the same thing twice.
        '<span><span class="sw" style="background:#00a3e3;border-radius:50%;">'
        '</span>Bungie</span>'
        '<span><span class="sw" style="background:#d95926;border-radius:50%;">'
        '</span>343 Industries</span>'
        '<span><span class="sw" style="background:#ffffff;border-radius:50%;">'
        '</span>Halo Studios</span>'
        "</div>")


def stats_legend():
    """The swatch key under "Stats for every game" -- generated, so it can
    never drift from the colors the cards actually use."""
    parts = [f'<span><span class="sw" style="background:{c}"></span>{esc(n)}</span>'
             for n, c in (NAMED_VENDORS[k] for k in NAMED_ORDER)]
    parts += [f'<span><span class="sw" style="background:{TYPE_COLOR[t]}"></span>'
              f'{TYPE_LABEL[t][0].upper()}{TYPE_LABEL[t][1:]}</span>' for t in TYPE_ORDER]
    parts = ([f'<span><span class="sw" style="background:{c}"></span>{n} '
              f'(core team)</span>'
              for n, c in (("Bungie", ERA_COLOR["Bungie"]),
                           ("343 Industries", ERA_COLOR["343 Industries"]),
                           ("Halo Studios", ERA_COLOR["Halo Studios"]))] + parts)
    parts += [f'<span><span class="sw" style="background:{PUBLISHER_COLOR}"></span>'
              f'Publisher staff</span>',
              f'<span><span class="sw" style="background:{COMMUNITY_COLOR}"></span>'
              f'Community volunteers</span>',
              f'<span><span class="sw" style="background:{ROLE_COLOR["thanks"]}"></span>'
              f'Special thanks</span>']
    return '<div class="lg">' + "".join(parts) + "</div>"


def stat_cards(a):
    out = []
    for i, (gids, label, year, era) in enumerate(COLUMNS):
        names = a["col_people"][i]
        total = len(names)
        if not total:
            continue
        newcomers = sum(1 for n in names if a["by_name"][n]["cols"][0] == i)
        returning = total - newcomers
        vend = sum(1 for n in names if i in a["person_vendor"].get(n, ()))
        # Per GAME, not per person. The publisher flag is set on a person
        # once and then counted on every game they appear on, so someone who
        # was publisher staff on Halo 5 and a developer on MCC was being
        # counted as publisher staff on MCC too.
        npub = len(set(names) & set(a["col_publishing"].get(i, ())))
        ncom = sum(1 for n in names if a["by_name"][n]["community"])
        nthanks = sum(1 for n in names if a["by_name"][n].get("special_thanks"))
        first_party = total - vend - npub - ncom - nthanks

        # segbar: first-party in the game's own era color, then each named
        # vendor in legend order, then the remaining vendors by kind of work
        seg = []
        if first_party:
            seg.append(f'<div style="width:{100*first_party/total:.2f}%;'
                       f'background:{ERA_COLOR[era]};" title="First-Party: {fmt(first_party)}"></div>')
        named_here, typed = {}, Counter()
        for n in names:
            if i not in a["person_vendor"].get(n, ()):
                continue
            key = a["person_named_vendor"].get((n, i))
            if key:
                named_here.setdefault(key, set()).add(n)
            else:
                for ty in sorted(a["person_vendor_type"].get((n, i), {"development"}))[:1]:
                    typed[ty] += 1
        for key in NAMED_ORDER:
            if key in named_here:
                label_, color = NAMED_VENDORS[key]
                c = len(named_here[key])
                seg.append(f'<div style="width:{100*c/total:.2f}%;background:{color};" '
                           f'title="{label_}: {fmt(c)}"></div>')
        for ty in TYPE_ORDER:
            if typed.get(ty):
                c = typed[ty]
                seg.append(f'<div style="width:{100*c/total:.2f}%;background:{TYPE_COLOR[ty]};" '
                           f'title="{TYPE_LABEL[ty]}: {fmt(c)}"></div>')
        if npub:
            seg.append(f'<div style="width:{100*npub/total:.2f}%;background:{PUBLISHER_COLOR};" '
                       f'title="publisher staff: {fmt(npub)}"></div>')
        if ncom:
            seg.append(f'<div style="width:{100*ncom/total:.2f}%;background:{COMMUNITY_COLOR};" '
                       f'title="community volunteers: {fmt(ncom)}"></div>')
        if nthanks:
            seg.append(f'<div style="width:{100*nthanks/total:.2f}%;'
                       f'background:{ROLE_COLOR["thanks"]};" '
                       f'title="special thanks: {fmt(nthanks)}"></div>')

        lineage = ""
        if era != "Bungie":
            # the same pool the core-team row above counts: development
            # staff with no vendor credit on this game. Publisher staff and
            # volunteers were never on the team and must not pad it.
            fp_names = [n for n in names
                        if i not in a["person_vendor"].get(n, ())
                        and not a["by_name"][n].get("publisher")
                        and not a["by_name"][n]["community"]]

            def prior_core(era_name):
                """On the studio's own team before, not a vendor on its games:
                someone contracted onto Halo 4 by an agency did not "come from
                343", so the prior credit has to be first-party too."""
                return sum(1 for n in fp_names
                           if any(COLUMNS[c][3] == era_name
                                  and c not in a["person_vendor"].get(n, ())
                                  for c in a["by_name"][n]["cols"] if c < i))

            def prior_any(era_name):
                return sum(1 for n in names
                           if any(COLUMNS[c][3] == era_name
                                  for c in a["by_name"][n]["cols"] if c < i))

            pb_core, pb_all = prior_core("Bungie"), prior_any("Bungie")
            lineage = ('<div class="statcard-divider"></div>'
                       f'<div class="statcard-row"><span>from Bungie (core team)</span>'
                       f'<b>{pct(pb_core, len(fp_names))} <i>({fmt(pb_core)}/{fmt(len(fp_names))})</i></b></div>'
                       f'<div class="statcard-row"><span>from Bungie (everyone credited)</span>'
                       f'<b>{pct(pb_all, total)} <i>({fmt(pb_all)}/{fmt(total)})</i></b></div>')
            # a 343-era game cannot report people who arrived "from 343" -- it
            # is 343. Only Halo Studios sits downstream of both.
            if era == "Halo Studios":
                p3_core, p3_all = prior_core("343 Industries"), prior_any("343 Industries")
                lineage += (f'<div class="statcard-row"><span>from 343 (core team)</span>'
                            f'<b>{pct(p3_core, len(fp_names))} <i>({fmt(p3_core)}/{fmt(len(fp_names))})</i></b></div>'
                            f'<div class="statcard-row"><span>from 343 (everyone credited)</span>'
                            f'<b>{pct(p3_all, total)} <i>({fmt(p3_all)}/{fmt(total)})</i></b></div>')

        # Both marked classes are part of the total: the credits name them.
        # They are shown as their own share so no developer or vendor figure
        # quietly absorbs them.
        def marked_row(label, n, color):
            return (f'<div class="statcard-row"><span>'
                    f'<span style="display:inline-block;width:7px;height:7px;'
                    f'border-radius:2px;background:{color};margin-right:5px;">'
                    f'</span>{label}</span>'
                    f'<b>{pct(n, total)} <i>({fmt(n)}/{fmt(total)})</i></b></div>')

        # Publisher staff and volunteers are two of the role classes and are
        # listed by role above, per game. Repeating them here stated the same
        # people twice from two different counts -- a person-level flag versus
        # a per-game resolution -- which is why the two disagreed on the same
        # card. The employer block now says only core versus vendor.
        publishing = ""

        _, nstudios = chips_for_column(a, i)
        out.append(f"""      <div class="statcard">
        <div class="statcard-head" style="color:{ERA_COLOR[era]};">{esc(label)} <span>&middot; {year}</span></div>
        <div class="statcard-total">{fmt(total)} credited</div>
        <div class="barlab">by employer</div>
        <div class="segbar">{''.join(seg)}</div>
        {role_bar(a, i)}
        {role_rows(a, i)}
        <div class="statcard-row"><span>new to the franchise</span><b>{pct(newcomers,total)} <i>({fmt(newcomers)}/{fmt(total)})</i></b></div>
        <div class="statcard-row"><span>returning to the franchise</span><b>{pct(returning,total)} <i>({fmt(returning)}/{fmt(total)})</i></b></div>
        <div class="statcard-row"><span><span style="display:inline-block;width:7px;height:7px;border-radius:2px;background:{ERA_COLOR[era]};margin-right:5px;"></span>core team</span><b>{pct(first_party,total)} <i>({fmt(first_party)}/{fmt(total)})</i></b></div>
        <div class="statcard-row"><span>vendor / contractor</span><b>{pct(vend,total)} <i>({fmt(vend)}/{fmt(total)})</i></b></div>
        {publishing}
        {lineage}
        <div class="statcard-divider"></div>
        <div class="statcard-row"><span>external studios</span><b>{nstudios}</b></div>
      </div>""")
    return "\n".join(out)


def studio_sections(a):
    out = []
    for i, (gids, label, year, era) in enumerate(COLUMNS):
        chips, _ = chips_for_column(a, i)
        if not chips:
            continue
        out.append(f'<div class="studiogame"><div class="studiogame-head" '
                   f'style="color:{ERA_COLOR[era]};">{esc(label)}</div>'
                   f'<div class="studiochips">{"".join(chips)}</div></div>')
    return "".join(out)


def hero_stats(a):
    """The eleven headline numbers, all computed on the 12-column spine."""
    # Two different populations, and mixing them is what made these figures
    # disagree with the cards: "credited" is everyone the credits name, while
    # every developer statistic below is about development staff only --
    # publisher staff hold no vendor credits and were never on the team, so
    # counting them deflates vendor share and inflates a lineage denominator.
    everyone = a["people"]
    dev = [p for p in everyone if not p.get("publisher") and not p["community"]]
    total = len(everyone)
    multi = [p for p in everyone if len(p["cols"]) >= 2]
    with_vendor = sum(1 for p in everyone if a["person_vendor"].get(p["name"]))

    studio_games = defaultdict(set)
    studio_people = defaultdict(set)
    for col, studios in a["col_studio_people"].items():
        for s, names in studios.items():
            studio_games[normalise_studio(s)].add(col)
            studio_people[normalise_studio(s)] |= names
    n_studios = len(studio_games)
    one_game = sum(1 for s, g in studio_games.items() if len(g) == 1)
    top = max(studio_people.items(), key=lambda kv: len(kv[1]))
    top_label = next((NAMED_VENDORS[top[0]][0] if top[0] in NAMED_VENDORS else top[0]
                      for _ in [0]))

    # count transitions, not people: these are the gold and violet links the
    # grid actually draws
    unbroken = sum(1 for p in multi
                   for x, b in zip(p["cols"], p["cols"][1:]) if b - x == 1)
    returns = sum(1 for p in multi
                  for x, b in zip(p["cols"], p["cols"][1:]) if b - x > 1)

    def era_cols(name):
        return {COLUMNS[c][3] for c in a["by_name"][name]["cols"]}
    all_three = sum(1 for p in everyone if len(era_cols(p["name"])) == 3)

    gaps = []
    for p in multi:
        for x, b in zip(p["cols"], p["cols"][1:]):
            if b - x > 1:
                gaps.append(int(COLUMNS[b][2][:4]) - int(COLUMNS[x][2][:4]))
    longest = max(gaps) if gaps else 0
    n_longest = sum(1 for p in multi
                    if any(int(COLUMNS[b][2][:4]) - int(COLUMNS[x][2][:4]) == longest
                           for x, b in zip(p["cols"], p["cols"][1:]) if b - x > 1))

    dev_names = {p["name"] for p in dev}

    def prior_core(era_name, name, upto):
        return any(COLUMNS[c][3] == era_name and c not in a["person_vendor"].get(name, ())
                   for c in a["by_name"][name]["cols"] if c < upto)

    def prior_any(era_name, name, upto):
        return any(COLUMNS[c][3] == era_name
                   for c in a["by_name"][name]["cols"] if c < upto)

    ce = len(COLUMNS) - 1
    ce_names = list(a["col_people"][ce])          # everyone credited on it
    ce_fp = [n for n in ce_names                  # its own core team
             if ce not in a["person_vendor"].get(n, ()) and n in dev_names]
    ce_b_core = sum(1 for n in ce_fp if prior_core("Bungie", n, ce))
    ce_b_all = sum(1 for n in ce_names if prior_any("Bungie", n, ce))
    ce_3_core = sum(1 for n in ce_fp if prior_core("343 Industries", n, ce))
    ce_3_all = sum(1 for n in ce_names if prior_any("343 Industries", n, ce))

    # 343-era staff, deduplicated across the era's six columns; community
    # volunteers are excluded from every developer/vendor statistic
    uniq_fp, uniq_all = set(), set()
    for i, (_g, _l, _y, era) in enumerate(COLUMNS):
        if era != "343 Industries":
            continue
        for n in a["col_people"][i]:
            uniq_all.add(n)
            if n not in dev_names:
                continue
            if i not in a["person_vendor"].get(n, ()):
                uniq_fp.add(n)
    later_fp, later_all = len(uniq_fp), len(uniq_all)
    later_fp_b = sum(1 for n in uniq_fp
                     if any(COLUMNS[c][3] == "Bungie" and c not in a["person_vendor"].get(n, ())
                            for c in a["by_name"][n]["cols"]))
    later_all_b = sum(1 for n in uniq_all
                      if any(COLUMNS[c][3] == "Bungie" for c in a["by_name"][n]["cols"]))

    def card(num, label):
        return f'<div><div class="hero-num">{num}</div><div class="hero-label">{label}</div></div>'

    return "".join([
        card(fmt(total), "people are credited across 25 years and 14 releases, including the publisher's own staff and the volunteers"),
        card(pct(with_vendor, total), f"of everyone credited holds at least one vendor or contractor credit <i>({fmt(with_vendor)}/{fmt(total)})</i>"),
        card(fmt(n_studios), f"external vendor studios worked on Halo. {fmt(one_game)} of them on exactly one game, {fmt(n_studios-one_game)} on two or more"),
        card(fmt(len(top[1])), f"people came from {esc(top_label.title() if top_label.islower() else top_label)}, the largest of any single vendor, across {len(studio_games[top[0]])} games"),
        card(fmt(unbroken), f"times someone went straight from one game to the next, across the {fmt(len(multi))} people credited on more than one"),
        card(fmt(returns), "returns after a gap of one or more games"),
        card(pct(later_fp_b, later_fp), f"of the 343-era studios' own staff had worked on a Bungie Halo game before <i>({fmt(later_fp_b)}/{fmt(later_fp)})</i>. Counting everyone credited it is {pct(later_all_b, later_all)} <i>({fmt(later_all_b)}/{fmt(later_all)})</i>"),
        card(pct(ce_3_core, len(ce_fp)), f"of Campaign Evolved's core team had worked under 343 before <i>({fmt(ce_3_core)}/{fmt(len(ce_fp))})</i>. Counting everyone credited it is {pct(ce_3_all, len(ce_names))} <i>({fmt(ce_3_all)}/{fmt(len(ce_names))})</i>"),
        card(pct(ce_b_core, len(ce_fp)), f"of Campaign Evolved's core team had worked under Bungie before <i>({fmt(ce_b_core)}/{fmt(len(ce_fp))})</i>. Counting everyone credited it is {pct(ce_b_all, len(ce_names))} <i>({fmt(ce_b_all)}/{fmt(len(ce_names))})</i>"),
        card(fmt(all_three), "people are credited under all three studio names: Bungie, 343 Industries, and Halo Studios"),
        card(fmt(n_longest), f"people share the longest confirmed gap here, {longest} years, all of them between Combat Evolved and Campaign Evolved"),
    ])


PAGE = """<title>Every Halo Credit</title>
{style}
<div class="wrap">
  <div class="title">Everyone credited on a Halo game, 2001 to 2026</div>
  <div class="sub">{total} people &middot; {multi} credited on more than one game.</div>
  <div class="lg">
    <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="#ffd166" stroke-width="1.8"/></svg>&nbsp;<b>Gold</b> credited on the very next game</span>
    <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="#9d7bea" stroke-width="1" opacity="0.6" stroke-dasharray="2,2"/></svg>&nbsp;<b>Dashed violet</b> returned after a gap</span>
    <span><span class="sw" style="background:#8b93a3;border-radius:50%;"></span>credited</span>
    <span><span class="sw" style="background:#8b93a3;"></span><b>square</b> last credit</span>
    <span><span class="sw" style="background:#4a9d8f;"></span><b>teal</b> community volunteer</span>
    <span><span class="sw" style="background:#00a3e3;border-radius:50%;"></span>Bungie</span>
    <span><span class="sw" style="background:#d95926;border-radius:50%;"></span>343</span>
    <span><span class="sw" style="background:#ffffff;border-radius:50%;"></span>Halo Studios</span>
  </div>
  <div class="hint">canvas 2,700 x {height}px &#183; scroll sideways for the later games</div>
  <div class="scroller">{svg}</div>

  <div class="section-label">The whole dataset, in numbers</div>
  <div class="hero-row">{hero}</div>

  <div class="section-label">External studios per game</div>
  <div class="zonenote" style="color:#8b93a3;font-size:11px;margin-bottom:10px;">Every distinct studio credited on each game, by real headcount. The 6 named studios keep their own color; the border color on every other chip shows which of development / testing / cinematic-sound / publishing it falls into, hover for the label. Dashed, italic chips marked &#8709; are companies the source credits by name with no individual attached: real, not a headcount.</div>
  {studios}

  <div class="section-label">Stats for every game</div>
  <div class="lg"><span><span class="sw" style="background:#e0538a;"></span>Experis</span><span><span class="sw" style="background:#4caf7d;"></span>Saber Interactive</span><span><span class="sw" style="background:#5b7fd9;"></span>SkyBox Labs</span><span><span class="sw" style="background:#e8825c;"></span>Certain Affinity</span><span><span class="sw" style="background:#c9c93a;"></span>Insight Global</span><span><span class="sw" style="background:#b8895f;"></span>Keywords Studios</span><span><span class="sw" style="background:#5c6b7f;"></span>Other development</span><span><span class="sw" style="background:#4a9d5f;"></span>Testing / QA</span><span><span class="sw" style="background:#c9a13a;"></span>Publishing</span><span><span class="sw" style="background:#7a5ec9;"></span>Cinematic / sound</span></div>
  <div class="statgrid">
{cards}
  </div>

  <div class="footnote">
    <ul>
      <li>With the exception of MCC's post-launch updates, every game's credits are taken from its initial release, not from later patches.</li>
      <li>A remade or remastered game's original credits are not counted as new work for the remaster: Combat Evolved Anniversary and Campaign Evolved do not double-count Combat Evolved's own 2001 credits, and a name appearing only because a remaster reprints the original roster is not treated as a new appearance.</li>
      <li>The Master Chief Collection's February 2025 update credited only community Reclaimer volunteers, no developers; those names are shown in the "TMCC (Post-2018)" column in teal but are not counted toward any developer or vendor statistic.</li>
      <li>Contractor share is not comparable across eras: Bungie-era credits carry almost no vendor tags while 343-era credits are saturated with them, which is partly a real outsourcing shift and partly a change in crediting convention.</li>
    </ul>
  </div>
  <div class="source">Source: Halopedia, Halo Waypoint, IGDB, and MobyGames credit rolls.</div>
</div>
"""


def render_page(root, people_csv, credits_dir, exclude=frozenset(), style=""):
    a = analyse(root, people_csv, credits_dir, exclude)
    core = a["core"]
    multi = sum(1 for p in core if len(p["cols"]) >= 2)
    height = re.search(r'height="(\d+)"', a["svg"]).group(1)
    return PAGE.format(style=style, total=fmt(len(core)), multi=fmt(multi),
                       height=fmt(int(height)), svg=a["svg"], hero=hero_stats(a),
                       studios=studio_sections(a), cards=stat_cards(a))


def wrap_standalone(fragment: str, title: str = "Halo Credits",
                    description: str = "Every person credited across 25 "
                    "years of Halo, from Combat Evolved to Campaign "
                    "Evolved.") -> str:
    """The generated fragment is a <style> block plus body content, meant
    to sit inside another page's shell -- the brainstorming tool's preview
    frame it was authored in. Serving it on its own needs the document
    scaffold that shell was supplying: DOCTYPE, a real <head>, a charset
    declaration so accented names decode correctly, and a title, none of
    which the fragment itself carries.
    """
    bar = (
        '<div style="position:sticky;top:0;z-index:1;display:flex;'
        'justify-content:flex-end;gap:16px;padding:8px 16px;'
        'background:#0a0e14ee;backdrop-filter:blur(6px);'
        'border-bottom:1px solid #232a35;font-family:\'Segoe UI\',sans-serif;'
        'font-size:13px;">'
        '<a href="poster.html" style="color:#e8f4ff;text-decoration:none;'
        'border-bottom:1px solid #3a4454;">Browse the full poster</a>'
        '<a href="https://github.com/HiIAmMoot/HaloCredits" '
        'style="color:#8b93a3;text-decoration:none;border-bottom:1px solid '
        '#3a4454;">Source</a>'
        '</div>')
    return (f'<!doctype html>\n<html lang="en">\n<head>\n'
           f'<meta charset="utf-8">\n'
           f'<meta name="viewport" content="width=device-width, '
           f'initial-scale=1">\n'
           f'<title>{esc(title)}</title>\n'
           f'<meta name="description" content="{esc(description)}">\n'
           f'<style>html,body{{margin:0;padding:0;background:#0a0e14}}</style>\n'
           f'</head>\n<body>\n{bar}\n{fragment}\n</body>\n</html>\n')


def load_json(path):
    """Editorial copy kept as data, so wording can be revised without touching
    code or the v4 file the generator is regression-tested against. None means
    "leave whatever the template already has"."""
    path = Path(path)
    if not path.exists():
        return None
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def load_spotlights(path):
    """The hand-written spotlight cards, kept as data so the prose can be
    corrected without touching code -- or the v4 reference the generator is
    regression-tested against. None means "leave whatever the template has".
    """
    path = Path(path)
    if not path.exists():
        return None
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def render_from_template(template_html, root, people_csv, credits_dir,
                         exclude=frozenset(), group_by_shape=True,
                         spotlights=None, copy=None, include_publishers=True):
    """Produce the next revision of the page by substituting only the regions
    the dataset decides, leaving everything editorial byte-for-byte intact.

    A textual diff against the template therefore shows exactly what the new
    data changed and nothing else -- a refresh cannot quietly redesign the
    page or drop hand-written prose.
    """
    a = analyse(root, people_csv, credits_dir, exclude, group_by_shape,
                include_publishers)
    h = template_html

    def swap(text, start_marker, end_marker, new, after=0):
        i = text.index(start_marker, after)
        j = text.index(end_marker, i + len(start_marker))
        return text[:i] + new + text[j:], i + len(new)

    everyone = a["people"]
    multi = sum(1 for p in everyone if len(p["cols"]) >= 2)
    height = int(re.search(r'height="(\d+)"', a["svg"]).group(1))

    h, _ = swap(h, '<div class="sub">', "</div>",
                f'<div class="sub">{fmt(len(everyone))} people &middot; {fmt(multi)} '
                f"credited on more than one game.")
    h = _inject_role_css(h)
    h, _ = swap(h, '<div class="lg">', '<div class="hint">',
                grid_legend() + role_legend(a) + '\n      ')
    h, _ = swap(h, '<div class="hint">', "</div>",
                f'<div class="hint">canvas 2,700 x {fmt(height)}px &#183; '
                f"scroll sideways for the later games")

    # the grid itself
    old_svg = max(re.findall(r"<svg .*?</svg>", h, re.S), key=len)
    h = h.replace(old_svg, a["svg"])

    h, _ = swap(h, '<div class="hero-row">',
                '\n\n      <div class="section-label">Achievements',
                f'<div class="hero-row">{hero_stats(a)}</div>')

    zone_end = h.index("</div>", h.index('<div class="zonenote"')) + len("</div>")
    stats_lbl = h.index('\n\n      <div class="section-label">Stats for every game')
    h = h[:zone_end] + "\n      " + studio_sections(a) + h[stats_lbl:]

    h, _ = swap(h, '<div class="statgrid">', '\n\n      <div class="footnote"',
                '<div class="statgrid">\n' + stat_cards(a) + "\n      </div>")

    # the swatch key sits between that section's label and its cards, and is
    # generated so it can never drift from the colors the cards actually use
    lbl = h.index('section-label">Stats for every game')
    h, _ = swap(h, '<div class="lg">', '<div class="statgrid">',
                stats_legend() + "\n      ", lbl)

    if spotlights:
        cards = "".join(f'<div class="spotlight-card"><div class="name">{c["name"]}'
                        f'</div><div class="fact">{c["fact"]}</div></div>'
                        for c in spotlights)
        start = h.index('<div class="spotlight-card">')
        end = h.rindex("</div></div>", start,
                       h.index('section-label">External studios'))
        h = h[:start] + cards + h[end + len("</div></div>"):]

    if copy:
        if copy.get("zonenote"):
            i = h.index('<div class="zonenote"')
            h, _ = swap(h, ">", "</div>", f'>{copy["zonenote"]}', i)
        if copy.get("footnote"):
            items = "".join(f"\n          <li>{x}</li>" for x in copy["footnote"])
            h, _ = swap(h, "<ul>", "</ul>", f"<ul>{items}\n        ")
        if copy.get("source"):
            h, _ = swap(h, '<div class="source">', "</div>",
                        f'<div class="source">{copy["source"]}')
    return h


if __name__ == "__main__":
    root = Path(".")
    ref = Path(__file__).resolve().parent / "templates" / "final-grid-v4.html"
    page = render_from_template(
        ref.read_text(encoding="utf-8"), root, "data/people.csv", "data/credits",
        spotlights=load_json(root / "config" / "spotlights.json"),
        copy=load_json(root / "config" / "page-copy.json"))
    page = wrap_standalone(page)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("render/final-grid-v6.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print("wrote", out, len(page), "bytes")

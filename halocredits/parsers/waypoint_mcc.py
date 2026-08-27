"""Parser for Halo: The Master Chief Collection's Waypoint credits page.

Person names are not in the served HTML at all -- ``__NEXT_DATA__`` carries
only the i18n dictionary. The names are hardcoded in the page's JS chunk as
compiled React JSX (spec 5.3), so ``fetch_mcc`` freezes the page HTML and the
chunk together, separated by ``MARKER``.

Structure of the compiled bundle, outermost first::

    <release tier>   E=function(s){var e=s.id,...,n=r("credits.block-titles.november-2014-launch")
      <block>          K, blockTitle:r("credits.block.343-industries")
        <area>           z, areaTitle:r("credits.area.publishing")
          <p> <strong>{title}</strong><br/>Name<br/>Name<br/>Name </p>

Every ``r("...")`` argument is an i18n key resolved against the flattened
``credits.*`` namespace; a bare string literal in the same position is already
display text.
"""

import json
import re

from ..models import CreditRow, InclusionClass, ParseResult
from ..normalize import clean_name, is_non_person, map_category

MARKER = "/*__MCC_CHUNK__*/"

RE_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

# A JS string literal, either quoting style, as a non-capturing group.
#
# Single quotes are not a theoretical case: the 2014 tier credits exactly one
# person whose name contains straight double quotes -- 'Josh "Jash" Jensen' --
# and the minifier switched that one literal to single quotes. A
# double-quote-only scanner loses him and mis-frames every token after him in
# that paragraph. Double-quoted is listed first so an apostrophe inside an
# ordinary name ("Vance O'Neill", "Makiko O'Brien") is consumed as part of the
# surrounding double-quoted literal instead of being read as the start of one.
_STR = r"""(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')"""

# A release tier is one top-level React component whose body opens by reading
# its own block title:
#
#   E=function(s){var e=s.id,r=(0,t.$)("halo-mcc").t,n=r("credits.block-titles.november-2014-launch")
#
# The four tiers (February 2025 / October 2021 / September 2018 / November
# 2014) are four such components emitted back to back, so a tier's extent is
# exactly one component body. Nothing here depends on ordinal position or on
# an anchor id.
#
# `[^{}]*?` between the opening brace and the key is what distinguishes a tier
# component from the page-level nav component higher up in the same chunk,
# which also names all four block-title keys -- but does so inside object
# literals (`a={jumpToNavAnchor:e,jumpToNavText:s("credits.block-titles...")}`),
# so a brace always intervenes. It takes no parameter either, which the
# required `\([A-Za-z_$][\w$]*\)` rules out independently.
RELEASE_KEY_PREFIX = "credits.block-titles."

RE_TIER = re.compile(
    r"=\s*function\s*\([A-Za-z_$][\w$]*\)\s*\{[^{}]*?"
    r'"(credits\.block-titles\.[^"]+)"'
)

# Any top-level component assignment. Used only to bound the *last* tier, which
# is followed by the page's shared presentational components (block header,
# toggle-all control, chevron SVGs) rather than by another tier.
#
# Cross-checked against an independent method on the frozen file: a balanced
# brace scan of the 2014 component's own function body ends at 149959, and the
# next component assignment starts at 149972. The 13 characters between them
# are the minifier's glue (`,f=r(62990),`) and contain no credits, so the two
# bounds are equivalent here.
RE_COMPONENT = re.compile(r"[A-Za-z_$][\w$]*\s*=\s*function\s*\(")

RE_BLOCK_TITLE = re.compile(
    r"blockTitle:\s*(?:\w+\(\s*(" + _STR + r")\s*\)|(" + _STR + r"))"
)
RE_AREA_TITLE = re.compile(
    r"areaTitle:\s*(?:\w+\(\s*(" + _STR + r")\s*\)|(" + _STR + r"))"
)
RE_PARAGRAPH = re.compile(r'"p",\s*\{')

# The February 2025 tier does not use paragraphs at all. Its "Reclaimers" -- the
# community modding programme -- are two bare JS array literals of gamertags,
# assigned to short identifiers before the JSX return and rendered by a list
# component:
#
#     d=["AbleSir Thomas","AshamanND",...],o=["killzone649322","KINNZE",...]
#
# There is no role, no vendor and no <strong>: just names. Verified against the
# frozen bundle that this shape occurs in the February 2025 tier ONLY (2 arrays,
# 50 names) and zero times in the 2014, 2018 and 2021 tiers, so recognising it
# cannot disturb any existing release's row count.
RE_ROSTER = re.compile(
    r"\b[A-Za-z_$][\w$]*\s*=\s*\[\s*"
    + _STR
    + r"\s*(?:,\s*"
    + _STR
    + r"\s*)*\]"
)

# Tokens *inside* one <p> element. Scanning is confined to that paragraph's own
# balanced extent (see _paragraph_span), which is what keeps layout noise from
# ever being offered as a candidate name: the `"".concat(p().row," ")` class
# strings and `"data-cms-id":"46081"` attributes all live between paragraphs,
# not inside them.
RE_IN_PARAGRAPH = re.compile(
    r'(?P<strong>"strong",\s*\{children:\s*'
    r"(?:\w+\(\s*(?P<skey>" + _STR + r")\s*\)|(?P<slit>" + _STR + r")))"
    r'|(?P<span>"span",\s*\{[^{}]*?children:\s*(?P<spanlit>' + _STR + r"))"
    r"|(?P<call>\w+\(\s*(?P<calllit>" + _STR + r")\s*\))"
    r"|(?P<text>[,\[]\s*(?P<textlit>" + _STR + r"))"
)

_JS_ESCAPE = re.compile(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.S)
_JS_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}

# A trailing staffing-agency / vendor tag on an individual credit line, e.g.
# "Cade Myers (Yoh Services LLC)", "Daniel Grade ( Collabera )". Unlike Halo
# Infinite's page (see waypoint_infinite.RE_VENDOR) this pattern deliberately
# accepts *any* trailing parenthetical: an audit of every trailing
# parenthetical in the 2014 tier found 42 distinct values and all 42 are
# company names, including seven bare single words with no corporate suffix and
# no all-caps cue ("Experis", "ExeQuo", "Amaxra", "Akvelon", "Volt",
# "Teksystems", "Collabera"). Infinite's suffix-or-all-caps rule would leave
# those seven stuck inside name_raw. Nested parentheses are excluded so the
# pattern can never swallow part of a name.
RE_VENDOR = re.compile(r"\s*\(\s*([^()]{1,60}?)\s*\)\s*$")

# "Test By Experis" / "Test By Lionbridge Game Services" name the vendor after
# a lead-in; the studio is the remainder, not the whole heading.
RE_VENDOR_PREFIX = re.compile(r"(?i)^(?:test|art|audio|localization|additional \w+)\s+by\s+(.+)$")

# Blocks that name an internal 343 Industries / Microsoft function rather than
# an outside company. Any block *not* listed here is treated as an external
# vendor and its rows inherit the block title as `studio` -- the same deny-list
# shape as waypoint_modern.FUNCTIONAL_DEPARTMENTS, so a block added by a future
# deploy defaults to being attributed rather than silently unattributed.
#
# Membership was decided by reading each block's contents in the frozen file,
# not from the name alone:
#   - "343 Industries" is the developer itself; blank studio means first-party
#     (spec section 4). Its areas are 343's own org chart (PUBLISHING,
#     FRANCHISE, COMMUNITY, DEVELOPMENT, TEST, ...).
#   - "Advanced Technology Group" and "Meld Development Team" are Microsoft
#     internal engineering groups: their rows carry *per-person* agency tags
#     ("(Experis)", "(Insight Global)", "(Aditi Technologies)"), which is the
#     shape of Microsoft staff plus contractors, not of an outside studio
#     credited as a unit.
#   - "Xbox Platform" and "Localization" are Microsoft publishing functions.
#   - "Halo Babies" and "SPECIAL THANKS" are not organisations at all.
# The four blocks deliberately left off -- United Front Games, Fireteam LTD,
# Test By Experis, Test By Lionbridge Game Services -- are genuine external
# vendors and are the only blocks that set `studio` from section context.
FUNCTIONAL_BLOCKS = {
    "343 industries",
    "advanced technology group",
    "meld development team",
    "xbox platform",
    "localization",
    "halo babies",
    "special thanks",
}

# inclusion_class is decided from an explicit set of block and area headings,
# never from a keyword sweep. That restraint is load-bearing here: the first
# and largest area of the 2014 tier is literally titled "PUBLISHING" -- 343's
# internal publishing group, which on MCC *is* the development leadership (Dan
# Ayoub, Greg Hermann, Paul Lipson, Jay Prochaska, Ben Cammarano). A
# waypoint_modern-style `\b(xbox|microsoft|localization|marketing)\b` sweep, or
# anything keying on the word "publishing", would reclassify 343's entire core
# team as publisher staff and drop them out of every core-participation
# statistic.
PUBLISHING_BLOCKS = {"xbox platform", "localization"}
PUBLISHING_AREAS = {"microsoft lca"}
SPECIAL_THANKS_HEADINGS = {"special thanks"}
BABIES_HEADINGS = {"halo babies", "production babies"}

# Headings kept OUT of the category fallback search. `category` is a normalized
# *department* (spec 4: "how did QA headcount change over 25 years"), and every
# heading listed here would answer that question with an organisational
# affiliation instead:
#
#   - "PUBLISHING" is 343's internal publishing group, and on MCC that group is
#     the development leadership. With the heading in the search, every row
#     there whose own title is unrecognised ("Senior SDE", "Creative Director")
#     was filed as category=Publishing purely because of the heading above it.
#   - "XBOX PLATFORM" and "LOCALIZATION" match category-map.csv's
#     `(...|localization|xbox|...)` Publishing rule on their heading text
#     alone. That put 24 Xbox Platform engineers ("SDE II", "Senior SDE",
#     "Principal SDE", "SDET", "Senior SDET") and 8 Localization staff
#     ("Linguistic Coordinators", "East Asia Content Reviewers") into
#     category=Publishing, which contradicted itself inside this one game:
#     "Senior SDE" came out Other under 343's block and Publishing under Xbox
#     Platform's, and "SDET" took three different categories depending only on
#     the heading above it.
#
# Publisher affiliation is already carried on its own axis --
# inclusion_class=publishing, 92 rows, set by PUBLISHING_BLOCKS /
# PUBLISHING_AREAS below -- so encoding it a second time in `category`, and
# only for the rows whose own title happens to be unrecognised, is inconsistent
# by construction. A row whose *own* role text says "Localization Project
# Managers" still resolves to Publishing, because that signal comes from the
# role, not from the heading.
#
# The line drawn here is affiliation vs. department, not "no heading may ever
# decide a category". Headings such as "TEST", "COMMUNITY" and "PROGRAMMING"
# stay in the search on purpose: those name a *discipline*, which is precisely
# what `category` records, and they are the only signal for rows whose own
# title carries none ("SDET", "Video Editors", "Channel PM").
MISLEADING_CATEGORY_HEADINGS = {"publishing", "xbox platform", "localization"}


def _js_unescape(literal: str) -> str:
    """Decode a JS string literal (quotes included) to its text value.

    The bundle really does use hex escapes for non-ASCII characters -- ``"Ethan
    Houl\\xe9"``, ``"Zuzanna G\\xf3rka"``, and a run of ``\\xa0`` non-breaking
    spaces. Returning the literal undecoded would put a backslash-x sequence
    straight into name_raw.
    """
    if len(literal) >= 2 and literal[0] == literal[-1] and literal[0] in "\"'":
        literal = literal[1:-1]

    def rep(m):
        g = m.group(1)
        if g.startswith("u{"):
            return chr(int(g[2:-1], 16))
        if g[0] == "u" and len(g) == 5:
            return chr(int(g[1:], 16))
        if g[0] == "x" and len(g) == 3:
            return chr(int(g[1:], 16))
        return _JS_SIMPLE.get(g, g)

    return _JS_ESCAPE.sub(rep, literal)


def extract_i18n(html: str) -> dict[str, str]:
    """Flatten the credits.* translation namespace out of __NEXT_DATA__.

    The store is NESTED, not flat --

        props.pageProps._nextI18Next.initialI18nStore
            .en["halo-mcc"]["credits"]["titles"]["executive-producer"] = "Executive Producer"

    while the JS bundle calls r("credits.titles.executive-producer") and
    r("credits.area.343-leadership-team"). So the nested dict must be flattened
    into dotted keys or every lookup misses and every role silently degrades to
    a slug. Searching for keys that already contain dots finds nothing.
    """
    m = RE_NEXT_DATA.search(html)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    out: dict[str, str] = {}

    def flatten(node, prefix):
        if isinstance(node, dict):
            for k, v in node.items():
                flatten(v, f"{prefix}.{k}")
        elif isinstance(node, str):
            out[prefix] = node

    def find_credits_namespace(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "credits" and isinstance(v, dict):
                    flatten(v, "credits")
                else:
                    find_credits_namespace(v)
        elif isinstance(node, list):
            for v in node:
                find_credits_namespace(v)

    find_credits_namespace(data)
    return out


def _resolve_text(i18n: dict[str, str], value: str) -> str:
    """Turn one already-unescaped JSX child into display text.

    A value that is a known i18n key resolves through the dictionary; an
    unknown ``credits.*`` key degrades to its de-slugified last segment, so the
    output shows a Title Cased guess rather than a raw dotted key; anything
    else is already display text.
    """
    if value in i18n:
        return clean_name(i18n[value])
    if value.startswith("credits."):
        return clean_name(value.rsplit(".", 1)[-1].replace("-", " ").title())
    return clean_name(value)


def _resolve(i18n: dict[str, str], literal: str | None) -> str:
    if literal is None:
        return ""
    return _resolve_text(i18n, _js_unescape(literal))


def _skip_string(text: str, i: int) -> int:
    """Index just past the string literal starting at text[i]."""
    quote = text[i]
    i += 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        i += 1
    return i


def _paragraph_span(text: str, brace: int, limit: int) -> tuple[int, int]:
    """Balanced extent of the props object of a ``"p",{...}`` element.

    ``brace`` is the index of the opening ``{``; returns (inner_start,
    inner_end). Brace counting skips string literals, so a ``{`` or ``}``
    inside a credited name can never unbalance the scan.

    ``limit`` is the end of the release tier this paragraph belongs to. A
    paragraph that failed to balance would otherwise run to the end of the
    file and pull names out of a *later release* -- the one outcome spec
    section 2 forbids -- so the scan is hard-stopped at the tier boundary
    rather than trusted to terminate on its own.
    """
    depth = 0
    i = brace
    while i < limit:
        c = text[i]
        if c in "\"'":
            i = _skip_string(text, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return brace + 1, i
        i += 1
    return brace + 1, limit


def find_release_tiers(chunk: str, i18n: dict[str, str]) -> list[tuple[str, int, int]]:
    """Return ``[(release title, start, end)]``, one entry per release tier."""
    starts = [(m.start(), _resolve_text(i18n, m.group(1))) for m in RE_TIER.finditer(chunk)]
    tiers = []
    for idx, (start, title) in enumerate(starts):
        if idx + 1 < len(starts):
            end = starts[idx + 1][0]
        else:
            nxt = RE_COMPONENT.search(chunk, start + 1)
            end = nxt.start() if nxt else len(chunk)
        tiers.append((title, start, end))
    return tiers


def _declares_releases(chunk: str, i18n: dict[str, str]) -> bool:
    """True if this document shows any sign that the page has release tiers.

    Two independent signals, so that renaming one of them is not enough to make
    the guard blind:

    * the chunk still calls a ``credits.block-titles.*`` key (8 occurrences on
      the frozen file -- four in the page nav, four in the tier components);
    * the page's own i18n dictionary declares more than one release title
      (the frozen store declares five, including an ``april-2021-launch`` that
      is not rendered).
    """
    if RELEASE_KEY_PREFIX in chunk:
        return True
    return len([k for k in i18n if k.startswith(RELEASE_KEY_PREFIX)]) > 1


def _vendor_from_heading(heading: str) -> str:
    m = RE_VENDOR_PREFIX.match(heading)
    return clean_name(m.group(1)) if m else heading


def _inclusion(block: str, area: str, role: str = "") -> InclusionClass:
    b, a, r = block.lower(), area.lower(), role.lower()
    if b in BABIES_HEADINGS or a in BABIES_HEADINGS:
        return InclusionClass.BABIES
    # `role` is checked too, not just the block/area headings: a per-line role
    # of "Special Thanks" (the same value already written to role_raw below)
    # can sit inside a block/area that isn't itself titled "Special Thanks" --
    # e.g. a person-level line under a broader department heading -- and was
    # silently counted as core crew until this was added.
    if b in SPECIAL_THANKS_HEADINGS or a in SPECIAL_THANKS_HEADINGS or r in SPECIAL_THANKS_HEADINGS:
        return InclusionClass.SPECIAL_THANKS
    if b in PUBLISHING_BLOCKS or a in PUBLISHING_AREAS:
        return InclusionClass.PUBLISHING
    return InclusionClass.CORE


def _iter_structure(chunk: str, start: int, end: int):
    """Yield ``(kind, payload, position)`` over one tier, in source order.

    ``kind`` is ``"block"``, ``"area"``, ``"paragraph"`` or ``"roster"``. A
    paragraph payload is the ``(inner_start, inner_end)`` extent of that
    ``<p>``'s props object; a roster payload is the array literal's own span.
    """
    events = []
    for m in RE_BLOCK_TITLE.finditer(chunk, start, end):
        events.append((m.start(), "block", m.group(1) or m.group(2)))
    for m in RE_AREA_TITLE.finditer(chunk, start, end):
        events.append((m.start(), "area", m.group(1) or m.group(2)))
    for m in RE_PARAGRAPH.finditer(chunk, start, end):
        events.append((m.start(), "paragraph", _paragraph_span(chunk, m.end() - 1, end)))
    for m in RE_ROSTER.finditer(chunk, start, end):
        events.append((m.start(), "roster", (m.start(), m.end())))
    events.sort(key=lambda e: e[0])
    for pos, kind, payload in events:
        yield kind, payload, pos


def parse(text, game_id, options, cats, nonp) -> ParseResult:
    result = ParseResult(game_id=game_id)
    html, marker, chunk = text.partition(MARKER)
    if not marker:
        # No frozen chunk separator: the caller handed us a bundle on its own.
        html, chunk = "", text
    offset = len(html) + len(marker)

    i18n = extract_i18n(html)
    wanted = clean_name(options.get("release", ""))

    tiers = find_release_tiers(chunk, i18n)
    if tiers:
        selected = [t for t in tiers if t[0].lower() == wanted.lower()]
        if not selected:
            raise ValueError(
                f"MCC release {options.get('release')!r} not present in this bundle; "
                f"available: {[t[0] for t in tiers]}"
            )
    elif _declares_releases(chunk, i18n):
        # RE_TIER matching nothing does NOT mean the bundle has no releases --
        # it means the *pattern* stopped matching. RE_TIER demands the exact
        # shape `=function(<ident>){<no braces>..."credits.block-titles...."`,
        # so a redeploy that destructures the parameter (`function({id})`),
        # reorders the `var` list, or puts any brace before the key makes it
        # match zero times. Falling through to "parse everything" there would
        # silently ingest all four releases at once -- thousands of phantom
        # 2014 participants, the single outcome spec section 2 forbids. So
        # whenever the document still shows evidence that releases exist,
        # failing to find them is a hard error, exactly like asking for a
        # release that is not there.
        raise ValueError(
            "MCC bundle declares release tiers but none could be located; "
            "refusing to parse, because parsing the whole chunk would mix "
            "every release into one game"
        )
    else:
        # No evidence of releases anywhere in the document: a focused test
        # fixture holding a bare fragment of bundle. Parsing all of it cannot
        # mix tiers, because there are none to mix.
        selected = [(wanted, 0, len(chunk))]

    order = 0
    for release, start, end in selected:
        block = area = ""
        # The page lays each area out in three horizontal columns, and a list
        # that outruns one column simply continues in the next WITHOUT
        # repeating its <strong> heading. Those continuation paragraphs carry
        # names and no title at all, so read alone they lose the only
        # statement of what the people did: MCC 2021's Experis block ends a
        # column on "Test Associates" and spills 23 more testers into the next
        # one, all of whom fell back to the area name "EXPERIS TEMPE".
        #
        # So the last title seen carries forward, and is dropped at every
        # block and area boundary -- the same scope that already bounds
        # `area` itself, which is what stops a heading reaching a list it
        # never belonged to.
        carried_role = ""
        for kind, payload, _pos in _iter_structure(chunk, start, end):
            if kind == "block":
                block = _resolve(i18n, payload)
                carried_role = ""
                # A new block ends the previous block's area context as well as
                # its studio context. Both are re-established by the block's own
                # first area heading, so nothing can leak across the boundary.
                area = ""
                continue
            if kind == "area":
                area = _resolve(i18n, payload)
                carried_role = ""
                continue

            if kind == "roster":
                # The arrays are declared before the JSX that renders them, so
                # the area heading naming the programme ("Reclaimers") has not
                # been seen yet. Look ahead within this tier for it rather than
                # inventing a label -- role_raw is meant to be the source's word.
                programme = area or block
                if not programme:
                    ahead = RE_AREA_TITLE.search(chunk, payload[1], end)
                    if ahead:
                        programme = _resolve(i18n, ahead.group(1) or ahead.group(2))
                order = _emit_roster(
                    result, chunk, payload[0], payload[1], offset,
                    game_id, release, programme, order, cats, nonp,
                )
                continue

            inner_start, inner_end = payload
            order, carried_role = _emit_paragraph(
                result, chunk, inner_start, inner_end, offset,
                game_id, release, block, area, order, i18n, cats, nonp,
                carried_role,
            )

    return result


def _emit_roster(result, chunk, start, end, offset, game_id, release,
                 programme, order, cats, nonp) -> int:
    """Emit one row per gamertag in a community roster array.

    These are volunteers, not staff: they carry no role, no vendor and no
    department, so ``role_raw`` records the programme that credited them and
    ``inclusion_class`` marks them COMMUNITY. Every one of them appears in
    exactly one game by construction, so counting them as core would inflate
    both newcomers and one-and-done departures -- the same distortion the
    English-only voice rule exists to prevent.
    """
    programme = programme or "Community"
    for m in re.finditer(_STR, chunk[start:end]):
        name = clean_name(_js_unescape(m.group(0)))
        ref = f"{release}/{programme}@{offset + start + m.start()}"
        if not name:
            continue
        if is_non_person(name, nonp):
            result.drop(name, "non-person")
            continue
        result.add(CreditRow(
            game_id=game_id,
            credit_order=order,
            name_raw=name,
            category=map_category(programme, cats),
            role_raw=programme,
            inclusion_class=InclusionClass.COMMUNITY,
            source_ref=ref,
        ))
        order += 1
    return order


def _emit_paragraph(result, chunk, inner_start, inner_end, offset, game_id,
                    release, block, area, order, i18n, cats, nonp,
                    carried_role="") -> tuple:
    """Emit every credited person in one ``<p>``.

    Returns ``(next credit_order, the last title seen)`` so a list continuing
    into the next layout column keeps the heading it was written under.
    """
    ref_base = f"{release}/{block}/{area}"
    role = carried_role
    names: list[tuple[str, int]] = []
    prose: list[tuple[str, int]] = []

    for m in RE_IN_PARAGRAPH.finditer(chunk, inner_start, inner_end):
        if m.group("strong") is not None:
            title = _resolve(i18n, m.group("skey") or m.group("slit"))
            # A paragraph can end with an empty <strong>{"\xa0"}</strong>
            # spacer; letting that blank the role would strip role_raw from
            # names credited under the real title in the same paragraph.
            if title:
                role = title
            continue
        if m.group("span") is not None:
            literal, at = m.group("spanlit"), m.start("spanlit")
        elif m.group("call") is not None:
            # A bare r("credits.x.y") child: display prose, never a name.
            prose.append((_resolve(i18n, m.group("calllit")),
                          offset + m.start("calllit")))
            continue
        else:
            literal, at = m.group("textlit"), m.start("textlit")

        value = clean_name(_js_unescape(literal))
        if value:
            names.append((value, offset + at))

    # Prose children are accounted for whether or not the same paragraph also
    # credits people. Handling them only in the no-names branch loses them
    # silently in the mixed case, which the 2014 tier really does contain: the
    # SPECIAL THANKS block opens one paragraph with the dedication
    # `r("credits.misc.all-my-love")` -- "All my love to Jane and Elsa for
    # their patience and love." -- and then lists thirteen names after it.
    has_prose = False
    for blob, at in prose:
        if not blob:
            continue
        has_prose = True
        if is_non_person(blob, nonp):
            result.drop(blob, "non-person")
        else:
            # Prose that is neither a person nor a recognised non-person
            # pattern -- the FreeType library's copyright notice and the
            # dedication above. config/non-person-patterns.txt covers neither,
            # so they are logged as unparsed rather than silently swallowed.
            result.fail(blob, f"{ref_base}@{at}")

    if not names:
        if role and not has_prose:
            # <p><strong>DESIGN</strong></p> with no <br> and no names: a
            # sub-heading inside one layout column. It is *not* promoted to
            # role context for the paragraphs that follow -- its visual scope
            # is one column of a three-column grid, which the compiled JSX
            # gives no reliable way to bound, and every paragraph under it
            # already carries its own specific <strong> title anyway.
            result.drop(role, "section-heading")
        elif not has_prose:
            result.drop("(empty paragraph)", "empty-paragraph")
        return order, role

    for original, at in names:
        studio = ""
        value = original
        vm = RE_VENDOR.search(value)
        if vm:
            studio = clean_name(vm.group(1))
            value = clean_name(value[: vm.start()])
        if not value:
            result.drop(original, "vendor-tag-without-name")
            continue
        if is_non_person(value, nonp):
            result.drop(value, "non-person")
            continue

        # A per-person agency tag names the placement agency precisely and
        # therefore wins over the section heading, matching waypoint_modern and
        # waypoint_infinite. Section context only fills in when there is no tag.
        if not studio and block.lower() not in FUNCTIONAL_BLOCKS:
            studio = _vendor_from_heading(block)

        role_raw = role or area or block
        # The role is searched on its own first; the surrounding headings are
        # consulted only when the role itself resolves to nothing, and a
        # heading whose text is a known category false positive is left out of
        # that fallback entirely (see MISLEADING_CATEGORY_HEADINGS).
        category = map_category(role_raw, cats)
        if category == "Other":
            context = " ".join(
                h for h in (role_raw, area, block)
                if h and h.lower() not in MISLEADING_CATEGORY_HEADINGS
            )
            category = map_category(context, cats)

        result.add(CreditRow(
            game_id=game_id,
            credit_order=order,
            name_raw=value,
            category=category,
            role_raw=role_raw,
            studio=studio,
            inclusion_class=_inclusion(block, area, role),
            source_ref=f"{ref_base}@{at}",
        ))
        order += 1

    return order, role

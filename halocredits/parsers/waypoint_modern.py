import re

from bs4 import BeautifulSoup

from ..models import CreditRow, InclusionClass, ParseResult
from ..normalize import clean_name, is_non_person, map_category

# Sections named after an earlier Halo game are reprinted credits, not this
# game's workforce (spec section 6).
LEGACY_SECTIONS = [
    re.compile(r"(?i)^halo:?\s*combat evolved$"),
    re.compile(r"(?i)^halo\s*[2-5]$"),
    re.compile(r"(?i)^halo:?\s*reach$"),
    re.compile(r"(?i)^halo\s*3:?\s*odst$"),
    re.compile(r"(?i)^halo infinite$"),
]

BABIES = re.compile(r"(?i)(production babies|halo babies)")
SPECIAL_THANKS = re.compile(r"(?i)special thanks")
PUBLISHING = re.compile(r"(?i)^(xbox|playstation|microsoft|marketing|public relations)$")

# Spec 6.2's English-only voice rule is series-wide, not a Halo 5/IGDB
# special case -- Task 8 implemented it there, this page needs the same
# guard. `Keywords Studios / Voice Actors` is a 131-row block of
# localization-dub performers, every single one titled the literal
# "Additional Localized Voices" (verified against the raw file: sibling
# h3 groups under the same Keywords Studios vendor department --
# Keywords Studios Italy/Germany/Spain/Tokyo/Mexico, Musai Co. LTD.,
# Jinglebell S.R.L., Parallel Soundworks -- are the *staff* who ran those
# dubs, not the block being filtered here). Left in, each of the 131
# would read as a person who appears in exactly one Halo game, fabricating
# "newcomer" and "one-and-done" statistics -- the same failure mode the
# legacy-section tagging exists to prevent, just via language instead of
# via decade.
NON_ENGLISH_VOICE_SECTIONS = {
    ("Keywords Studios", "Voice Actors"),
}

# Sections that genuinely hold performers whose *title* names the specific
# character they portray. Deliberately an explicit allowlist rather than a
# "contains 'voice'" substring match: a full-file audit found the naive
# substring match also firing on `Arrival / Voice Over & Dialogue` (14 rows
# of dialogue editors and recording engineers -- job titles, not
# characters), `Talent & Performance / I Hear You Productions` (a casting
# director), and `Talent & Performance / ARU Recording Studio` (a dialogue
# recordist), forcing all of them to category=Voice with a fake
# `character` value and deflating Audio/Engineering in the process.
#
# `Talent & Performance / Performance` (3 motion-capture performers) is
# genuine cast too, but its title is the role descriptor "Performance
# Capture" for all three rows, not a named character -- it is deliberately
# left out of this set so `character` stays blank there. `category` still
# resolves to Voice for that group on its own, via category-map.csv's
# existing "performance capture" pattern -- see the map_category call
# below.
VOICE_CHARACTER_SECTIONS = {
    ("Talent & Performance", "Voice Talent"),
    ("Halo: Combat Evolved", "Voice Talent"),  # legacy CE cast, reprinted
}

# Departments (h2) that describe an internal Halo Studios / Xbox function
# rather than a named third-party company. Any h2 *not* in this set is a
# vendor department, and its rows inherit the department name itself as
# `studio` (spec 5.3's MCC-style section-context inheritance) -- a
# per-entry `credits_entry_agency__*` span, where present, still wins,
# since it names the specific sub-vendor more precisely than the
# department heading does (e.g. "Experis" vs. "Experis Game Solutions").
#
# "ENGINEERING" and "Engineering, Security & Operations" are two distinct,
# real h2 headings on the live page for the same internal discipline, so
# both are listed explicitly rather than matched by a case/substring
# heuristic.
#
# Five more were added after auditing the resulting studio distribution
# against the raw page and finding all five are internal 343/Xbox
# functions wearing names that read like companies, not actual companies:
#   - "Studios Quality" (38 rows): Halo Studios' own QA/data-engineering
#     org (titles: "Head of Quality", "Quality Director", "Director of
#     Data & AI").
#   - "Supplier Support" (11 rows): a generic umbrella heading whose own
#     h3 subgroups -- Agility Partners, Allegis Global Solutions, Aquent
#     LLC, Ascendion Inc, Kforce Inc, Randstad Digital -- are the real
#     staffing-agency names; none of its 11 rows carry a per-entry agency
#     span, so h2-based inheritance was assigning them the umbrella label
#     instead.
#   - "User Research" (4 rows): an internal research team ("Senior Xbox
#     Researcher", "Principal XR Program Manager Lead").
#   - "XGS Special Thanks" (17 rows): a second, differently-named Special
#     Thanks block (XGS = Xbox Game Studios), functionally identical to
#     the plain "Special Thanks" department already on this list.
#   - "XMS Digital Gaming" (17 rows): an internal Xbox digital storefront
#     org ("VP, Digital Gaming, 3P Platforms").
#
# By contrast, "Rare", "Ninja Theory", and "Turn 10 Studios" are
# deliberately *not* on this list: they are genuinely distinct Microsoft
# first-party sibling studios that contributed work, not a vendor and not
# a 343/Xbox internal function -- spec 8's two-way core/vendor split
# doesn't have a slot for "first-party sibling studio," but the raw
# `studio` values are preserved either way, so a later analysis pass can
# still split them out from true external vendors.
#
# "FX - Chamber" (6 rows) was also audited and left off this list on
# purpose: Chamber (fx-chamber.com) is a real, independently-branded
# real-time VFX outsourcing studio with a public client list (God of War
# Ragnarok, GTA5, Marvel's Spider-Man 2, Crackdown 3, Dauntless) -- a
# genuine external vendor, despite titles ("VFX Director", "Senior VFX
# Artist") that read like an in-house art team.
FUNCTIONAL_DEPARTMENTS = {
    "Art",
    "Audio",
    "Design",
    "ENGINEERING",
    "Engineering, Security & Operations",
    "Narrative",
    "Production",
    "Studio",
    "Talent & Performance",
    "Community Members",
    "Special Thanks",
    "Production Babies",
    "Xbox",
    "PlayStation",
    "Halo: Combat Evolved",
    "Studios Quality",
    "Supplier Support",
    "User Research",
    "XGS Special Thanks",
    "XMS Digital Gaming",
}


def _has_prefix(tag, prefix: str) -> bool:
    return any(c.startswith(prefix) for c in (tag.get("class") or []))


def _is_header(tag) -> bool:
    # On the live page a top-level department heading (h2, e.g. "Art",
    # "Halo: Combat Evolved") lives in its own `credits_section_header__*`
    # wrapper, one level above the `credits_group__*` block; the team
    # sub-heading (h3, e.g. "Character Art") lives in `credits_group_header__*`
    # inside that block. A single department can contain several groups, so
    # the h2 wrapper appears once per department while the h3 wrapper repeats.
    #
    # Both prefixes are checked here because the *fixture* below nests h2 and
    # h3 in two sibling `credits_group_header__*` divs (no separate section
    # wrapper) -- a plausible simplification, but verified against the raw
    # file's real markup and found to be a different shape: a grep of the
    # 536KB `halo-campaign-evolved.html` fixture found zero `<h2>` elements
    # inside any `credits_group_header__*` div (all 45 live in
    # `credits_section_header__*`), and all 210 `<h3>` elements live in
    # `credits_group_header__*`. Matching only `credits_group_header__*`
    # would leave `department` permanently empty on the real file, silently
    # disabling legacy-section detection (LEGACY_SECTIONS matches only
    # `department`) as well as the PUBLISHING check for department-level
    # sections like "Xbox" / "PlayStation" whose h3 sub-team names differ
    # from the department name. Checking both prefixes handles the fixture's
    # shape and the live page's shape with the same code.
    return _has_prefix(tag, "credits_group_header__") or _has_prefix(tag, "credits_section_header__")


# Volunteers credited alongside staff but never employed on the game. Campaign
# Evolved's "Community Members / Sentinels" are the same population as MCC's
# February 2025 "Reclaimers": they appear in exactly one game by construction,
# so leaving them as CORE inflates both newcomers and one-and-done departures.
# Spec section 6 had no bucket for them until InclusionClass.COMMUNITY existed.
COMMUNITY = re.compile(r"(?i)\b(community members|sentinels)\b")


def _inclusion(department: str, group: str) -> InclusionClass:
    if any(p.match(department) for p in LEGACY_SECTIONS):
        return InclusionClass.LEGACY
    for text in (department, group):
        if COMMUNITY.search(text):
            return InclusionClass.COMMUNITY
        if BABIES.search(text):
            return InclusionClass.BABIES
        if SPECIAL_THANKS.search(text):
            return InclusionClass.SPECIAL_THANKS
        if PUBLISHING.match(text):
            return InclusionClass.PUBLISHING
    return InclusionClass.CORE


def parse(text, game_id, options, cats, nonp) -> ParseResult:
    result = ParseResult(game_id=game_id)
    soup = BeautifulSoup(text, "lxml")
    department, group = "", ""
    order = 0

    for i, node in enumerate(soup.find_all("div")):
        if _is_header(node):
            h2 = node.find("h2")
            h3 = node.find("h3")
            if h2 is not None:
                department = clean_name(h2.get_text(" ", strip=True))
                group = ""
            if h3 is not None:
                group = clean_name(h3.get_text(" ", strip=True))
            continue

        # Middleware attributions (Unreal Engine, Wwise, SpeedTree, Speech
        # Graphics) sit in their own `credits_software_entry__*` divs, a
        # sibling structure to the person credits, not a person. Spec
        # section 6 requires excluding these *and* logging them -- silently
        # `continue`-ing past them (as the person-shaped branch below would
        # do, since "credits_software_entry__…".startswith("credits_entry__")
        # is False) would satisfy the first half and violate the second.
        if _has_prefix(node, "credits_software_entry__"):
            name_div = None
            for child in node.find_all("div"):
                if _has_prefix(child, "credits_software_name__"):
                    name_div = child
                    break
            label = clean_name((name_div or node).get_text(" ", strip=True))
            if label:
                result.drop(label, "middleware")
            continue

        if not _has_prefix(node, "credits_entry__"):
            continue

        spans = node.find_all("span", recursive=False)
        name = title = agency = ""
        for span in spans:
            classes = span.get("class") or []
            value = clean_name(span.get_text(" ", strip=True))
            if any(c.startswith("credits_entry_title__") for c in classes):
                title = value
            elif any(c.startswith("credits_entry_agency__") for c in classes):
                agency = value
            elif not classes and not name:
                name = value

        # `i` is this <div>'s own position among all <div> elements in the
        # document, in document order -- a real, independently-checkable
        # coordinate in the source (re-running `soup.find_all("div")[i]`
        # lands back on this exact node). `order` below only counts rows
        # this parser decided to emit and is reported back as credit_order;
        # reusing it here would make source_ref a disguised restatement of
        # credit_order rather than an actual source location.
        ref = f"{department}/{group}#{i}"
        if not name:
            text_repr = clean_name(node.get_text(" ", strip=True))
            if text_repr:
                result.fail(text_repr, ref)
            continue
        if is_non_person(name, nonp):
            result.drop(name, "non-person")
            continue
        if (department, group) in NON_ENGLISH_VOICE_SECTIONS:
            result.drop(name, f"non-english-voice:{department}/{group}")
            continue

        inclusion = _inclusion(department, group)
        role_raw = title or group
        is_character_section = (department, group) in VOICE_CHARACTER_SECTIONS
        character = title if is_character_section else ""
        if is_character_section:
            category = "Voice"
        else:
            category = map_category(f"{role_raw} {group} {department}", cats)
            if category == "Voice":
                # `group` text can satisfy category-map.csv's Voice pattern
                # on its own even for a section that was just excluded from
                # VOICE_CHARACTER_SECTIONS above -- Arrival's "Voice Over &
                # Dialogue" audio-post team is the one real case on this
                # page (title "Senior Dialogue Editor" / "Recording
                # Engineer", never mentioning voice work). A full-file diff
                # confirmed dropping `group` from the search unconditionally
                # is too blunt: ~150 *other*, correctly-categorized rows
                # (e.g. "Virtuos Chengdu / Environment Art", "Digic / DIGIC
                # Leadership") rely on `group` supplying the only category
                # signal when the title itself is generic. So `group` stays
                # in the search by default, and is only dropped -- falling
                # back to the person's own title/department -- in the
                # specific case where keeping it produced a Voice result
                # from a section this parser has already determined is not
                # a performer credit.
                category = map_category(f"{role_raw} {department}", cats)

        studio = agency or (department if department not in FUNCTIONAL_DEPARTMENTS else "")

        result.add(CreditRow(
            game_id=game_id,
            credit_order=order,
            name_raw=name,
            category=category,
            role_raw=role_raw,
            character=character,
            studio=studio,
            inclusion_class=inclusion,
            source_ref=ref,
        ))
        order += 1

    return result

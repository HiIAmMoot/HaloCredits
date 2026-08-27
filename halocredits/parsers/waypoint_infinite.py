import re

from bs4 import BeautifulSoup

from ..models import CreditRow, InclusionClass, ParseResult
from ..normalize import VENDOR_TAG, clean_name, is_non_person, map_category

# Inline staffing-agency / vendor tag on an individual row, e.g.
# "Jason Lackie (INSIGHT GLOBAL)". Hoisted into normalize.py so the
# halopedia parser -- which covers seven of the eleven games and had a
# strictly weaker pattern of its own -- shares this one instead of growing
# a third variant. See normalize.VENDOR_TAG for why the two alternatives
# are deliberately asymmetric.
RE_VENDOR = VENDOR_TAG

# A birth-death year range under "IN LOVING MEMORIES" (e.g. "1986 - 2020")
# -- structurally identical to a section heading (non-empty left cell,
# empty right cell) but not a name and not a new section either.
RE_YEAR_RANGE = re.compile(r"^\d{4}\s*[-–—]\s*\d{4}$")

# Department detection is keyed off the `xl69` cell class, not off matching
# heading text. An earlier version of this parser matched against a fixed
# set of 12 department name strings instead -- and broke on the one
# department name that is reprinted verbatim as a *nested* sub-heading:
# "343 INDUSTRIES" is both the real top-level department (tr 2926, class
# `xl69`) and, later, a plain sub-heading inside "SPECIAL THANKS" (tr 4118,
# class `xl76`, the same level as its sibling "HALO INFINITE TEAM"). Text
# matching treated the second occurrence as a fresh department change,
# silently losing Special Thanks context for the remaining 553 rows of that
# block (435 of which are real people, mislabelled `core`/`publishing`
# instead of `special-thanks`).
#
# Unlike the deeper `xl##` classes (verified elsewhere in this file to be
# semantically overloaded -- the same class marks a vendor company name in
# one place and a purely functional grouping in another), `xl69` itself is
# reliably a top-level-department-only marker: every `xl69` cell in the
# real file (13 total -- the 12 two-column department headings below plus
# the single-cell "MIDDLEWARE PARTNERS") is a genuine department boundary,
# with no double-duty use anywhere on the page. So department tracking
# reads the class directly; everything below that level still reads
# structure from cell content and emptiness, per the module docstring.
DEPARTMENT_CLASS = "xl69"

MEMORIAM_DEPARTMENT = re.compile(r"(?i)in loving memor")
BABIES = re.compile(r"(?i)(production babies|halo babies)")
SPECIAL_THANKS = re.compile(r"(?i)special thanks")
# "microsoft" is deliberately excluded here: on this page a bare
# "MICROSOFT" heading distinguishes in-house QA staff from the sibling
# "EXTERNAL TEAMS" heading a few rows later -- it is not a business
# function, and matching it would mislabel ~44 in-house QA engineers as
# Publishing.
PUBLISHING = re.compile(r"(?i)\b(xbox|marketing|public relations|publishing|localization)\b")

# Exactly the section headings under which the two columns invert to
# character | actor. Deliberately a narrow allowlist rather than a "contains
# voice/cast" substring test: a full-file audit found that broader match
# also firing on "CASTING" (-> the casting director's job title misread as
# a character, and Karen Sadow -- credited here via the same "I Hear You
# Productions" casting agency that tripped up the Campaign Evolved parser's
# own naive voice-substring match -- misread as an actor) and on
# "Voice Over Direction" / "Voice Over Editorial" (-> audio-post crew
# misread as cast, with the job title itself becoming a fake character
# name).
CHARACTER_SECTIONS = {
    "MAIN VOICE & PERFORMANCE CAST",
    "ADDITIONAL VOICES",
}

# Named external vendor / outsourcing studios that identify themselves via
# their own heading row rather than a per-person "(VENDOR)" tag -- the
# ~20 companies under "OUTSOURCE PARTNERS" (e.g. "Airship Images", listing
# a CEO, a COO, and a dozen artists with no individual agency tag at all)
# plus the five post-production sound houses subcontracted for the cast
# recording sessions, plus "TURN 10" (Turn 10 Studios, a genuine sibling
# Microsoft studio credited once under Special Thanks -- mirroring the
# Campaign Evolved parser's own Turn 10 carve-out). A per-row inline
# "(VENDOR)" tag, where present, still overrides this -- e.g. a handful of
# individual contractors under "The Coalition" carry their own staffing-
# agency tag distinct from the client studio they were placed at.
#
# Matched case-insensitively with any trailing " SPECIAL THANKS" suffix
# stripped first: four of these companies (SkyBox Labs, Sperasoft, The
# Coalition, Undead Labs) are credited *twice* -- once as their own
# heading, and again later as e.g. "SKYBOX LABS, INC. SPECIAL THANKS" for
# a second, smaller group of names -- and "Liquid Development LLC" is
# reprinted in a different case ("LIQUID DEVELOPMENT LLC") the second time.
# Both variants must resolve to the same studio.
VENDOR_HEADINGS = {
    "Airship Images", "Atomhawk", "Axis Studios", "Certain Affinity, Inc.",
    "CounterPunch a Virtuos Studio", "Lakshya Digital Pvt Ltd",
    "Liquid Development LLC", "Mandali Games", "Mindwalk", "Nuare Studios",
    "OF3D", "Pixel Mafia", "Pixel Smash Ltd", "Red Hot CG", "Room 8 Studios",
    "SkyBox Labs, Inc.", "Speech Graphics", "Sperasoft, Inc.",
    "Sprung Studios, Ltd.", "The Coalition", "Undead Labs",
    "SWEET JUSTICE", "KPOW AUDIO", "WARNER BROTHERS", "WABI SABI",
    "SKYWALKER SOUND", "TURN 10",
}

_SPECIAL_THANKS_SUFFIX = re.compile(r"\s+SPECIAL THANKS$", re.IGNORECASE)


def _vendor_key(text: str) -> str:
    return _SPECIAL_THANKS_SUFFIX.sub("", text).strip().upper()


_VENDOR_BY_KEY = {_vendor_key(v): v for v in VENDOR_HEADINGS}

# `studio_ctx` (the vendor a blank left cell inherits) must clear at the
# end of a vendor's own block, not just at the next department change --
# otherwise it leaks onto unrelated rows nested at the same or a shallower
# level as sibling headings. Two real, measured leaks: "SKYWALKER SOUND"
# (a genuine vendor, 3 rows) is immediately followed by three nested
# job-title headings (Foley Artist, Foley Mixer, Additional Sound Design --
# each correctly still "Skywalker Sound" rows) and *then* by "MUSIC", a
# sibling of "AUDIO" one level up -- without a level check, "MUSIC"'s own
# rows (55 of them, including composer Gareth Coker) kept inheriting
# "Skywalker Sound". Likewise "Liquid Development LLC" (9 rows) is followed
# by "AMD" and "TEAM XBOX", two unrelated sibling headings at the same
# level, which leaked the same vendor onto 15 more rows.
#
# A small, verified rank table over the four classes that actually appear
# on heading rows in the vendor-bearing parts of the file (`xl69` > `xl76`
# > `xl73` > `xl66`, confirmed by tracing every heading between each
# vendor heading and the next one at or above its own level) lets
# `studio_ctx` persist through anything *deeper* than the heading that set
# it -- e.g. "Airship Images" (xl76) followed by its own nested "CHARACTER
# ART" (xl73) team and "CEO" job title correctly keeps inheriting
# "Airship Images" -- while clearing on anything at the same level or
# shallower. Any class not in this table (role-only headings occasionally
# written in the plain data-row class, e.g. "SUPPORT & SAFETY MANAGEMENT")
# defaults to the deepest rank, since every such case observed in the file
# is a job-title heading, never a department or vendor boundary.
_HEADING_RANK = {"xl69": 0, "xl76": 1, "xl73": 2, "xl66": 3}
_DEFAULT_RANK = 3


def _heading_rank(classes) -> int:
    for cls in classes:
        if cls in _HEADING_RANK:
            return _HEADING_RANK[cls]
    return _DEFAULT_RANK


# The handful of single-<td> lines that are recognized boilerplate rather
# than a name|role pair, verified against every one of the 10 non-empty
# single-cell rows in the real file. Any single-cell text that is neither
# this heading, nor matched by the shared non-person patterns, nor seen
# while inside "IN LOVING MEMORIES", falls through to result.fail() --
# which on the real file is exactly the five middleware/copyright lines
# that don't match any existing non-person pattern (Wwise, two Granny
# Animation lines, Dolby, SpeedTree).
MIDDLEWARE_HEADING = "MIDDLEWARE PARTNERS"


def _inclusion(department: str, heading: str) -> InclusionClass:
    for text in (department, heading):
        if BABIES.search(text):
            return InclusionClass.BABIES
        if SPECIAL_THANKS.search(text):
            return InclusionClass.SPECIAL_THANKS
        if PUBLISHING.search(text):
            return InclusionClass.PUBLISHING
    return InclusionClass.CORE


def parse(text, game_id, options, cats, nonp) -> ParseResult:
    """Parse Halo Infinite's Waypoint credits page: a pasted Excel table.

    The page is Excel's HTML export -- a flat two-column <table> with
    `xl##` style classes. One of them, `xl69`, is a reliable, exhaustively
    verified marker for a top-level department heading and nothing else
    (see DEPARTMENT_CLASS) and is used directly for department tracking.
    Every deeper class is semantically overloaded -- the same class marks a
    vendor company name in one place and a purely functional grouping in
    another (`xl76` alone covers both "Airship Images", a vendor, and
    "MICROSOFT", an internal-staff label) -- so structure below the
    department level is still read from cell content and emptiness, not
    from the class, with one narrow exception: a small rank table over the
    four classes that actually appear on heading rows in the vendor-bearing
    parts of the page is used only to decide how far a vendor heading's
    `studio` inheritance reaches (see `_HEADING_RANK`).

    - A row with a non-empty left cell and an empty right cell is a
      section heading, at whichever level it happens to sit (department,
      vendor company, team, or job-title-as-heading).
    - A row with a non-empty right cell is data. Under most sections the
      columns are role | name; under the two real cast-roster sections
      (CHARACTER_SECTIONS) they invert to character | actor.
    - A blank left cell on a data row does not mean "no role" -- it means
      "same role as the row(s) above", a pattern used far more heavily
      than a single continuation row (see ROLE_CONTINUATION tests): a
      whole job-title group is frequently written as one role-bearing row
      followed by many blank-left rows, or as a role-only heading row
      followed immediately by an all-blank-left list.
    """
    result = ParseResult(game_id=game_id)
    soup = BeautifulSoup(text, "lxml")

    department = ""
    heading = ""
    last_role = ""
    studio_ctx = ""
    studio_rank = _HEADING_RANK[DEPARTMENT_CLASS]
    order = 0

    for i, tr in enumerate(soup.find_all("tr")):
        cells = tr.find_all("td")

        if len(cells) == 1:
            label = clean_name(cells[0].get_text(" ", strip=True))
            if not label:
                continue
            if label == MIDDLEWARE_HEADING:
                continue
            if MEMORIAM_DEPARTMENT.search(department):
                result.drop(label, "in-memoriam-tribute")
                continue
            if is_non_person(label, nonp):
                result.drop(label, "non-person")
                continue
            result.fail(label, f"{department}/{heading}#{i}")
            continue

        if len(cells) < 2:
            continue

        left = clean_name(cells[0].get_text(" ", strip=True))
        right = clean_name(cells[1].get_text(" ", strip=True))

        if not left and not right:
            continue

        if left and not right:
            # "IN LOVING MEMORIES" reuses the section-heading shape for a
            # real honoree's name (kept as a row -- mirrors the IGDB
            # parser's precedent of keeping a named "In Memory" honoree
            # rather than dropping them), for one honoree, a birth-death
            # year range (not a name, dropped), and -- for one honoree
            # only -- a full tribute paragraph in *two* languages that is
            # a two-<td> row with an empty right cell (the exact same
            # shape as a name), unlike the other honoree's tribute
            # paragraph which is a genuine single-<td> rowspan cell caught
            # by the `len(cells) == 1` branch above. A prose tribute is
            # unmistakably not name-shaped: multiple sentences, well over
            # 60 characters, versus "Jens Hauch" / "Caio Cesar Nunes
            # Oliveira" at under 30.
            if MEMORIAM_DEPARTMENT.search(department):
                if RE_YEAR_RANGE.match(left):
                    result.drop(left, "memoriam-date-range")
                elif len(left) > 60 or "." in left:
                    result.drop(left, "in-memoriam-tribute")
                elif is_non_person(left, nonp):
                    result.drop(left, "non-person")
                else:
                    result.add(CreditRow(
                        game_id=game_id,
                        credit_order=order,
                        name_raw=left,
                        category=map_category(department, cats),
                        role_raw=department,
                        inclusion_class=InclusionClass.CORE,
                        source_ref=f"{department}/{heading}#{i}",
                    ))
                    order += 1
                continue

            heading = left
            last_role = left
            classes = cells[0].get("class") or []

            if DEPARTMENT_CLASS in classes:
                department = left

            vendor = _VENDOR_BY_KEY.get(_vendor_key(left))
            rank = _heading_rank(classes)
            if vendor:
                # A new vendor heading always takes over, regardless of its
                # rank relative to whatever set studio_ctx before it (e.g.
                # one vendor's heading directly following another's last
                # row).
                studio_ctx = vendor
                studio_rank = rank
            elif rank <= studio_rank:
                # Same level or shallower than whatever last set
                # studio_ctx -- a sibling heading, not something nested
                # under the vendor's own block, so the vendor's studio
                # stops applying here. (A department heading is always
                # rank 0, the shallowest, so this also covers the
                # department-change case without a separate check.)
                studio_ctx = ""
                studio_rank = rank
            # else: strictly deeper than the heading that set studio_ctx --
            # still nested under the same vendor's block (e.g. a team or
            # job-title heading within it) -- leave studio_ctx and
            # studio_rank unchanged so a chain of such nested headings all
            # measure against the vendor's own original level, not the
            # most recent one.
            continue

        if not right:
            continue

        in_voice = heading in CHARACTER_SECTIONS

        if in_voice:
            name = right
            character = left
            role = "Voice Actor"
            category = "Voice"
            m = RE_VENDOR.search(name)
            studio = clean_name(m.group(1)) if m else ""
            if m:
                name = clean_name(name[: m.start()])
        else:
            name = right
            character = ""
            role = left or last_role
            m = RE_VENDOR.search(name)
            studio = clean_name(m.group(1)) if m else ""
            if m:
                name = clean_name(name[: m.start()])
            if not studio:
                studio = studio_ctx
            # `department` is deliberately kept OUT of the primary search
            # string and only consulted as a fallback when role+heading
            # resolve to nothing (`Other`): the top-level department name
            # "PERFORMANCE CAST & CREW" itself contains the literal
            # substring "performance cast", which satisfies
            # category-map.csv's Voice pattern unconditionally. Included
            # in every row's search, that turned composers, foley artists,
            # sound mixers, and the casting director all into
            # category=Voice regardless of their actual job, simply for
            # being organizationally grouped under a heading that happens
            # to contain the word "cast".
            #
            # But dropping `department` outright also loses real signal:
            # e.g. "PROGRAM DIRECTORS" under "STUDIOS QUALITY TEAM" has no
            # QA/test keyword in its own role text, only in the department
            # name, and fell all the way to `Other` without it. So it's
            # used as a second pass, only when the specific signal came up
            # empty, and only outside "PERFORMANCE CAST & CREW" -- the one
            # department whose own name is the false-positive source above,
            # so it must never be allowed back in even as a fallback.
            category = map_category(f"{role} {heading}", cats)
            if category == "Other" and department != "PERFORMANCE CAST & CREW":
                category = map_category(department, cats)

        if left:
            last_role = left

        if not name:
            result.fail(right, f"{department}/{heading}#{i}")
            continue
        if is_non_person(name, nonp):
            result.drop(name, "non-person")
            continue

        result.add(CreditRow(
            game_id=game_id,
            credit_order=order,
            name_raw=name,
            category=category,
            role_raw=role,
            character=character,
            studio=studio,
            inclusion_class=_inclusion(department, heading),
            source_ref=f"{department}/{heading}#{i}",
        ))
        order += 1

    return result

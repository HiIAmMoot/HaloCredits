"""What a person actually did, resolved to one role class per game.

The grid draws one marker per person per game, so it needs exactly one role
for that pair. Three facts make this tractable:

  * 99% of person-game pairs carry a single credit category already (12,762
    of 12,892). Only 130 hold more than one, so the tiebreak below decides a
    rounding error, not the picture.
  * The corpus already has a 13-value `category`. Thirteen hues at a 2.6px
    marker is past what the eye separates, so they group to nine -- eight
    development crafts plus live and support -- with neutrals for the
    classes that are not work at all.
  * 1,904 rows land in `Other`, and almost none of them describe a
    discipline. They hold a company ("Volt", "EXPERIS TEMPE") or a group
    label ("DCC TEAM MEMBERS", "DEVELOPERS"). Colouring those as a made-up
    discipline would be a lie about the source.

FALLBACKS, most specific first, when the role text names no craft.

  0. A DEPARTMENT TAG BESIDE THE NAME. Several rolls annotate the person
     rather than the role: "Aaron Nicholls (Engineering)", "Seth Gibson
     (Tech Art)", "Alicia Brattin (Business)". config/name-fixes.csv strips
     those brackets so the name resolves to one person, and used to discard
     the tag with them. It is recovered into data/name-role-tags.csv and
     counts as STATED, because the source said it about that individual.
     Most bracketed text in the raw rolls is a vendor rather than a
     department -- Aquent, Volt, Insight Global -- and that is the
     inline_vendor machinery's job, not this one.

  1. MOBYGAMES' EXPLICIT ROLE for the same person on the same game.
     MobyGames prints a role beside every name it lists, for every game it
     covers. The wiki rolls often do not -- they group bare names under a
     heading, or put a staffing agency where the job should be -- so where
     this row's own source is silent, that one usually is not. Indexed by
     tools/build_mobygames_roles.py; also counts as STATED, since a source
     does say it outright, though a different one from the row's own.

  2. THE HEADING the row sat under. A row whose role text reads only "Volt"
     still sat beneath something that named the work -- "Digic / MoCap",
     "343 INDUSTRIES / SUPPORT TECHS", "Lionbridge Games / French
     Translation Support". Waypoint references carry that path already;
     Halopedia's are line numbers and MobyGames' are row indices, so those
     are recovered from the frozen sources into data/source-headings.csv.
     Patterns live in config/role-headings.csv.
  3. THE STUDIO'S LINE OF WORK, via config/vendor-types.csv. Weaker, because
     it describes a company rather than a block of people, so it is tried
     only when the heading says nothing.

Reading what the source already wrote down is what makes this worth doing.
Studio typing alone left 1,566 person-games unspecified; the headings took
it to 1,154, the department tags to 1,067, and MobyGames' own role column to
965 -- from 13.0% of the corpus to 7.5%. MobyGames also moves credits from
inferred to stated rather than merely colouring more of them: inference fell
from 710 pairs to 587 while the classified total rose.

Inference is recorded, not hidden. Every call reports whether a class was
STATED by the credit or INFERRED from context, so the page can say which is
which and the proportion can be measured rather than assumed.

Nothing here guesses from a bare name. A row with no category, no heading
that names work and no typed studio stays `unspecified`, and the grid shows
that plainly.
"""
from __future__ import annotations

import csv
from pathlib import Path

# The eight disciplines, plus four neutrals that are not disciplines.
MANAGEMENT = "management"
PRODUCTION = "production"
ENGINEERING = "engineering"
ART = "art"
DESIGN = "design"
AUDIO = "audio"
WRITING = "writing"          # narrative and performance
QA = "qa"
# Player-facing and live-service work: the community command centre, player
# support and safety, esports, and Waypoint. Not a development craft, but a
# real and growing function -- Infinite alone credits 110 of them -- and
# folding it into any of the eight would misreport the shape of the team.
LIVE = "live"
PUBLISHING = "publishing"
COMMUNITY = "community"
THANKS = "thanks"
UNSPECIFIED = "unspecified"

DISCIPLINES = [MANAGEMENT, PRODUCTION, ENGINEERING, ART, DESIGN, AUDIO,
               WRITING, QA, LIVE]
NEUTRALS = [PUBLISHING, COMMUNITY, THANKS, UNSPECIFIED]
ALL_CLASSES = DISCIPLINES + NEUTRALS

# corpus category -> role class
CATEGORY_CLASS = {
    "Leadership": MANAGEMENT,
    "Studio/Business": MANAGEMENT,
    "Production": PRODUCTION,
    "Engineering": ENGINEERING,
    "Art": ART,
    "Design": DESIGN,
    "Audio": AUDIO,
    "Narrative": WRITING,
    "Voice": WRITING,
    "QA": QA,
    # "Publishing" is deliberately absent. config/category-map.csv routes
    # marketing, finance, legal and HR into that category, so mapping it here
    # made 343's own finance manager and HR lead read as the publisher's
    # staff -- and dragged a "SENIOR SDE" in with them. These rows fall
    # through to the role text and heading instead, where finance and HR
    # reach management and marketing reaches publishing on their own terms.
    "Special Thanks": THANKS,
    "Other": UNSPECIFIED,
    "": UNSPECIFIED,
}

# What a vendor was hired to do, when the row itself says nothing useful.
VENDOR_TYPE_CLASS = {
    "testing": QA,
    "cinematic-sound": AUDIO,
    "publishing": PUBLISHING,
    # `development` says the studio built part of the game, not which craft,
    # so it is deliberately not mapped. Guessing "engineering" there would
    # colour hundreds of outsourced artists as programmers.
}

# When a person holds several categories on one game, the most specific
# statement about their craft wins over the most generic. Management sits
# high because "Studio Head" is a stronger claim than a second art credit;
# unspecified sits last because it is the absence of a claim.
PRIORITY = [MANAGEMENT, WRITING, AUDIO, DESIGN, ENGINEERING, ART, PRODUCTION,
            QA, LIVE, PUBLISHING, COMMUNITY, THANKS, UNSPECIFIED]
_RANK = {c: i for i, c in enumerate(PRIORITY)}

# Standing on the project, where standing is all there is. A community
# volunteer and a credited baby have no craft to record, so these outrank
# everything.
STANDING_ALWAYS = {
    "community": COMMUNITY,
    "babies": THANKS,
}

# Standing that must NOT outrank a stated craft, because the rolls subdivide
# these blocks by department: Special Thanks sections carry their own "ART",
# "ENGINEERING" and "DESIGN" sub-headings, and publisher-side credits include
# localization testers whose craft is testing. Overriding those would discard
# what the credits actually say, so they only fill in silence.
STANDING_FALLBACK = {
    "publishing": PUBLISHING,
    "special-thanks": THANKS,
}

STATED, INFERRED = "stated", "inferred"


def load_heading_patterns(path: Path) -> list:
    """(compiled pattern, role class), tried in file order against a heading."""
    import re
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pattern = (row.get("pattern") or "").strip()
            cls = (row.get("role_class") or "").strip()
            if pattern and cls in ALL_CLASSES:
                out.append((re.compile(pattern), cls))
    return out


def load_heading_index(path: Path) -> dict:
    """(game_id, source_ref) -> heading, for sources whose refs omit it.

    Built by tools/build_heading_index.py from the frozen raw sources:
    Halopedia refs are line numbers and MobyGames refs are row indices, so
    neither says anything on its own, but both sit under a heading that
    does. Committed rather than re-derived, so classification stays a
    function of committed data.
    """
    path = Path(path)
    if not path.exists():
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[(row["game_id"], row["source_ref"])] = row["heading"]
    return out


def heading_of(source_ref: str, game_id: str = "", index: dict = None) -> str:
    """The credit block a row sat under.

    Waypoint refs carry the path outright -- "Digic/MoCap#1204",
    "343 INDUSTRIES/SUPPORT TECHS#88" -- so the heading is already in the
    data. Everything else is looked up in the index.
    """
    ref = (source_ref or "").strip()
    if not ref:
        return ""
    if index:
        found = index.get((game_id, ref)) or index.get((game_id, ref.split("#")[0]))
        if found:
            return found
    if ":" in ref:
        return ""
    head = ref.split("#", 1)[0]
    if not head or (head.startswith("L") and head[1:].isdigit()):
        return ""
    return head.replace("/", " ")


def load_name_tags(path: Path) -> dict:
    """name -> the department tag the credits printed beside it.

    Built by tools/build_name_tags.py from the tags config/name-fixes.csv
    strips off names. The strongest signal in the corpus, because the credit
    states it about the individual rather than about the block they sit in.
    """
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["name"]: r["tag"] for r in csv.DictReader(fh) if r.get("tag")}


def load_category_patterns(path: Path) -> list:
    """(compiled pattern, corpus category) from config/category-map.csv.

    The same rules the parser uses to turn a role string into a category,
    reused here to read role strings that arrive from another source.
    """
    import re
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("pattern") and row.get("category"):
                out.append((re.compile(row["pattern"]), row["category"]))
    return out


def load_mobygames_roles(path: Path) -> dict:
    """(game_id, name) -> the role text MobyGames prints for that credit.

    MobyGames states a role beside every name it lists. The wiki rolls often
    do not -- they group bare names under a heading, or put a staffing agency
    where the job should be -- so this fills in the work for people the
    primary source leaves silent about. Built by
    tools/build_mobygames_roles.py.
    """
    path = Path(path)
    if not path.exists():
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("roles"):
                out[(row["game_id"], row["name"])] = row["roles"]
    return out


def load_vendor_types(path: Path) -> dict[str, str]:
    """studio (lowercased) -> work type. Missing file means no inference."""
    path = Path(path)
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            studio = (row.get("studio") or "").strip().lower()
            kind = (row.get("type") or "").strip().lower()
            if studio and kind:
                out[studio] = kind
    return out


def row_class(category: str, studio: str, vendor_types: dict,
              source_ref: str = "", heading_patterns=(), game_id: str = "",
              heading_index: dict = None, name: str = "",
              name_tags: dict = None, mobygames_roles: dict = None,
              category_patterns=(), role_raw: str = "",
              inclusion: str = "") -> tuple[str, str]:
    """One credit row -> (role class, STATED or INFERRED).

    Order matters. What the credit says about the person wins; only when it
    says nothing does the row fall back to where it sat, and only then to
    what its studio was hired for. The heading is tried before the studio
    because it is the more specific statement: "Digic/MoCap" says what this
    block of people did, where "Digic is a development vendor" says only
    that the company built part of the game.
    """
    incl = (inclusion or "").strip()
    standing = STANDING_ALWAYS.get(incl)
    if standing:
        return standing, STATED

    cls = CATEGORY_CLASS.get((category or "").strip(), UNSPECIFIED)
    if cls is not UNSPECIFIED:
        return cls, STATED

    # The role text itself, read again with the wider rule set. config's
    # category-map is tuned for the shapes the parser meets most often and
    # misses others outright -- its engineering pattern has no "software",
    # so "Software Development Leads" fell through to Other. This is still
    # the credit's own words about the person, so it counts as stated.
    if role_raw:
        for pattern, rcls in heading_patterns:
            if pattern.search(role_raw):
                return rcls, STATED

    # a department printed beside the name -- "Seth Gibson (Tech Art)". The
    # credit said this about the person, so it counts as stated, not guessed.
    tag = (name_tags or {}).get((name or "").strip())
    if tag:
        for pattern, tcls in heading_patterns:
            if pattern.search(tag):
                return tcls, STATED

    # MobyGames prints an explicit role for every credit it carries. Where
    # this row's own source left the work unnamed, that one usually names it.
    moby = (mobygames_roles or {}).get((game_id, (name or "").strip()))
    if moby:
        for pattern, cat in category_patterns:
            if pattern.search(moby):
                mapped = CATEGORY_CLASS.get(cat, UNSPECIFIED)
                if mapped is not UNSPECIFIED:
                    return mapped, STATED
        for pattern, hcls in heading_patterns:
            if pattern.search(moby):
                return hcls, STATED

    heading = heading_of(source_ref, game_id, heading_index)
    if heading:
        for pattern, hcls in heading_patterns:
            if pattern.search(heading):
                return hcls, INFERRED

    kind = vendor_types.get((studio or "").strip().lower())
    inferred = VENDOR_TYPE_CLASS.get(kind or "")
    if inferred:
        return inferred, INFERRED

    fallback = STANDING_FALLBACK.get(incl)
    if fallback:
        return fallback, STATED
    return UNSPECIFIED, STATED


def resolve(rows, vendor_types: dict, heading_patterns=(), game_id: str = "",
            heading_index: dict = None, name: str = "",
            name_tags: dict = None, mobygames_roles: dict = None,
            category_patterns=()) -> tuple[str, str]:
    """Rows are (category, studio) or longer: (category, studio, source_ref,
    role_raw, inclusion)."""
    """Several rows for one person on one game -> their single role class.

    Rows are (category, studio) or (category, studio, source_ref). Returns
    the class and its provenance; provenance is STATED if any row that voted
    for the winning class stated it outright.
    """
    votes: dict[str, str] = {}
    for row in rows:
        category, studio = row[0], row[1]
        ref = row[2] if len(row) > 2 else ""
        role_raw = row[3] if len(row) > 3 else ""
        inclusion = row[4] if len(row) > 4 else ""
        cls, prov = row_class(category, studio, vendor_types, ref,
                              heading_patterns, game_id, heading_index,
                              name, name_tags, mobygames_roles,
                              category_patterns, role_raw, inclusion)
        if cls not in votes or prov == STATED:
            votes[cls] = prov
    if not votes:
        return UNSPECIFIED, STATED
    # a real discipline always beats "unspecified", however many rows say it
    real = {c: p for c, p in votes.items() if c != UNSPECIFIED}
    pool = real or votes
    best = min(pool, key=lambda c: _RANK.get(c, len(PRIORITY)))
    return best, pool[best]

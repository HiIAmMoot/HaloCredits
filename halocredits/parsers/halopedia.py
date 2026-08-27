import re

from ..models import CreditRow, InclusionClass, ParseResult
from ..normalize import (clean_name, is_non_person, map_category,
                         split_vendor_tag, vendor_tag_pattern)

# Matches a single non-nested {{...}} template. Applied repeatedly (see
# _strip_templates) so that nested templates ({{Ref/Note|...{{Ref/X|...}}}})
# resolve from the innermost pair outward, and so that templates whose
# opening/closing braces land on different source lines (e.g. a multi-line
# infobox) are removed too -- [^{}] matches newlines by default in Python's
# re module, so this is not limited to a single line. Each match is replaced
# with its own newline count (see _strip_templates), not with "", so that
# collapsing a multi-line template can never shift every subsequent line's
# 1-based number -- source_ref must keep pointing at the real file line.
RE_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
RE_BOLD_ROLE = re.compile(r"^'''(.+?)'''\s*:?\s*$")
# Sentinel `studio_level` for a vendor context set by a BOLD line rather than
# a ``===Heading===``. Bold lines carry no nesting depth of their own, so this
# must compare as deeper than any real heading level (2-5) -- that is what
# makes the very next ``===Heading===``, at any level, correctly end a
# bold-set vendor's scope via the existing `level <= studio_level` check.
STUDIO_LEVEL_BOLD = float("inf")
RE_HEADING = re.compile(r"^(={2,5})\s*(.+?)\s*\1\s*$")
RE_ITALIC = re.compile(r"^''(?!')(.+?)''$")
# A stage direction that Halopedia additionally wraps in a parenthetical
# aside, e.g. "(''Epilogue - Beholden'' plays )" -- RE_ITALIC alone requires
# the *entire* line to be the ''...'' span, so it misses this shape. Halo 2
# is the only fixture that uses it (six lines); left unrecognized, each one
# becomes a fake credited "person" whose name is the stage direction's own
# text -- one of them names a music track containing " - ", which is how
# this was found while auditing name_raw for dash-split leftovers.
RE_PAREN_ITALIC = re.compile(r"^\(.*''.*''.*\)$")
RE_BULLET = re.compile(r"^\*+\s*(.+)$")
RE_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
# Wiki namespace prefixes on a link target. Matched case-insensitively and
# tolerant of both the leading-colon form ([[:Category:X|Y]]) and a space
# after the colon ([[Wikipedia: Aisha Tyler|Aisha Tyler]]). An earlier
# lowercase-only literal strip missed every capitalised occurrence -- and
# capitalised is what the corpus actually uses (21 of the 23 namespaced
# links), so "Nika Futterman" was pinned to the canonical identity
# "Wikipedia:Nika Futterman". Those rows are disproportionately voice
# actors, i.e. exactly the population most likely to recur across games.
#
# Two lists, because the two kinds of namespace mean different things for
# identity. An ARTICLE namespace points at a page ABOUT the credited person
# on another wiki, so the target minus its prefix IS a usable canonical
# name. A NON-ARTICLE namespace points at a page that is not a person at
# all: [[:Category:Images by Ashley Wood|Ash Wood]] must not canonicalise
# "Ash Wood" to "Images by Ashley Wood" -- there is no canonical name to be
# had from a category listing, and a wrong one is worse than none.
#
# Both are closed lists rather than a generic ^[A-Za-z]+: strip, because
# halo-cea credits [[Halo: Original Soundtrack|Original Halo... Music]] and
# a generic rule would truncate that page title at its colon.
RE_NS_ARTICLE = re.compile(r"(?i)^\s*:?\s*(?:wikipedia|marathongame)\s*:\s*")
RE_NS_NON_ARTICLE = re.compile(r"(?i)^\s*:?\s*(?:category|file|image|media|template|help)\s*:\s*")
RE_INVERTED = re.compile(r"^(Writer|Editor|Print Artist|Producer|Designer)\s*:\s*(.+)$")
# A hyphen, en dash, or em dash with whitespace on *at least one* side. Some
# lines only space one side of the separator ("Crowd- The Bungie auxiliary
# players", "NOBLE SIX (MALE)- Phillip Anthony Rodriguez") -- requiring
# whitespace on both sides (the original " - " form) missed those and left
# the dash sitting in name_raw. An unspaced hyphen (no whitespace on either
# side) is never a candidate: that is what protects real surnames
# (Pettiford-Wates, Lentz-Pope) and in-universe designations (John-117),
# which is checked character-by-character in _split_dash_outside_links
# rather than expressed as a single regex, since a lookaround for "whitespace
# OR string edge" on a variable-width dash class is easy to get subtly wrong.
RE_DASH_CHAR = re.compile(r"[-–—]")

# A section whose current role heading is a cast/voice credit list, where a
# per-line dash separates a *character* from an *actor* rather than a role
# from a name. dash_style is set page-wide and gets this wrong for exactly
# these sections (see cast_dash_style in config/sources.csv) -- deliberately
# narrower than "cast|voice|talent": halo-4's "===Scanned Talent===" section
# also matches the word "talent" but is role-first shaped ("OTHER FACES -
# Toshiya Agata", a scan category, not a fictional character), so "talent"
# alone is excluded to avoid misclassifying it.
CAST_SECTION_RE = re.compile(r"(?i)\b(cast|voice)\b")

# A credit line that is really a roster: three or more comma-separated
# segments, every one shaped like a person's name. halo-cea L263 lists 35
# Saber Interactive staff on one line; emitted whole it is one absurd
# "person" and 34 real people never enter the dataset.
#
# The >=3 floor and the all-segments-must-match rule keep this off ordinary
# credits: "Wilson, Jr." has two segments and fails the shape test, and
# "Audio Lead, Sound Design & Original Music" fails on segment shape too.
RE_NAME_SHAPE = re.compile(r"^[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){1,3}$")

# A word that marks a segment as an ORGANIZATION rather than a person, even
# though it otherwise passes RE_NAME_SHAPE's 2-4-capitalized-word test.
# "Epic Games, Turtle Rock Studios, Bungie Studios" has three segments that
# all individually shape-match a person's name, so without this guard a
# Special Thanks line crediting three studios would be exploded into three
# fabricated people. Does not fire anywhere in the current corpus -- the
# roster split still runs exactly once, on halo-cea L263 -- but the roster
# split is the only change in this project that can *create* rows, so this
# latent fabrication risk is worth a cheap, narrow guard even though nothing
# in the frozen fixtures currently exercises it.
RE_ORG_WORD = re.compile(
    r"(?i)\b(Studios?|Games|Inc|LLC|Ltd|Limited|Interactive|Entertainment|"
    r"Software|Technologies|Productions|Media|Group)\b"
)

SPECIAL_THANKS = re.compile(r"(?i)special thanks")
PUBLISHING = re.compile(r"(?i)\b(xbox|playstation|microsoft|localization|marketing|public relations)\b")
BABIES = re.compile(r"(?i)\b(production babies|halo babies)\b")


def _strip_templates(text: str) -> str:
    """Remove {{...}} templates from the whole page, including nested and
    multi-line ones, without shifting any surviving line's number.

    A single regex pass can only remove non-nested templates, and can only
    remove templates whose opening/closing braces both land on lines that
    happen to be joined in one match attempt. Applying it once per line (as
    an earlier draft did) misses two real shapes in the Halo CE source: a
    multi-line ``{{Level infobox ... }}`` block, and a role heading with a
    ``{{Ref/Note|...{{Ref/X|...}}}}`` citation nested two levels deep. Running
    the substitution to a fixed point over the *whole* text resolves both:
    each pass removes whatever templates are currently innermost/non-nested,
    which peels a nested template from the inside out and collapses a
    multi-line template in one shot.

    Each match is replaced with the same number of newlines it contained,
    not with "". Deleting a multi-line template's interior newlines outright
    would shift the 1-based line number of every line after it -- silently
    and by a different amount at every subsequent template -- which corrupts
    ``source_ref`` (and, downstream, the ``L{n}`` in every unparsed/failed
    entry) without ever showing up as a test failure that points at the
    cause. Preserving the newline count keeps line numbers pinned to the
    original file no matter how many templates collapse before them.
    """
    prev = None
    while prev != text:
        prev = text
        text = RE_TEMPLATE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return text


def _has_level2_heading(text: str) -> bool:
    """True if the page uses top-level ``==Section==`` headings.

    Halopedia credit pages open with an intro paragraph and an infobox, then
    a ``==Credits==`` section, then unrelated sections (``==Trivia==``,
    ``==Notes==``, ``==Sources==``, a trailing ``[[Category:...]]`` tag).
    None of that surrounding material is a credit and must never be scanned
    for names. Bare test snippets passed straight into ``parse()`` don't have
    this page structure at all, so the gate below only engages when a
    level-2 heading is actually present -- otherwise every unit test would
    need to be wrapped in a fake ``==Credits==`` section to produce any rows.
    """
    for raw in text.splitlines():
        m = RE_HEADING.match(raw.strip())
        if m and len(m.group(1)) == 2:
            return True
    return False


def strip_links(text: str) -> tuple[str, str]:
    """Return (display_text, canonical_name).

    canonical_name is the wiki-link target when it differs from the displayed
    text, which is how Halopedia records the correct spelling of misprinted
    credits (e.g. [[Zach Russell|Zach Russel]]).
    """
    canonical = ""
    m = RE_LINK.search(text)
    if m:
        target = m.group(1)
        if RE_NS_NON_ARTICLE.match(target):
            target = ""
        canonical = clean_name(RE_NS_ARTICLE.sub("", target))
    display = RE_LINK.sub(lambda mm: mm.group(2) or mm.group(1), text)
    # Only the article namespaces are stripped from the display text. A
    # non-article prefix is left visible on purpose: an unpiped page-footer
    # tag like [[Category:Credits]] renders as the literal "Category:Credits"
    # and the non-person patterns need to be able to recognise it as such.
    display = clean_name(RE_NS_ARTICLE.sub("", display))
    if canonical == display:
        canonical = canonical if m and m.group(2) else ""
    return display, canonical


def _studio_headings(raw) -> dict[str, str]:
    """Normalize the per-game ``studio_headings`` option into a lookup.

    Accepts either a list of heading texts (the studio name is the heading
    itself) or a {heading: studio name} map, and keys it casefolded.

    This is an explicit, per-game map rather than "the heading at level N is
    a vendor", because that rule does not hold on the one page that needs it.
    halo-cea's organizations sit at level 3 (Saber Interactive, Certain
    Affinity Inc.) AND at level 4 (Pyramind Studios, Chanticleer, Skywalker
    Sound and the three Soundelux blocks under ===Audio===; Experis Manpower
    Group and Keywords International Ltd. under ===[[Microsoft Studios]]===),
    while ===Audio=== and ===Terminal Videos=== are level-3 headings that are
    functions, not companies. A level rule therefore either invents "Audio"
    and "Terminal Videos" as employers -- the exact fabrication that had to be
    unwound twice in the Waypoint parsers -- or drops 119 genuine vendor rows.
    An explicit list is the same remedy Task 9 landed on for the Waypoint
    modern parser's FUNCTIONAL_DEPARTMENTS, and it is auditable line by line
    against the wikitext.

    The map form exists because one vendor can head several blocks:
    Soundelux Design Music Group appears three times with a scope suffix, and
    collapsing those to one studio name is what keeps a "distinct studios"
    count honest.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {clean_name(k).casefold(): clean_name(v) for k, v in raw.items()}
    return {clean_name(k).casefold(): clean_name(k) for k in raw}


def _inclusion(role: str, effective_role: str = "") -> InclusionClass:
    if BABIES.search(role):
        return InclusionClass.BABIES
    if SPECIAL_THANKS.search(role):
        return InclusionClass.SPECIAL_THANKS
    if PUBLISHING.search(role):
        return InclusionClass.PUBLISHING
    # `role` is the enclosing section/heading context and is checked first,
    # unconditionally -- that is what keeps a "SPECIAL THANKS" section's own
    # sub-headings (e.g. Reach's "Design Lead", "Xbox") correctly classified
    # by the section they are IN rather than by the former-job-title text
    # `effective_role` displays for them. `effective_role` is consulted only
    # as a fallback, for the narrower case a per-line inverted "Role: Name"
    # credit (e.g. "Special Thanks: Marty O'Donnell") names its own role
    # more specifically than any heading above it ever did.
    if effective_role and effective_role != role:
        if BABIES.search(effective_role):
            return InclusionClass.BABIES
        if SPECIAL_THANKS.search(effective_role):
            return InclusionClass.SPECIAL_THANKS
        if PUBLISHING.search(effective_role):
            return InclusionClass.PUBLISHING
    return InclusionClass.CORE


def parse(text, game_id, options, cats, nonp) -> ParseResult:
    text = _strip_templates(text)
    result = ParseResult(game_id=game_id)
    name_style = options.get("name_style", "bullet")
    # Resolved once per page so an unknown mode fails loudly at the top
    # rather than silently stripping nothing on every row.
    inline_vendor = vendor_tag_pattern(options.get("inline_vendor", False))
    dash_style = options.get("dash_style")
    cast_dash_style = options.get("cast_dash_style")
    cast_bold_style = options.get("cast_bold_style")
    # {heading text -> studio name}. See _studio_headings for why this is an
    # explicit map and not a heading level or a heuristic.
    studio_headings = _studio_headings(options.get("studio_headings"))
    # Sections naming a later port or re-release. The project counts each
    # game from its FIRST release, so Halo 2's "Halo 2 for Windows Vista"
    # block -- which the page itself marks "appears in Halo 2 for Windows
    # Vista only" -- is not part of the 2004 credits. Skipped wholesale,
    # including every heading nested inside it, until a heading at the same
    # or a shallower level ends the block.
    # compared with wiki italic/bold markup stripped: the heading is written
    # "''Halo 2'' for Windows Vista", and config should name it as a reader
    # sees it.
    def _plain(s):
        return re.sub(r"'{2,}", "", clean_name(s)).casefold()

    exclude_sections = {_plain(s) for s in options.get("exclude_sections", [])}
    excluded_level = 0

    # Full pages carry a real ==Credits== section boundary; bare test
    # snippets do not. Only gate on it when the page actually has one.
    in_credits = not _has_level2_heading(text)

    role = ""
    # The nearest SECTION heading, tracked separately from `role` because a
    # bold line overwrites `role` and would otherwise destroy the "am I inside
    # a cast section?" signal for everything below it. halo-3 proves this is
    # not hypothetical: "'''Civilians'''" is a bold ROLE sitting in the middle
    # of "==== Artificial Intelligence Cast ====", between the linked
    # characters Brute Chieftain and Elites. Testing `role` made Elites,
    # Grunts and Marines stop registering as cast, which silently left 15 real
    # voice actors -- Nolan North, Adam Baldwin, Katee Sackhoff, Alan Tudyk
    # among them -- filed as category "Other" with no character.
    section_role = ""
    # The character a bold cast heading is currently naming, under
    # cast_bold_style. Cleared by the next section heading and by any bold
    # line that is a role rather than a character.
    character_ctx = ""
    order = 0
    # Vendor/organization currently in scope, and the heading level that set
    # it. Cleared by any non-studio heading at the same or a shallower level
    # -- a deeper heading is a department *inside* the organization and must
    # inherit it. This is the same clearing rule the Waypoint parsers had to
    # adopt after studio context leaked across sibling sections there
    # (SKYWALKER SOUND onto 55 unrelated MUSIC rows, Liquid Development onto
    # AMD engineers): a vendor block ends at its first non-vendor sibling.
    studio_ctx = ""
    studio_level = 0
    # The heading-level (studio_ctx, studio_level) pair in force just before a
    # bold vendor heading temporarily overrode it -- restored when a
    # following bold line ends that vendor's block, instead of clearing to
    # blank, so a vendor bold-heading nested inside a vendor SECTION heading
    # (none in the current fixtures, but the same containment CEA already
    # has at the section level) hands scope back to the section, not to "".
    saved_studio_ctx = ""
    saved_studio_level = 0

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        ref = f"L{lineno}"
        line = raw_line.strip()
        if not line:
            continue

        stripped = clean_name(line)
        if not stripped:
            continue

        m = RE_HEADING.match(stripped)
        if m:
            level = len(m.group(1))
            heading_text = clean_name(m.group(2))
            # Matched on the link-resolved text so config can name the
            # organization as a reader sees it ("Microsoft Studios"), not as
            # the wikitext spells it ("[[Microsoft Studios]]").
            heading_display, _ = strip_links(heading_text)
            if level == 2:
                # Top-level page section marker, not a role: only the
                # "Credits" section (case-insensitive) is in scope.
                in_credits = heading_text.lower() == "credits"
                studio_ctx, studio_level = "", 0
                section_role = ""
                character_ctx = ""
                excluded_level = 0
            elif in_credits:
                if excluded_level and level <= excluded_level:
                    excluded_level = 0          # the excluded block ends here
                if _plain(heading_display) in exclude_sections:
                    excluded_level = level
                    continue
                if excluded_level:
                    continue
                # A studio heading still sets `role`, exactly as before. It is
                # the only thing standing between the rows under it and a
                # stale role left over from the previous section -- and
                # `role` feeds inclusion_class, so not setting it would flip
                # whole vendor blocks to publishing.
                #
                # The LINK-RESOLVED text, not the wikitext. Neither heading
                # capture used to be de-linked at all, so ODST's
                # "=== [[Halo 3]] Contributors ===" put the literal string
                # "[[Halo 3]] Contributors" into role_raw on 19 rows.
                role = heading_display
                section_role = heading_display
                # A new section ends any cast character context. Without this
                # the last character of a Cast section would inherit onto the
                # first rows of whatever section follows it.
                character_ctx = ""
                studio = studio_headings.get(heading_display.casefold())
                if studio:
                    studio_ctx, studio_level = studio, level
                elif studio_ctx and level <= studio_level:
                    studio_ctx, studio_level = "", 0
            continue

        if excluded_level:
            # Inside an excluded port/re-release block. Recorded rather than
            # dropped silently, so the audit log still accounts for the line.
            result.drop(clean_name(stripped), "excluded-section")
            continue

        if not in_credits:
            # Page furniture outside the Credits section (intro prose, the
            # Trivia section's prose "bullet", a trailing [[Category:...]]
            # tag) is real content, not blank filler -- it must be logged,
            # not vanish past every one of rows/dropped/unparsed.
            result.drop(stripped, "outside-credits-section")
            continue

        m = RE_BOLD_ROLE.match(stripped)
        if m:
            # De-linked for the same reason as the heading above: halo-3
            # writes its whole cinematic cast as bold wiki-links, and the raw
            # markup was landing in role_raw verbatim.
            raw_bold = clean_name(m.group(1)).rstrip(":")
            bold, _ = strip_links(raw_bold)
            # Only a bold line that is ENTIRELY one wiki-link is read as a
            # character. That is the discriminator the source itself provides:
            # Halopedia links characters and does not link role labels, and
            # halo-3's "==== Artificial Intelligence Cast ====" proves the
            # distinction matters -- it mixes linked characters
            # ("'''[[Unggoy|Grunts]]'''") with bold lines that are plainly
            # roles ("'''Additional Voices'''", "'''Casting & Voice-Over
            # Production Services'''"). Treating every bold line in a cast
            # section as a character would file the casting director as a
            # voice actor playing a character called "Casting & Voice-Over
            # Production Services".
            if (cast_bold_style == "character"
                    and CAST_SECTION_RE.search(section_role)
                    and RE_LINK.fullmatch(raw_bold)):
                # halo-3 records its voice cast as a THIRD page shape, which
                # neither dash_style nor cast_dash_style reaches: the
                # character is a bold heading of its own,
                # "'''[[John-117|Master Chief]]'''", and the actor is the
                # plain line underneath. Read as a role that produced 29 rows
                # whose role_raw was a fictional character and whose category
                # was derived from that character's name -- "Master Chief"
                # contains "chief", so Steve Downes came out as Leadership.
                #
                # `role` deliberately keeps the section heading ("Cinematic
                # Cast") so that the next bold line still tests as being
                # inside a cast section, and so role_raw stays a job
                # description rather than becoming a character name.
                character_ctx = bold
                # Revert to the section heading. A bold ROLE seen earlier in
                # the same section ("'''Civilians'''") must not leak past a
                # character heading onto the rows below it -- that put
                # role_raw="Civilians" on nine actors whose character is
                # "Marines". Once a bold line is known to name a character,
                # the role in force is the section's, not the last bold one's.
                role = section_role
            else:
                role = bold
                character_ctx = ""
                # A bold sub-heading naming a vendor -- e.g. halo-3's
                # "'''damnfx'''" under "===Cinematic Animation Partners==="
                # -- is the same organization-heading shape the ===Heading===
                # branch above already resolves via studio_headings, just one
                # level deeper in the markup. Left unhandled, `role` above is
                # the only thing set: the vendor's own staff (damnfx, Excell
                # Data Corporation, Volt, Xversity, Rare, Filter, FilmOasis,
                # Sakson and Taylor, Zoic Studios all read this way on halo-3)
                # keep a blank studio and are silently counted as first-party.
                bold_studio = studio_headings.get(bold.casefold())
                if bold_studio:
                    if studio_level != STUDIO_LEVEL_BOLD:
                        saved_studio_ctx, saved_studio_level = studio_ctx, studio_level
                    studio_ctx, studio_level = bold_studio, STUDIO_LEVEL_BOLD
                elif studio_level == STUDIO_LEVEL_BOLD:
                    studio_ctx, studio_level = saved_studio_ctx, saved_studio_level
            continue

        if RE_ITALIC.match(stripped) or RE_PAREN_ITALIC.match(stripped):
            result.drop(stripped, "stage-direction")
            continue

        m = RE_BULLET.match(stripped)
        if m:
            body = m.group(1)
        elif name_style == "plain" and not stripped.startswith(("*", "=", "'''")):
            body = stripped
        elif is_non_person(stripped, nonp):
            # Non-bulleted attributions (e.g. the "Bink Video (c)..." line)
            # sit at the same indentation as real credits but are recognized
            # non-person boilerplate, not an unparseable shape.
            result.drop(stripped, "non-person")
            continue
        else:
            result.fail(stripped, ref)
            continue

        # dash_style is set for the whole page, but a Cast/Voice section's
        # per-line dash separates a character from an actor, not a role
        # from a name -- cast_dash_style overrides dash_style for exactly
        # those sections (see CAST_SECTION_RE), based on whatever heading
        # was most recently seen, the same way `role` itself already works.
        effective_dash_style = dash_style
        if cast_dash_style and CAST_SECTION_RE.search(role):
            effective_dash_style = cast_dash_style

        added = _emit(result, body, role, game_id, order, ref, cats, nonp, inline_vendor,
                       effective_dash_style, studio_ctx, character_ctx)
        order += added

    return result


def _split_outside_links(body: str) -> tuple[str, str] | None:
    """Split body at its first ':' that is not inside a [[...]] span.

    A colon can appear in a bulleted body for three different reasons: a
    link's own namespace prefix ([[wikipedia:Ed Fries|Ed Fries]]), a voice
    credit's name/character separator ([[Actor]]: [[Character]]), or an
    inverted role/name separator (Writer: Keith Cirillo). Only the latter
    two are a real split point -- the first is interior to a single link
    and must not be split on. Returns None if there's no such colon.
    """
    spans = [m.span() for m in RE_LINK.finditer(body)]
    for i, ch in enumerate(body):
        if ch == ":" and not any(start <= i < end for start, end in spans):
            return body[:i], body[i + 1:]
    return None


def _split_dash_outside_links(body: str) -> tuple[str, str] | None:
    """Split body at its first hyphen/en dash/em dash that is not inside a
    [[...]] span AND has whitespace on at least one side. Several Halopedia
    pages record each credit as a single "ROLE - Name", "Name - Role",
    "Character - Actor", or "Actor - Character" line instead of a shared
    role heading over a list of names; per-game config (dash_style /
    cast_dash_style) says which shape, if any, a page uses.

    Whitespace on *at least one* side, not both: some lines only space one
    side of the separator ("Crowd- The Bungie auxiliary players", "NOBLE SIX
    (MALE)- Phillip Anthony Rodriguez"). A dash with no whitespace on either
    side is never a candidate -- that's what protects real hyphenated
    surnames (Pettiford-Wates, Lentz-Pope) and in-universe designations
    (John-117) from being split. Both returned halves are stripped, since a
    one-sided-spaced match can leave the *other* side's boundary exactly on
    the dash (no space to trim there, but the far side may still have one
    from the source line's own formatting).

    Returns None if there is no such dash outside a link.
    """
    spans = [m.span() for m in RE_LINK.finditer(body)]
    for m in RE_DASH_CHAR.finditer(body):
        i = m.start()
        if any(start <= i < end for start, end in spans):
            continue
        before = body[i - 1] if i > 0 else ""
        after = body[i + 1] if i + 1 < len(body) else ""
        if before.isspace() or after.isspace():
            return body[:i].strip(), body[i + 1:].strip()
    return None


def _roster_split(text: str) -> list[str] | None:
    """Return the names if `text` is a comma-separated roster, else None."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) < 3:
        return None
    if not all(RE_NAME_SHAPE.match(p) for p in parts):
        return None
    # A segment that shape-matches a name can still be an organization
    # ("Turtle Rock Studios", "Bungie Studios") -- see RE_ORG_WORD above.
    if any(RE_ORG_WORD.search(p) for p in parts):
        return None
    return parts


def _emit(result, body, role, game_id, order, ref, cats, nonp, inline_vendor,
          dash_style=None, studio_ctx="", character_ctx="") -> int:
    """Emit one credit row (or, for a roster line, one row per name).

    Returns the number of rows added: 0, 1, or N for an N-person roster.
    """
    # Section context is the default; an inline "(VENDOR)" tag on the
    # line itself is more specific and overrides it below.
    studio = studio_ctx
    body, inline_studio = split_vendor_tag(body, inline_vendor)
    if inline_studio:
        studio = inline_studio

    # Checked on the whole, unsplit line before either split below is
    # attempted. Two shapes of non-person boilerplate would otherwise never
    # reach the final is_non_person check at the bottom of this function:
    # a line whose own colon (e.g. a quoted game title, "Halo 3: ODST")
    # confuses the colon-split below into failing outright, and a community
    # "Organization - URL" line that dash_style would otherwise slice into
    # a fake character/name pair (e.g. "7th Column" / "Bungie's Underground
    # Army") instead of recognizing it isn't a person at all.
    whole_display, _ = strip_links(body)
    if is_non_person(whole_display, nonp):
        result.drop(clean_name(whole_display) or body.strip(), "non-person")
        return 0

    character = ""
    effective_role = role
    dash_kind = None

    split = _split_outside_links(body)
    if split:
        left, right = split
        if RE_LINK.search(left):
            # Voice form: "[[Actor]]: [[Character]]". A wikilink to the left
            # of the colon is Halopedia's own structural marker that this
            # line credits a person -- every voice line in the fixture has
            # one, and no inverted-role line does -- so it discriminates the
            # shape without a memorized word list.
            name_disp, _ = strip_links(left)
            char_disp, _ = strip_links(right)
            if name_disp and char_disp:
                body, character = left, char_disp
        else:
            # No link on the left rules out the voice form. It may still be
            # the inverted "Role: Name" form used under Halo Manual. Match
            # against the ORIGINAL body, not a de-linked copy: the role word
            # itself is always plain text, so this loses nothing, and it
            # means a linked name (e.g. "Writer: [[Zach Russell|Zach
            # Russel]]") keeps its link markup for strip_links below to read
            # the canonical spelling from.
            inv = RE_INVERTED.match(clean_name(body))
            if inv:
                effective_role = inv.group(1)
                body = inv.group(2)
            else:
                # Neither shape recognized. Don't guess which side is the
                # person -- e.g. "Art Director: John Doe" matches no known
                # role word, and defaulting to the voice form would silently
                # swap the job title in for the name. Record it instead.
                result.fail(body, ref)
                return 0
    elif dash_style:
        # Per-page "ROLE - Name" / "Name - Role" line shape, or -- inside a
        # Cast/Voice section -- a per-line "Character - Actor" /
        # "Actor - Character" shape substituted in by the caller via
        # cast_dash_style (config/sources.csv). Only tried when the
        # colon-split above found nothing to split on, so a colon-based line
        # is never reinterpreted as a dash line. _split_dash_outside_links
        # never returns a fully-unspaced hyphen, so a real hyphenated
        # surname (Pettiford-Wates, Lentz-Pope) or in-universe designation
        # (John-117) is never a candidate split point.
        dsplit = _split_dash_outside_links(body)
        if dsplit:
            left, right = dsplit
            left_disp, _ = strip_links(left)
            right_disp, _ = strip_links(right)
            if left_disp and right_disp:
                if dash_style == "character-actor":
                    character, body = left_disp, right
                    dash_kind = "character-actor"
                elif dash_style == "actor-character":
                    character, body = right_disp, left
                    dash_kind = "character-actor"
                elif dash_style == "role-first":
                    effective_role, body = left_disp, right
                elif dash_style == "name-first":
                    effective_role, body = right_disp, left
            # If neither side has any text once links resolve (or the dash
            # style is unrecognized), body is left untouched -- the same
            # fall-through as when there is no dash at all.

    # Second attempt, now that the split has isolated the name. Halo: CEA
    # writes the agency BEFORE the separator -- "Pete Comley (FILTER) -
    # Sound Designer" -- so the tag is not at the end of the line and the
    # pass above cannot see it; it only becomes trailing once the role has
    # been split off. Skipped when the first pass already found a vendor,
    # because a line carries at most one: halo-4's "Clay Akazawa (IT)
    # (COROWARE)" would otherwise have its employer overwritten by the "(IT)"
    # that the first pass deliberately left behind.
    if not inline_studio:
        body, inline_studio = split_vendor_tag(body, inline_vendor)
        if inline_studio:
            studio = inline_studio

    # A bold cast heading names the character for every row beneath it until
    # the next heading. A per-line dash split is more specific and wins, the
    # same way an inline vendor tag beats section studio context.
    if character_ctx and not character:
        character = character_ctx
        dash_kind = "character-actor"

    display, canonical = strip_links(body)
    display = clean_name(display)

    if not display or is_non_person(display, nonp):
        result.drop(display or body.strip(), "non-person")
        return 0

    # A credit line that is really a roster (see RE_NAME_SHAPE above): expand
    # it into one row per name instead of one absurd multi-name "person".
    # Checked here, on the fully split/de-linked display text, so a roster
    # can only ever be recognized among genuine credit lines -- never among
    # role headings, dash-split fragments, or vendor tags, all of which have
    # already been peeled off above.
    roster = _roster_split(display)
    if roster:
        for person in roster:
            result.add(CreditRow(
                game_id=game_id,
                credit_order=order,
                name_raw=person,
                category="Voice" if dash_kind == "character-actor" else map_category(effective_role, cats),
                role_raw=effective_role,
                character=character,
                studio=studio,
                inclusion_class=_inclusion(role, effective_role),
                source_ref=ref,
            ))
            order += 1
        return len(roster)

    result.add(CreditRow(
        game_id=game_id,
        credit_order=order,
        name_raw=display,
        name_canonical=canonical,
        # character is deliberately excluded from map_category's input: a
        # character name is free text an editor typed, not a controlled
        # role vocabulary, and it can coincidentally contain a category
        # keyword that has nothing to do with the credited person's actual
        # job -- e.g. "Master Chief" contains "chief", which the Leadership
        # pattern matches, mis-categorizing every voice actor who played
        # him. character-actor/actor-character rows get "Voice" explicitly
        # instead (dash_kind), which is the only place this project ever
        # needs the character to influence category at all.
        category="Voice" if dash_kind == "character-actor" else map_category(effective_role, cats),
        role_raw=effective_role,
        character=character,
        studio=studio,
        inclusion_class=_inclusion(role, effective_role),
        source_ref=ref,
    ))
    return 1

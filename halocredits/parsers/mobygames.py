import re

from bs4 import BeautifulSoup

from ..models import CreditRow, InclusionClass, ParseResult
from ..normalize import clean_name, is_non_person, map_category

SPECIAL_THANKS = re.compile(r"(?i)special thanks|^thanks$")
BABIES = re.compile(r"(?i)\b(production babies|halo babies)\b")
# "MGS" is this project's own credits pages abbreviating "Microsoft Game
# Studios" (confirmed by sibling sections spelling it out, e.g. halo-3-odst's
# "MGS: Marketing & Public Relations" next to "MGS: Business Development"),
# not a generic word risking false positives elsewhere.
PUBLISHING = re.compile(r"(?i)\b(xbox|microsoft|mgs|marketing|public relations|localization)\b")
# A parenthetical immediately after a person's <a> link is one of three
# unrelated things, distinguished only by its own text:
#   "(as El Jefe Maestro)" / "(credited as Natalya Tatarchuk)" is a
#     pseudonym the credit lists them under -- not a `character` (treating
#     one as a character would read a producer as playing a role called
#     "El Jefe Maestro" and give them category "Voice").
#   "(Aquent)" / "(Filter)" is the SAME inline vendor tag every other
#     parser in this project already knows (halopedia.py's inline_vendor,
#     the "(VENDOR)" suffix), not a character either -- halo-3-odst's own
#     page proves this matters: "Jason R. Keith (Aquent)" sits under an
#     ordinary "3D Art Leads" crew role with no cast context at all, and
#     without this check he read as playing a character named "Aquent".
#     Checked against studio_headings, the same map role-cell-as-studio
#     already reuses -- one place per game to list a vendor's spellings.
#   "(Dalton)" is a genuine fictional character, matched only once neither
#     of the above applies.
# "(uncredited)" is a fourth, MobyGames-specific marker (halo-reach's own
# "Eddie Kim (uncredited)") meaning MobyGames itself sourced this credit
# from outside the game's own credits roll -- not a character, not a
# vendor, and not this project's business to strip the person over (the
# whole point of this session's work is recovering people the game's own
# credits under-reported), so it is ignored the same way an alias is.
RE_TAIL_PAREN = re.compile(r"^\(([^)]+)\)")
RE_ALIAS = re.compile(r"(?i)^(as|credited as)\s+|^uncredited$")


def _studio_headings(raw) -> dict[str, str]:
    """{heading text -> studio name}, casefolded. See halopedia.py's function
    of the same name for why this is an explicit per-game map rather than a
    delimiter-split heuristic: MobyGames spells the same relationship as
    "Studio - Department" on one page and "Department - Studio" on another
    (Halo: MCC's "Blur - Animation" vs its own "Audio - Finishing Move
    Inc."), so no single split rule is safe across pages, let alone games.
    A heading not present here defaults to a blank (first-party) studio.
    """
    if not raw:
        return {}
    return {clean_name(k).casefold(): clean_name(v) for k, v in raw.items()}


def _inclusion(section: str, role: str = "") -> InclusionClass:
    if BABIES.search(section):
        return InclusionClass.BABIES
    if SPECIAL_THANKS.search(section):
        return InclusionClass.SPECIAL_THANKS
    if PUBLISHING.search(section):
        return InclusionClass.PUBLISHING
    if role:
        if BABIES.search(role):
            return InclusionClass.BABIES
        if SPECIAL_THANKS.search(role):
            return InclusionClass.SPECIAL_THANKS
        # halo-reach's own "Localization Testers" sits under "Contract
        # Development and Test" -- a section name with no publishing
        # keyword at all -- while the existing Halopedia data classifies
        # this exact role as publishing (matching Xbox/Microsoft precedent
        # elsewhere in this project). Section is checked first everywhere
        # else in this function; role is only a fallback for what section
        # text alone can't see.
        if PUBLISHING.search(role):
            return InclusionClass.PUBLISHING
    return InclusionClass.CORE


def _wanted_heading(heading: str, game_prefix: str, sections) -> str | None:
    """Return the heading text this row's section is filed under (with any
    `game_prefix` stripped), or None if this heading is out of scope for the
    current invocation.

    One MobyGames page can carry more than one of our game_ids: Halo: MCC's
    page prefixes every section it owns with "Halo 2A: ", and separately
    carries one bare "Behaviour Interactive (September 2018 update)" section
    that belongs to a different game_id entirely. `game_prefix` selects the
    former shape (only headings starting with "PREFIX: " are taken, prefix
    stripped); `sections` selects the latter (only these exact headings,
    taken verbatim). Neither given means the page is its own single game --
    every heading is taken as-is, the common case for a standalone page.
    """
    if game_prefix:
        marker = f"{game_prefix}:"
        if not heading.startswith(marker):
            return None
        return clean_name(heading[len(marker):])
    if sections is not None:
        return heading if heading in sections else None
    return heading


def parse(text, game_id, options, cats, nonp) -> ParseResult:
    result = ParseResult(game_id=game_id)
    soup = BeautifulSoup(text, "lxml")
    table = soup.select_one("table.table-credits")
    if table is None:
        return result

    studio_headings = _studio_headings(options.get("studio_headings"))
    exclude_sections = {clean_name(s) for s in options.get("exclude_sections", [])}
    exclude_roles = {clean_name(s) for s in options.get("exclude_roles", [])}
    game_prefix = options.get("game_prefix", "")
    sections = options.get("sections")
    if sections is not None:
        sections = {clean_name(s) for s in sections}
    # halo-3's own "Voice Actors" section has no parenthetical character at
    # all -- the role cell IS the character ("Master Chief", "Cortana", ...)
    # and the name cell is bare, one actor per row. Explicit per-section,
    # like halopedia.py's cast_bold_style, rather than inferred from the
    # section's own name ("Cast"/"Voice" would also match "Casting &
    # Voice-Over Production Services", a vendor section with no characters
    # at all).
    cast_sections = {clean_name(s) for s in options.get("cast_sections", [])}

    section = ""   # current heading, in scope for this invocation, prefix stripped
    in_scope = False
    studio = ""
    order = 0
    for i, tr in enumerate(table.select("tr")):
        ref = f"tr{i}"
        header = tr.find("h4")
        if header is not None:
            heading = clean_name(header.get_text(" ", strip=True))
            wanted = _wanted_heading(heading, game_prefix, sections)
            if wanted is None or wanted in exclude_sections:
                in_scope = False
                continue
            in_scope = True
            section = wanted
            studio = studio_headings.get(section.casefold(), "")
            continue
        if not in_scope:
            continue

        cells = tr.find_all("td", recursive=False)
        if len(cells) < 2:
            text_ = clean_name(tr.get_text(" ", strip=True))
            if text_:
                result.fail(text_, ref)
            continue

        role = clean_name(cells[0].get_text(" ", strip=True))
        if role in exclude_roles:
            continue
        name_cell = cells[1]
        links = name_cell.find_all("a", recursive=False)
        # A third page shape, alongside the heading-named studio and the
        # inline (VENDOR) tag every other parser already knows: the ROLE
        # cell itself names the vendor, one row per company, all sitting
        # under one shared container heading with no studio of its own
        # (halo-3's "Cinematic Animation Partners" heads a roster where the
        # role column reads "DamnFX", "Corestaff", "Excell Data
        # Corporation", ...). Checked in the same studio_headings map --
        # a heading text and a role text never collide in practice, since
        # a role like "Executive Producer" is never also someone's section
        # heading -- and only overrides the section's own studio when it
        # actually matches, so an ordinary job-title role falls through to
        # the section-level default untouched.
        row_studio = studio_headings.get(role.casefold())
        row_studio = row_studio if row_studio is not None else studio

        if not links:
            # No MobyGames person link at all: the cell names one or more
            # companies, not people (e.g. "Facial Scans by" -> "Light Stage
            # Inc., TNG Visual Effects") -- the same bare-company-credit
            # shape fixed elsewhere in this project via
            # config/studio-only-credits.csv. Recorded, not fabricated as a
            # person.
            whole = clean_name(name_cell.get_text(" ", strip=True))
            if not whole:
                continue
            for company in whole.split(","):
                company = company.strip()
                if company:
                    result.drop(company, "studio-mention")
            continue

        cast_row = section in cast_sections

        for a in links:
            name = clean_name(a.get_text(" ", strip=True))
            if not name:
                continue
            name_studio = row_studio
            if cast_row:
                # The role cell IS the character; there is no parenthetical
                # to read on this page shape.
                character = role
            else:
                # A trailing "(...)" is plain text immediately after this
                # person's </a>, not inside any <a> -- read from the link's
                # own tail string, which ends at the next comma or the
                # cell's end.
                tail = a.next_sibling if isinstance(a.next_sibling, str) else ""
                m = RE_TAIL_PAREN.match(clean_name(tail))
                paren = m.group(1).strip() if m else ""
                paren_studio = studio_headings.get(paren.casefold()) if paren else None
                if paren_studio is not None:
                    character = ""
                    name_studio = paren_studio
                elif not paren or RE_ALIAS.match(paren):
                    character = ""
                else:
                    character = paren
            if is_non_person(name, nonp):
                result.drop(name, "non-person")
                continue
            result.add(CreditRow(
                game_id=game_id,
                credit_order=order,
                name_raw=name,
                category="Voice" if character else map_category(f"{role} {section}", cats),
                role_raw="Voice Actor" if cast_row else (role or section),
                character=character,
                studio=name_studio,
                inclusion_class=_inclusion(section, role),
                source_ref=ref,
            ))
            order += 1

    return result

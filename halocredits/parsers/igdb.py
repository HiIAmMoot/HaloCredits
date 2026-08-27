import re

from bs4 import BeautifulSoup

from ..models import CreditRow, InclusionClass, ParseResult
from ..normalize import clean_name, is_non_person, map_category

FIRST_PARTY = re.compile(r"(?i)^(343 industries|microsoft studios|bungie)$")
MICROSOFT_STUDIOS = re.compile(r"(?i)^microsoft studios$")
SPECIAL_THANKS = re.compile(r"(?i)special thanks")
BABIES = re.compile(r"(?i)(production babies|halo babies)")
PUBLISHING = re.compile(r"(?i)\b(microsoft|marketing|public relations|localization|xbox)\b")
PERFORMANCE = re.compile(r"(?i)\(performance\)")
SUPPORT_SUFFIX = re.compile(r"(?i)\s*\(support company\)\s*$")


def _inclusion(section: str, company: str, role: str = "") -> InclusionClass:
    if BABIES.search(section):
        return InclusionClass.BABIES
    if SPECIAL_THANKS.search(section):
        return InclusionClass.SPECIAL_THANKS
    # `company` (the enclosing credits-company row, if any is still in
    # scope -- see _parse_staff) is checked alongside the section-text
    # regex rather than folded into it: "Mircosoft Studios User Research"
    # is a real typo on the page (misspelled "Mircosoft"), and a page-wide
    # roster header should not be corrected just to make a regex match --
    # that is fragile by construction and only papers over the next typo.
    # Keying off the *company* instead answers the actual question ("is
    # this row credited under Microsoft Studios' corporate roster?")
    # without caring how any one section heading happens to be spelled.
    if PUBLISHING.search(section) or MICROSOFT_STUDIOS.match(company):
        return InclusionClass.PUBLISHING
    # `role` (the row's own table-cell title, e.g. "Special Thanks") is a
    # fallback checked only when `section` did not already classify the
    # row -- the same section-first, per-row-second order used elsewhere,
    # so a "Special Thanks" section's own rows keep classifying by the
    # section regardless of what their individual titles say.
    if role and SPECIAL_THANKS.search(role):
        return InclusionClass.SPECIAL_THANKS
    return InclusionClass.CORE


def _company_label(tr) -> str:
    """Extract just the company name from a credits-company /
    credits-supportcompany row.

    A ``credits-company`` row (343 Industries, Microsoft Studios) is a
    single ``<td colspan="4">`` wrapping an ``<h3>`` -- the row's whole text
    IS the company name. A ``credits-supportcompany`` row (the 25 third-party
    vendors) is laid out differently: two separate ``<td>`` cells, the first
    holding the company name/link and the second holding a role description
    that always ends in the literal suffix "(Support Company)" (e.g. "Skybox
    Labs" | "Additional Engineering (Support Company)"). Reading the whole
    row's text -- as a naive ``tr.get_text()`` does -- concatenates both
    cells and leaves that description text sitting inside `studio` for every
    one of those 25 vendors and everyone credited under them. Reading only
    the first ``<td>`` gives the bare company name in both row shapes.
    """
    cells = tr.find_all("td", recursive=False)
    text = cells[0].get_text(" ", strip=True) if cells else tr.get_text(" ", strip=True)
    return clean_name(text)


def _support_descriptor(tr) -> str:
    """Second-cell text of a credits-supportcompany row, minus its trailing
    "(Support Company)" suffix.

    Used to detect Halo 5's "Special Thanks" block, which is an
    alphabetized peer list of thanked companies *and* thanked individuals
    interleaved together -- a support-company row there sits at its own
    alphabetical position among the names, it does not head a sub-list of
    people who work there. Structurally, its descriptor is exactly the
    enclosing section name repeated back ("Special Thanks"), whereas every
    genuine vendor-attribution row elsewhere on the page has a distinct
    descriptor ("Music Production", "Recorded at", ...). See _parse_staff.
    """
    cells = tr.find_all("td", recursive=False)
    if len(cells) < 2:
        return ""
    text = cells[1].get_text(" ", strip=True)
    return clean_name(SUPPORT_SUFFIX.sub("", text))


def parse(text, game_id, options, cats, nonp) -> ParseResult:
    result = ParseResult(game_id=game_id)
    soup = BeautifulSoup(text, "lxml")
    order = 0
    order = _parse_staff(soup, result, game_id, order, cats, nonp)
    _parse_voice(soup, result, game_id, order, cats, nonp)
    return result


def _parse_staff(soup, result, game_id, order, cats, nonp) -> int:
    pane = soup.select_one("#credits-employees")
    if pane is None:
        return order

    studio, section, company = "", "", ""
    for i, tr in enumerate(pane.select("tr")):
        classes = tr.get("class") or []
        ref = f"employees:tr{i}"

        if "credits-company" in classes:
            label = _company_label(tr)
            company = label
            studio = "" if FIRST_PARTY.match(label) else label
            continue
        if "credits-supportcompany" in classes:
            label = _company_label(tr)
            descriptor = _support_descriptor(tr)
            # A support-company row unambiguously means we've moved from
            # an internal corporate roster into vendor-driven content, so
            # the enclosing `company` no longer applies from here on.
            company = ""
            if descriptor and descriptor == section:
                # Peer-thanked company (see _support_descriptor) -- record
                # it, but it is not anyone's employer here.
                result.drop(label, "support-company-thanked")
            else:
                studio = label
            continue
        if "credits-misc" in classes:
            section = clean_name(tr.get_text(" ", strip=True))
            # A new section resets studio: a support-company row's
            # attribution only ever applies to the rows immediately
            # beneath it, up to the next section boundary. Left unreset,
            # an unrelated later section (Production Babies, In Memory,
            # Test Reserves) silently inherits whatever vendor was last
            # mentioned, fabricating an employment relationship for named
            # private individuals -- e.g. every one of the 83 Production
            # Babies rows would otherwise read studio="Wunderman", the
            # last Special Thanks vendor alphabetically.
            studio = ""
            continue

        cells = tr.find_all("td", recursive=False)
        if len(cells) < 2:
            text = clean_name(tr.get_text(" ", strip=True))
            if text:
                result.fail(text, ref)
            continue

        name = clean_name(cells[0].get_text(" ", strip=True))
        role = clean_name(cells[1].get_text(" ", strip=True))
        if not name:
            text = clean_name(tr.get_text(" ", strip=True))
            if text:
                result.fail(text, ref)
            continue
        if is_non_person(name, nonp) or len(name) > 80:
            result.drop(name, "non-person")
            continue

        result.add(CreditRow(
            game_id=game_id,
            credit_order=order,
            name_raw=name,
            category=map_category(f"{role} {section}".strip(), cats),
            role_raw=role or section,
            studio=studio,
            inclusion_class=_inclusion(section, company, role),
            source_ref=ref,
        ))
        order += 1
    return order


def _parse_voice(soup, result, game_id, order, cats, nonp) -> int:
    pane = soup.select_one("#credits-voice")
    if pane is None:
        return order

    language = ""
    for i, tr in enumerate(pane.select("tr")):
        ref = f"voice:tr{i}"
        header = tr.find(["h3", "h4"])
        if header is not None:
            language = clean_name(header.get_text(" ", strip=True))
            continue

        body = tr.select_one(".media-body")
        target = tr.select_one("td.text-right")
        if body is None or target is None:
            text = clean_name(tr.get_text(" ", strip=True))
            if text:
                result.fail(text, ref)
            continue

        name = clean_name(body.get_text(" ", strip=True))
        character = clean_name(target.get_text(" ", strip=True))
        if not name:
            text = clean_name(tr.get_text(" ", strip=True))
            if text:
                result.fail(text, ref)
            continue

        # Spec section 6.2: English cast only, and the language must be read
        # rather than assumed.
        if language.lower() != "english":
            result.drop(f"{name} - {character}", f"non-english-voice:{language or 'unknown'}")
            continue

        if is_non_person(name, nonp):
            result.drop(name, "non-person")
            continue

        result.add(CreditRow(
            game_id=game_id,
            credit_order=order,
            name_raw=name,
            category="Voice",
            role_raw="Performance Capture" if PERFORMANCE.search(character) else "Voice Actor",
            character=character,
            inclusion_class=InclusionClass.CORE,
            source_ref=ref,
        ))
        order += 1
    return order

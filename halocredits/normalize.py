import csv
import re
from pathlib import Path

# Halo 2's page wraps nearly every credit line in a trailing <br> (and
# occasionally <br/> / <br />) to force a wiki line break within a single
# list paragraph. It carries no content -- left in place it lands directly
# in name_raw/role_raw/character for the majority of that game's rows. No
# other Halopedia fixture uses it, so stripping it here is a safe, general
# cleanup rather than a per-game special case.
RE_HTML_BREAK = re.compile(r"(?i)<br\s*/?>")

NBSP = " "


# --------------------------------------------------------------------------
# Inline staffing-agency / vendor tags
#
# Every source in this project glues the agency onto the end of the credited
# name -- "Jason Lackie (INSIGHT GLOBAL)", "Joseph Shih (Lionbridge
# Technologies, Inc.)", "Kevin Dalziel (Filter)". Left in place the tag lands
# in name_raw, and that name can then never be matched to the same person on
# another game, which is the entire point of the dataset.
#
# Three parsers had independently grown three patterns of three different
# sophistications, and the LEAST sophisticated one covered the MOST games.
# Both live patterns are hoisted here so a future parser picks one instead of
# writing a fourth.
# --------------------------------------------------------------------------

# The discriminating pattern (first written for Halo Infinite). An ALL-CAPS
# parenthetical is accepted on its own -- that is the common case and caps
# are a strong signal. A mixed-case parenthetical is accepted ONLY when it
# ends in a recognizable corporate suffix, because without that condition it
# also swallows things like "TenEighteen (Cobb)" -- a community
# contributor's second handle, sitting right alongside genuine mixed-case
# agency tags on the same page. Commas are inside both character classes on
# purpose: "24 SEVEN TOPCO, LLC", "MIT GATHERING CO., LTD." and "Populus
# Group, LLC" are all real, and the earliest version of this pattern
# excluded commas and so missed every one of them.
VENDOR_TAG = re.compile(
    r"\s*\("
    r"([A-Z0-9][A-Z0-9\s&.,\-]{1,50}"
    r"|[A-Za-z][A-Za-z0-9\s&.,\-]{1,50}\b(?:LLC|Inc\.?|Corp\.?|Ltd\.?|Co\.?))"
    r"\)\s*$"
)

# The permissive pattern: any trailing parenthetical is the vendor. Only safe
# on a page where that is empirically true of every occurrence -- it is on
# Halo: Reach (162 of 163 trailing parentheticals are companies: Volt,
# Xversity, Excell, Aquent, Comsys, Filter, ...) and on Halo: CEA (23 of 24,
# the 24th being an infobox line outside the credits section). It is
# emphatically NOT true on Halo 4, where 26 lines end in a role annotation
# like "(Engineering)" or "(Design)". Which pattern a page gets is per-game
# config, never a guess -- see inline_vendor in config/sources.csv.
#
# The lookahead excludes a URL: "WAVES Audio Plug-ins (www.waves.com)" is a
# middleware credit and "www.waves.com" is not an employer.
PARENTHETICAL_TAG = re.compile(r"\s*\(\s*(?!www\.|https?://)([^()]{1,60}?)\s*\)\s*$")

# Halo 3: ODST tags a handful of vendors in SQUARE brackets rather than
# parentheses -- "Stan LePard [Panther modern]", "Michael Salvatori [Total
# music]", "Eric Osborne [Xversity]". Left unread, the tag stays inside
# name_raw, which both loses the vendor and splits the person from their
# other credits ("Stan LePard" and "Stan LePard [Panther modern]" resolve to
# two people). Wiki link syntax is already resolved before this runs, so a
# remaining "[...]" is never a link.
SQUARE_TAG = re.compile(r"\s*\[\s*([^\[\]]{1,60}?)\s*\]\s*$")

VENDOR_TAG_MODES = {
    "suffix": VENDOR_TAG,
    "any-parenthetical": PARENTHETICAL_TAG,
    "any-bracket": re.compile(
        r"\s*[\(\[]\s*(?!www\.|https?://)([^()\[\]]{1,60}?)\s*[\)\]]\s*$"),
    "square": SQUARE_TAG,
}


def vendor_tag_pattern(mode):
    """Resolve an ``inline_vendor`` option value to a pattern, or None.

    ``True`` selects the discriminating pattern, so per-game config that
    merely switches the feature on keeps meaning what it always meant.
    """
    if not mode:
        return None
    if mode is True:
        return VENDOR_TAG
    try:
        return VENDOR_TAG_MODES[mode]
    except KeyError:
        raise ValueError(
            f"unknown inline_vendor mode {mode!r}; "
            f"expected true or one of {sorted(VENDOR_TAG_MODES)}"
        ) from None


def split_vendor_tag(text: str, pattern) -> tuple[str, str]:
    """Return (text with its trailing vendor tag removed, the vendor name)."""
    if pattern is None:
        return text, ""
    m = pattern.search(text)
    if not m:
        return text, ""
    return text[: m.start()], clean_name(m.group(1))


def load_category_map(path: Path) -> list[tuple[re.Pattern, str]]:
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.append((re.compile(r["pattern"]), r["category"]))
    return out


def map_category(role: str, mapping: list[tuple[re.Pattern, str]]) -> str:
    for pattern, category in mapping:
        if pattern.search(role or ""):
            return category
    return "Other"


def load_non_person_patterns(path: Path) -> list[re.Pattern]:
    """One regex per line; blank lines and ``#`` comment lines are skipped.

    Comments matter more here than in most config. Every pattern in this file
    deletes rows, and an over-broad one deletes real credited people silently
    -- the exact failure the audit log exists to prevent. A pattern that
    cannot say in a comment which rows it is for, and that those are the only
    rows it hits, has not been checked. No pattern legitimately starts with
    ``#``, so this costs nothing.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [re.compile(ln) for ln in lines
            if ln.strip() and not ln.lstrip().startswith("#")]


def is_non_person(line: str, patterns: list[re.Pattern]) -> bool:
    text = clean_name(line)
    if not text:
        return True
    return any(p.search(text) for p in patterns)


def clean_name(raw: str) -> str:
    text = RE_HTML_BREAK.sub(" ", (raw or "").replace(NBSP, " "))
    return re.sub(r"\s+", " ", text).strip()

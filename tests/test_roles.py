import csv
import glob
from collections import Counter, defaultdict
from pathlib import Path

from halocredits.roles import (ALL_CLASSES, ART, AUDIO, DISCIPLINES, INFERRED, LIVE,
                               MANAGEMENT, QA, STATED, UNSPECIFIED, WRITING,
                               heading_of, load_category_patterns,
                               load_heading_index, load_heading_patterns,
                               load_mobygames_roles, load_name_tags,
                               load_vendor_types, resolve, row_class)

ROOT = Path(__file__).resolve().parents[1]
VENDOR_TYPES = load_vendor_types(ROOT / "config" / "vendor-types.csv")
HEADING_PATTERNS = load_heading_patterns(ROOT / "config" / "role-headings.csv")
HEADING_INDEX = load_heading_index(ROOT / "data" / "source-headings.csv")
NAME_TAGS = load_name_tags(ROOT / "data" / "name-role-tags.csv")
MOBY_ROLES = load_mobygames_roles(ROOT / "data" / "mobygames-roles.csv")
CATEGORY_PATTERNS = load_category_patterns(ROOT / "config" / "category-map.csv")


def _resolve(rows, game_id="", name=""):
    return resolve(rows, VENDOR_TYPES, HEADING_PATTERNS, game_id, HEADING_INDEX,
                   name, NAME_TAGS, MOBY_ROLES, CATEGORY_PATTERNS)


def _pairs():
    pairs = defaultdict(list)
    for path in glob.glob(str(ROOT / "data" / "credits" / "*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                pairs[(row["name_raw"], row["game_id"])].append(
                    (row["category"], row["studio"], row["source_ref"],
                     row["role_raw"], row["inclusion_class"]))
    return pairs


def test_a_stated_category_always_wins_over_inference():
    """A row that says what it is must never be overridden by its studio's
    general line of work. Only silence gets inferred."""
    cls, prov = row_class("Art", "Volt", VENDOR_TYPES)   # Volt is typed testing
    assert (cls, prov) == (ART, STATED)


def test_inference_only_fires_on_an_empty_category():
    cls, prov = row_class("Other", "Volt", VENDOR_TYPES)
    assert (cls, prov) == (QA, INFERRED)


def test_development_is_not_a_discipline_and_is_never_inferred():
    """"Development" says a studio built part of the game, not which craft.
    Mapping it would colour hundreds of outsourced artists as programmers."""
    cls, prov = row_class("Other", "Lionbridge Games", VENDOR_TYPES)
    assert cls is UNSPECIFIED


def test_a_real_discipline_beats_unspecified_however_many_rows_say_it():
    """Someone credited once as an artist and five times under a bare vendor
    label is an artist. Counting rows would bury them in grey."""
    rows = [("Other", ""), ("Other", ""), ("Other", ""), ("Art", "")]
    assert _resolve(rows)[0] == ART


def test_multi_category_pairs_resolve_by_specificity():
    """Leadership is a stronger claim about a person than a second art
    credit, so it wins the tiebreak."""
    assert _resolve([("Art", ""), ("Leadership", "")])[0] == MANAGEMENT
    assert _resolve([("Audio", ""), ("Production", "")])[0] == AUDIO


def test_every_person_game_pair_gets_exactly_one_known_class():
    """The grid draws one marker per pair, so the classifier must be total."""
    for key, rows in _pairs().items():
        cls, prov = _resolve(rows, key[1], key[0])
        assert cls in ALL_CLASSES, key
        assert prov in (STATED, INFERRED), key


# Measured over the committed CSVs. Exact, so a category or vendor-type
# change that moves the composition cannot pass unnoticed.
# 781/1034/1562/108 -> 772/1028/1561/112: name-fixes.csv discards removed
# nine halo-4/halo-reach rows that had resolved to management or writing
# (fabricated "people" -- middleware vendors and fake community orgs, see
# test_identity.py's DISTINCT_PEOPLE note), and the four real Halo: Reach
# community members reclassified core->community via
# config/inclusion-overrides.csv now resolve to "community" (their own
# STANDING_ALWAYS class) instead of whatever category their row carried.
# 686/165 -> 685/164: halo-infinite's "Slate & Ash" (Design category,
# resolved "design") and "Texas Film Commission" (Other category, resolved
# "unspecified") were both discarded as non-person credits -- see
# test_identity.py's DISTINCT_PEOPLE note. The alias merges in that same
# pass don't move these counts: they touch identity resolution in
# data/people.csv, not the raw (name, game) credit rows this test counts.
PINNED = {
    "management": 772, "production": 718, "engineering": 1839, "art": 2705,
    "design": 685, "audio": 790, "writing": 1028, "qa": 2124,
    "live": 179, "publishing": 200, "community": 112, "thanks": 1561,
    "unspecified": 164,
}


def test_pinned_role_composition():
    counts = Counter()
    for (name, game), rows in _pairs().items():
        counts[_resolve(rows, game, name)[0]] += 1
    assert dict(counts) == PINNED
    assert sum(counts.values()) == 12877


def test_inference_is_a_small_minority_of_classified_pairs():
    """If inference ever carried a large share, the grid would be showing
    guesses at the same weight as the credits' own words."""
    prov = Counter()
    for (name, game), rows in _pairs().items():
        cls, p = _resolve(rows, game, name)
        if cls is not UNSPECIFIED:
            prov[p] += 1
    assert prov[INFERRED] == 433
    assert prov[INFERRED] / sum(prov.values()) < 0.04


def test_disciplines_and_neutrals_do_not_overlap():
    assert UNSPECIFIED not in DISCIPLINES
    assert len(set(ALL_CLASSES)) == len(ALL_CLASSES)


def test_the_heading_is_read_before_the_studio():
    """"Digic / MoCap" says what this block of people did; "Digic is a
    development vendor" says only that the company built part of the game.
    The specific statement has to win, or capture artists become unspecified."""
    cls, prov = row_class("Other", "Digic", VENDOR_TYPES, "Digic/MoCap#1204",
                          HEADING_PATTERNS)
    assert (cls, prov) == (ART, INFERRED)


def test_headings_are_recovered_for_refs_that_do_not_carry_one():
    """Halopedia refs are line numbers and MobyGames refs are row indices.
    Neither says anything alone; both sit under a heading that does."""
    assert heading_of("L395", "halo-cea", HEADING_INDEX)
    assert heading_of("mobygames:tr88", "halo-mcc", HEADING_INDEX)
    # and with no index there is nothing to recover, rather than a guess
    assert heading_of("L395", "halo-cea", {}) == ""


def test_translation_blocks_read_as_language_work():
    cls, prov = row_class("Other", "Lionbridge Games", VENDOR_TYPES,
                          "Lionbridge Games/French Translation Support#12",
                          HEADING_PATTERNS)
    assert (cls, prov) == (WRITING, INFERRED)


def test_heading_patterns_contain_no_control_characters():
    """A pattern written as '\b' in a non-raw Python string becomes a literal
    backspace, which compiles fine and then silently matches nothing. Three
    patterns were shipped that way once; this catches the next one."""
    for pattern, cls in HEADING_PATTERNS:
        assert not any(ord(ch) < 32 for ch in pattern.pattern), (cls, pattern.pattern)


def test_word_boundaries_keep_art_out_of_department():
    """Without \b, 'art' matches inside 'Department', 'Cartography' and
    'Quartz', which would paint support staff as artists."""
    for probe in ("Support Department", "Cartography Team", "Quartz Group"):
        assert not [c for pat, c in HEADING_PATTERNS if pat.search(probe)], probe
    assert [c for pat, c in HEADING_PATTERNS if pat.search("Tech Art")] == [ART]


def test_a_department_tag_beside_a_name_counts_as_stated():
    """The credits printed "Seth Gibson (Tech Art)". That is the source
    speaking about the individual, not an inference from their neighbours."""
    cls, prov = row_class("Other", "", VENDOR_TYPES, "", HEADING_PATTERNS,
                          "", None, "Seth Gibson", NAME_TAGS)
    assert (cls, prov) == (ART, STATED)


def test_mobygames_covers_every_game_it_has_a_page_for():
    """The three pages added last (Combat Evolved, its Anniversary, and
    Campaign Evolved) are the ones whose wiki rolls name the fewest jobs."""
    games = {game for game, _name in MOBY_ROLES}
    for expected in ("halo-ce", "halo-cea", "halo-campaign-evolved",
                     "halo-infinite", "halo-mcc"):
        assert expected in games, expected


def test_an_explicit_mobygames_role_resolves_a_silent_credit():
    """Jason Jones is credited on Combat Evolved with no job in the wiki
    roll; MobyGames says "Project Lead"."""
    cls, prov = row_class(
        "Other", "", VENDOR_TYPES, "", HEADING_PATTERNS, "halo-ce", None,
        "Jason Jones", None, MOBY_ROLES, CATEGORY_PATTERNS)
    assert prov == STATED
    assert cls in ("production", "management")


def test_mobygames_never_overrides_a_role_the_credit_already_names():
    cls, prov = row_class(
        "Art", "", VENDOR_TYPES, "", HEADING_PATTERNS, "halo-ce", None,
        "Jason Jones", None, MOBY_ROLES, CATEGORY_PATTERNS)
    assert (cls, prov) == (ART, STATED)


def test_volunteers_read_as_community_not_as_a_missing_role():
    """MCC's 2025 update is fifty community volunteers and no developers.
    They are marked as volunteers, so the grid must not show them as having
    no recorded role."""
    counts = Counter()
    for (name, game), rows in _pairs().items():
        if game == "halo-mcc-2025":
            counts[_resolve(rows, game, name)[0]] += 1
    assert counts == Counter({"community": 50})


def test_standing_never_overrides_a_stated_craft():
    """Special Thanks blocks are subdivided by department -- the rolls carry
    their own "ART" and "ENGINEERING" sub-headings -- and publisher-side
    credits include localization testers. Letting standing win would throw
    away what the credits say."""
    assert row_class("Art", "", VENDOR_TYPES, "", HEADING_PATTERNS, "", None,
                     "", None, None, (), "ART", "special-thanks")[0] == ART
    assert row_class("QA", "", VENDOR_TYPES, "", HEADING_PATTERNS, "", None,
                     "", None, None, (), "Localization Testers",
                     "publishing")[0] == QA


def test_standing_still_fills_silence():
    cls, prov = row_class("Other", "", VENDOR_TYPES, "", HEADING_PATTERNS, "",
                          None, "", None, None, (), "", "special-thanks")
    assert (cls, prov) == ("thanks", STATED)


def test_a_stem_pattern_matches_its_own_plural():
    """A trailing \b after a stem defeats it: \brecruit\b cannot match
    "RECRUITERS" and "project manage\b" cannot match "Project Manager".
    Both shipped that way and quietly matched nothing."""
    for probe, expected in (("RECRUITERS", "management"),
                            ("Project Manager", "production"),
                            ("Software Test Engineers", "qa"),
                            ("Web Developer", "engineering")):
        hits = [c for pat, c in HEADING_PATTERNS if pat.search(probe)]
        assert hits and hits[0] == expected, (probe, hits)


def test_names_with_no_stated_work_stay_unspecified():
    """Novelty and photo credits -- "Draft Dodgers", "OTHER FACES", "... And
    the Rest of the Bungie Crew" -- name no work, and neither do bare agency
    labels. Inventing a craft for them would be a guess."""
    for probe in ("Draft Dodgers", "Halo 3 Contributors",
                  "... And the Rest of the Bungie Crew",
                  "Sakson and Taylor", "Rare"):
        assert not [c for pat, c in HEADING_PATTERNS if pat.search(probe)], probe


def test_live_and_support_is_its_own_class():
    """Player-facing work is a real and growing function -- the community
    command centre, player support and safety, esports, Waypoint -- and does
    not belong to any development craft."""
    for probe in ("DCC TEAM MEMBERS", "Support Agent Team", "PRO TEAM",
                  "WAYPOINT AND ECOSYSTEM TEAM", "HALO SUPPORT"):
        hits = [c for pat, c in HEADING_PATTERNS if pat.search(probe)]
        assert hits and hits[0] == LIVE, (probe, hits)


def test_studio_it_is_not_player_support():
    """"SUPPORT TECHS" keep the studio running; "Support Agent" answers
    players. The live rule sits first, so the distinction has to be carried
    by the words, not by the ordering alone."""
    hits = [c for pat, c in HEADING_PATTERNS if pat.search("SUPPORT TECHS")]
    assert hits and hits[0] == "engineering"


def test_a_scan_credit_is_talent_not_art():
    """People scanned to become a character are talent. The rule must not
    reach "Studio Head", "Head of Engineering" or "Production Head", which
    is why it never matches a bare "head" or "body"."""
    for probe in ("OTHER FACES", "CORTANA BODY", "FACE OF THOMAS LASKY"):
        hits = [c for pat, c in HEADING_PATTERNS if pat.search(probe)]
        assert hits and hits[0] == "writing", (probe, hits)
    for probe in ("Studio Head", "Head of 343 Industries"):
        assert not [c for pat, c in HEADING_PATTERNS if pat.search(probe)], probe
    assert [c for pat, c in HEADING_PATTERNS
            if pat.search("HEAD OF ENGINEERING")][0] == "engineering"

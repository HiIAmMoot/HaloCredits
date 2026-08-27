from pathlib import Path

from halocredits.config import load_games
from halocredits.identity import load_aliases, load_credit_rows, load_reviews, resolve
from halocredits.lineage import ERAS, era_of, lineage
from halocredits.studios import load_studio_classes

ROOT = Path(__file__).resolve().parents[1]
GAMES = load_games(ROOT / "config" / "games.csv")


def _real_rows_and_people():
    rows = load_credit_rows(ROOT / "data" / "credits")
    aliases = load_aliases(ROOT / "config" / "aliases.csv")
    reviews = load_reviews(ROOT / "config" / "identity-review.csv")
    people = resolve(rows, GAMES, aliases, reviews)
    return rows, people


def _real_lineage(first_party_only=False):
    rows, people = _real_rows_and_people()
    classes = load_studio_classes(ROOT / "config" / "studio-classes.csv")
    return lineage(rows, people, GAMES, classes, first_party_only=first_party_only)


def test_eras_cover_every_game_exactly_once():
    assigned = [g for era in ERAS.values() for g in era]
    assert len(assigned) == len(set(assigned))
    assert set(assigned) == set(GAMES)


def test_era_boundaries():
    assert era_of("halo-reach") == "Bungie"
    assert era_of("halo-cea") == "343 Industries"      # 343's first project
    assert era_of("halo-infinite") == "343 Industries"
    assert era_of("halo-campaign-evolved") == "Halo Studios"


def test_lineage_counts_prior_games_only():
    """A first draft compared each game against its whole era INCLUDING
    itself and reported Halo 4 as 94% ex-343. Carryover means people who
    worked on a game EARLIER in the sequence."""
    rows = {r["game_id"]: r for r in _real_lineage()}
    h4 = rows["halo-4"]
    assert h4["from_343"] < h4["roster"] * 0.5


def test_bungie_carryover_concentrates_in_the_first_343_project():
    """The dilution is the finding: veterans seeded 343's small first team,
    then the studio grew sevenfold and they became a minority."""
    fp = {r["game_id"]: r for r in _real_lineage(first_party_only=True)}
    cea, h4 = fp["halo-cea"], fp["halo-4"]
    assert cea["from_bungie"] / cea["roster"] > 0.25
    assert h4["from_bungie"] / h4["roster"] < 0.10
    assert h4["roster"] > cea["roster"] * 5


def test_halo_studios_is_not_a_new_studio_on_its_own_staff():
    """83% of Campaign Evolved's credited staff have no prior Halo credit --
    but 1,330 of them are outsourced vendors who were never going to recur.
    On first-party staff the majority are carryover."""
    all_staff = {r["game_id"]: r for r in _real_lineage()}["halo-campaign-evolved"]
    first_party = {r["game_id"]: r for r in
                   _real_lineage(first_party_only=True)}["halo-campaign-evolved"]
    assert all_staff["no_prior_halo"] / all_staff["roster"] > 0.8
    carryover = first_party["from_bungie"] + first_party["from_343"]
    assert carryover / first_party["roster"] > 0.5


# Measured: lineage() over the real corpus (all core rows, committed
# aliases/reviews/studio-classes). Exact -- pins the full row for the three
# games that answer the two headline claims, in both views.
#
# halo-cea and halo-4 moved after lineage.py stopped re-deriving identity
# from an ambiguous {variant: person} lookup (see review of Task 8):
# halo-4's and halo-cea's composer-credit compound lines are variants shared
# by three Person objects apiece (both real composers plus each line's own
# phantom "person"), and the old lookup silently kept only the phantom.
# Michael Salvatori and Martin O'Donnell now correctly carry halo-cea and
# halo-4 as prior-Halo appearances (Bungie veterans, so both counts move in
# from_bungie's favour), and each compound line's own phantom entry is
# excluded from the roster as redundant -- see lineage._real_people.
# halo-campaign-evolved is untouched: it has no such compound line.
PINNED_LINEAGE = {
    False: {
        # game_id: (roster, from_bungie, from_343, no_prior_halo)
        #
        # halo-4's roster moved 949 -> 945 (no_prior_halo 828 -> 824): four
        # halo-4 rows were fabricated "people" for bare company names on
        # "===Additional Content Developed By===" (Axis Animation, Digic
        # Pictures, Hollywood Studio Symphony, Technicolor Game-Sound
        # Services) and are now discarded -- see the matching note in
        # test_stats.py's PINNED_STATS.
        # halo-4's roster/from_343 moved 945/73 -> 946/74 after "James
        # Cassidy & Barry Campbell" was split via name-fixes.csv (see
        # test_stats.py's PINNED_STATS): Barry Campbell is a genuine new
        # halo-4 credit.
        # Internal-corpus dedup (see test_identity.py's DISTINCT_PEOPLE
        # note) merged pre-existing duplicate people across games -- a
        # person previously double-counted as two separate identities on
        # two different games now correctly carries prior-Halo history,
        # shifting from_bungie/from_343/no_prior_halo on any game where
        # one of their identities recurs.
        # halo-cea's roster moved 371 -> 370 (no_prior_halo 328 -> 327) after
        # the Scott Martin Gershin merge -- see test_identity.py's
        # DISTINCT_PEOPLE note.
        # halo-4 grew after the MobyGames redo landed -- see test_identity.py's
        # DISTINCT_PEOPLE note.
        # halo-cea's roster moved 370 -> 368 (no_prior_halo 327 -> 325): the
        # Peter Zinda and Justin Langley duplicate merges, see
        # test_identity.py's DISTINCT_PEOPLE note.
        # halo-4's roster/no_prior_halo moved 963/816 -> 958/811: the five
        # middleware-vendor discards (Digital Extremes, Bink Video, Granny
        # 3D, FaceFX, FaceGen), see test_identity.py's DISTINCT_PEOPLE note.
        "halo-cea": (368, 43, 0, 325),
        "halo-4": (958, 81, 88, 811),
        "halo-campaign-evolved": (1626, 39, 283, 1319),
    },
    True: {
        # game_id: (roster, from_bungie, from_343, no_prior_halo)
        #
        # halo-cea and halo-4 moved after halopedia.py's bold-line handler
        # started consulting studio_headings (STUDIO_LEVEL_BOLD): rows on
        # halo-3/halo-3-odst/halo-4 that carried a blank studio -- damnfx,
        # Excell Data Corporation, Volt, Xversity, Rare, Filter, FilmOasis,
        # Sakson and Taylor, Zoic Studios, FASA, Certain Affinity, Digital
        # Extremes -- now correctly read as vendor staff, so a person whose
        # only prior credit was one of those rows no longer counts as
        # first-party history on a later game. halo-cea: one CEA returner's
        # only earlier appearance was a now-vendor halo-3/odst row (from_bungie
        # 30 -> 29, no_prior_halo 52 -> 53). halo-4: its own roster shrinks
        # from 596 to 485 because first_party_only excludes halo-4's own
        # newly-vendor Certain Affinity/Digital Extremes rows from the roster
        # itself, not just from prior-game history. It moves again, 485 ->
        # 481, for the same four-row discard described in the False block
        # above (all four carried a blank studio, so first_party_only was
        # already counting them).
        # halo-4's roster/no_prior_halo moved 481/437 -> 482/438 for the
        # same Barry Campbell split described in the False block above.
        # Same internal-corpus dedup as the False block above, plus the
        # MobyGames redo's halo-4 growth (see test_identity.py's
        # DISTINCT_PEOPLE note).
        # halo-4's roster/no_prior_halo moved 523/471 -> 518/466 for the same
        # five middleware-vendor discards described in the False block above.
        "halo-cea": (82, 29, 0, 53),
        "halo-4": (518, 39, 30, 466),
        "halo-campaign-evolved": (297, 33, 156, 121),
    },
}


def test_pinned_exact_counts_for_cea_halo4_and_campaign_evolved():
    for first_party_only, expected in PINNED_LINEAGE.items():
        rows = {r["game_id"]: r for r in _real_lineage(first_party_only=first_party_only)}
        for game_id, (roster, from_bungie, from_343, no_prior) in expected.items():
            actual = rows[game_id]
            assert (actual["roster"], actual["from_bungie"], actual["from_343"],
                    actual["no_prior_halo"]) == (roster, from_bungie, from_343, no_prior), \
                (first_party_only, game_id)

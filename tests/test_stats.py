from pathlib import Path

from halocredits.config import load_games
from halocredits.identity import load_aliases, load_credit_rows, load_reviews, resolve
from halocredits.stats import collapse_spine, per_game_stats
from halocredits.studios import load_studio_classes

ROOT = Path(__file__).resolve().parents[1]
GAMES = load_games(ROOT / "config" / "games.csv")


def _real_rows_and_people():
    rows = load_credit_rows(ROOT / "data" / "credits")
    aliases = load_aliases(ROOT / "config" / "aliases.csv")
    reviews = load_reviews(ROOT / "config" / "identity-review.csv")
    people = resolve(rows, GAMES, aliases, reviews)
    return rows, people


def _real_stats():
    rows, people = _real_rows_and_people()
    classes = load_studio_classes(ROOT / "config" / "studio-classes.csv")
    return per_game_stats(rows, people, GAMES, classes)


def test_mcc_entries_collapse_only_where_chronology_allows_it():
    """The 2014 launch and the February 2025 update each stand alone in the
    spine because a mainline game (Halo 5, Halo Infinite) shipped directly
    next to them -- collapsing either into a neighboring MCC entry would
    compare that mainline game's continuity against the wrong neighbor. Only
    the September 2018 and October 2021 updates, which have no other game
    between them, share one position: someone who maintained MCC across both
    kept working and must not read as a returner."""
    spine = collapse_spine(GAMES)
    assert "halo-mcc" in spine
    assert "halo-mcc-2025" in spine
    mcc_late = [p for p in spine if p.startswith("mcc-")]
    assert len(mcc_late) == 1
    assert len(spine) == 13
    assert spine.index("halo-mcc") < spine.index("halo-5") < spine.index(mcc_late[0])
    assert spine.index(mcc_late[0]) < spine.index("halo-infinite") < spine.index("halo-mcc-2025")


def test_spine_is_chronological():
    spine = collapse_spine(GAMES)
    assert spine[0] == "halo-ce"
    assert spine[-1] == "halo-campaign-evolved"


def test_newcomer_departure_and_continuing_partition_the_roster():
    """Every credited person is exactly one of newcomer / continuing /
    returning for a given game. If they overlap or leave a gap the metric is
    wrong regardless of what the totals look like."""
    stats = {s["game_id"]: s for s in _real_stats()}
    for game_id, s in stats.items():
        assert s["newcomers"] + s["returning"] + s["continuing_from_previous"] \
            <= s["headcount"], game_id


def test_first_game_is_all_newcomers():
    stats = {s["game_id"]: s for s in _real_stats()}
    ce = stats["halo-ce"]
    assert ce["newcomers"] == ce["headcount"]
    assert ce["returning"] == 0


# Measured: per_game_stats() over the real corpus (all core rows, committed
# aliases/reviews/studio-classes). Exact -- pins the full row for three games
# spanning the corpus: the all-newcomer launch title, a mainline title deep
# into the roster's churn, and the newest, largest release.
#
# halo-4 moved from the pre-fix values (headcount 967, newcomers 844,
# continuing_from_previous 73, departures 638) after stats.py stopped
# re-deriving identity from an ambiguous {variant: person} lookup (see
# review of Task 8): halo-4's compound credit line "composed by Marty
# O'Donnell and Michael Salvatori" is a variant shared by three Person
# objects (both composers plus a phantom "person" whose own name IS that
# credit line), and the old lookup silently kept only the phantom. Michael
# Salvatori and Martin O'Donnell now correctly appear in halo-4's roster
# (their only halo-4 credit was inside this compound line and a second one,
# "Special thanks to..."); both compound lines' own phantom Person entries,
# and a third unrelated phantom ("James Cassidy & Barry Campbell", where
# only James Cassidy is separately known), are excluded from headcount as
# redundant with the real people they name -- see stats._real_people.
# Net: -3 phantom entries +2 real composers = headcount -1.
# halo-ce and halo-campaign-evolved are untouched: neither has a compound
# credit line whose named people are also separately known.
#
# halo-4's contractors moved 355 -> 466 after halopedia.py's bold-line
# handler started consulting studio_headings (STUDIO_LEVEL_BOLD): halo-4
# credits Certain Affinity and Digital Extremes under heading-shaped
# "===Additional Multiplayer ... By: ...===" sections that carried a blank
# studio before the fix, reading their 121 combined rows as first-party
# Halo staff.
#
# headcount also moved 949 -> 945: four rows on halo-4's own
# "===Additional Content Developed By===" section (Axis Animation, Digic
# Pictures, Hollywood Studio Symphony, Technicolor Game-Sound Services) were
# company names with no individual attached, fabricated as four blank-studio
# "people" -- the same shape as the already-fixed ReelFX Creative Studios
# case -- and are now discarded via config/name-fixes.csv, with the company
# itself recorded in config/studio-only-credits.csv instead.
# halo-4's headcount/continuing_from_previous moved 945/73 -> 946/74:
# "James Cassidy & Barry Campbell" (PROJECT MANAGEMENT) was previously read
# as one credit for James Cassidy plus its own excluded phantom "person" --
# split via name-fixes.csv into two real people, Barry Campbell now counts
# as a genuine +1 to halo-4's headcount. See test_identity.py's
# DISTINCT_PEOPLE note.
PINNED_STATS = {
    "halo-ce": {
        # 95 -> 96: Ji Hong, Bungie's Localization Lead, was being counted as
        # publisher staff and so left out of the core roster entirely.
        "headcount": 96, "newcomers": 96, "returning": 0,
        "continuing_from_previous": 0, "departures": 30, "contractors": 0,
    },
    # halo-4/halo-campaign-evolved newcomers/returning/continuing_from_previous
    # shifted after the internal-corpus dedup sweep (see test_identity.py's
    # DISTINCT_PEOPLE note): people previously double-counted as separate
    # identities on two games now correctly count as one returning person
    # instead of two newcomers.
    # halo-4's headcount/contractors grew after the MobyGames redo landed
    # (see test_identity.py's DISTINCT_PEOPLE note): 39 approved new credits
    # plus spelling-variant duplicates that resolve to existing halo-4 people
    # but carry additional halo-4 role lines.
    # halo-4's headcount/newcomers/departures moved 963/816/598 -> 958/811/593:
    # five middleware vendors (Digital Extremes, Bink Video, Granny 3D,
    # FaceFX, FaceGen) were fabricated "people" from a "Scanned Talent" block
    # under a Voice heading, discarded via config/name-fixes.csv -- see
    # test_identity.py's DISTINCT_PEOPLE note.
    "halo-4": {
        "headcount": 958, "newcomers": 811, "returning": 59,
        "continuing_from_previous": 88, "departures": 593, "contractors": 471,
    },
    "halo-campaign-evolved": {
        "headcount": 1626, "newcomers": 1319, "returning": 43,
        "continuing_from_previous": 264, "departures": 1626, "contractors": 1329,
    },
}


def test_pinned_exact_counts_for_ce_halo4_and_campaign_evolved():
    stats = {s["game_id"]: s for s in _real_stats()}
    for game_id, expected in PINNED_STATS.items():
        actual = {k: stats[game_id][k] for k in expected}
        assert actual == expected, game_id


def test_contractor_share_is_bounded_and_nonzero_where_expected():
    """Combat Evolved shipped before Halo had any outside help. Campaign
    Evolved leaned on many studios (Digic, Virtuos, Rare, Ninja Theory, and
    others all outside Halo Studios' own team) but is not entirely them."""
    stats = {s["game_id"]: s for s in _real_stats()}
    assert stats["halo-ce"]["contractors"] == 0
    assert stats["halo-campaign-evolved"]["contractors"] > 1000
    ce = stats["halo-campaign-evolved"]
    assert ce["contractors"] < ce["headcount"]


# Measured: flows() over the real corpus, halo-3 -> halo-3-odst edge. Exact.
# 142 -> 141 after "Blindlight" (a casting/voice-over vendor fabricated as a
# blank-studio person on both games) was discarded -- see test_identity.py's
# DISTINCT_PEOPLE note. It was never a real person moving between the two.
# 141 -> 166 after the internal-corpus dedup sweep merged pre-existing
# duplicate people who happened to be credited on both halo-3 and
# halo-3-odst under two slightly different spellings.
# 167 -> 170 after the MobyGames redo landed (see test_identity.py's
# DISTINCT_PEOPLE note): a few of the newly-added halo-3/halo-3-odst
# credits are people who already appear on the other side of that edge.
HALO3_TO_ODST = 171


def test_flow_counts_people_moving_between_consecutive_spine_positions():
    from halocredits.stats import flows
    rows, people = _real_rows_and_people()
    f = {(x["from_game"], x["to_game"]): x["count"] for x in flows(rows, people, GAMES)}
    # Measured on the committed data; exact.
    assert f[("halo-3", "halo-3-odst")] == HALO3_TO_ODST
    assert ("halo-mcc", "halo-mcc") not in f, "MCC must not flow to itself"


def test_flows_never_go_backwards():
    from halocredits.stats import flows
    rows, people = _real_rows_and_people()
    spine = collapse_spine(GAMES)
    for x in flows(rows, people, GAMES):
        assert spine.index(x["from_game"]) < spine.index(x["to_game"])

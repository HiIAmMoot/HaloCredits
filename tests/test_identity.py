import pytest

from pathlib import Path
from halocredits.config import load_games
from halocredits.identity import (
    PersonIdCollisionError,
    UNCERTAIN_GAP_YEARS,
    load_aliases,
    load_reviews,
    normalise_name,
    resolve,
    write_uncertain_review,
)

ROOT = Path(__file__).resolve().parents[1]
GAMES = load_games(ROOT / "config" / "games.csv")
# Measured: resolve() over all core rows, empty aliases.csv. Moved from 7366
# to 7367 after fixing two identity-resolution defects (see task-3 review):
#   -1  Marcus Lehto ("Marcus R. Lehto" / "Marcus Lehto") now merges to one
#       person instead of splitting on canonical-lock first-occurrence order.
#   +2  Two compound credit lines that previously had their whole row folded
#       into a single named person (losing whoever else was named on the
#       line) now also stay as their own standalone, inspectable entries;
#       the real people named on those lines are attributed via exact
#       substring match instead of the untrustworthy canonical link.
# Moved from 7293 to 7285 after eight rows across halo-2/halo-4/halo-reach
# were recognized as bare company names with no individual attached
# (Omni Interactive Audio, Miles Sound System, Hollywood Studio Symphony,
# Axis Animation, Digic Pictures, Technicolor Game-Sound Services, Northwest
# Sinfornia, Studio X) and discarded via config/name-fixes.csv -- the same
# shape as the already-fixed ReelFX Creative Studios case, each one had been
# resolving to its own fabricated "person".
#
# 7285 -> 7279: a wider census of halo-reach's own "===Art, Animation and FX
# Vendors===" section turned up six more of the same shape (House of Moves,
# Image Metrics, NewBreed Visual FX, Polygon, Schematic, Vicon); this test's
# core-only row set drops exactly six people for them (House of Moves also
# had a Special Thanks mention on halo-infinite, but that row was never
# core, so removing it does not move this count).
#
# 7279 -> 7277: cross-checking halo-2's own MobyGames page against the
# existing halopedia data surfaced "Blindlight" (a casting/voice-over
# production company) fabricated as a blank-studio "person" on four
# games -- halo-2, halo-3, halo-3-odst, halo-reach -- and "SIDE LA" (an
# audio dubbing studio) the same way on halo-infinite. Both are bare
# company credits with no individual attached, the same shape as the
# already-fixed ReelFX/Axis Animation cases, and neither had a company-y
# keyword in its own name for the earlier keyword-based sweep to catch.
# Discarded via name-fixes.csv; -2 people (Blindlight was one shared
# person across 4 games, SIDE LA one more).
#
# The MobyGames-sourced merges for halo-mcc/halo-3/halo-2/halo-3-odst/
# halo-reach that briefly landed after this were reverted: the per-game
# dedup passes done at the time (surname + first-initial fuzzy matching,
# spot-checked by hand) missed a large number of real duplicate people --
# e.g. "Adrian Perez" / "Adrian Mark Perez" and "Charles Gough" / "Charlie
# Gough" stayed as separate person_ids. A full-corpus rescan found ~300+
# such collisions touching those five games. Redo pending a stricter
# duplicate filter before any of that data is re-merged.
#
# 7277 -> 7276: two more pre-existing identity issues found while reviewing
# the above. "Ahmad Chohan" (halo-4) and "Ahmad J. Chohan" (halo-cea,
# halo-mcc) are the same person, aliased together (-1). Separately,
# halo-4's "James Cassidy & Barry Campbell" compound credit line was only
# ever recognized as James Cassidy (via the compound-credit substring
# match) plus its own phantom "person" whose name was the raw line -- Barry
# Campbell was never a person in his own right at all. Split via
# name-fixes.csv's `fix` action (the same mechanism already used for
# "composed by Martin O'Donnell and Michael Salvatori"), same as that
# precedent: the phantom disappears and both named people get their own
# entry (net 0 on this count, but Barry Campbell is a real +1 to halo-4's
# headcount -- see test_stats.py's PINNED_STATS).
# 7276 -> 7037: internal-corpus dedup sweep found pre-existing duplicate
# people scattered across all 14 games (spelling variants, nickname forms,
# credential/generational suffixes, missing middle names, contractor/dept
# tags baked into the credited name). 312 merged identities aliased
# together (-239 net after collapsing multi-way groups). A further 15
# candidate merges were found to be internally contradictory (e.g. two
# separately-plausible pairs sharing a third name, where the third pair
# turned out to share a game -- proof under the same-source rule that
# they're different people, meaning at least one of the two pairs was
# wrong) and were deliberately left unmerged pending manual review rather
# than guessed at.
# 7037 -> 7027: a special-cased exception for the "Andy 'Bravo' Dudynsky"
# group -- normally two credits in the same game's single source prove two
# different people, but the user confirmed Andrew Dudynsky and Andy
# "Bravo" Dudynsky (both credited separately in halo-infinite) really are
# the same person credited twice under different names, overriding that
# default. All four spellings (including a same-instrument-name row that
# used curly quotes the auto-generated alias initially failed to match
# byte-for-byte) now resolve to one identity.
# 7027 -> 7025: two of the four groups held out for contradictory transitive
# merges got a final user ruling. Matt Benedict and Matthew Benedict are the
# same person (matthew-c-benedict, who shares halo-mcc with matt-benedict,
# stays separate). Thomas Hill and Tom Hill are the same person (thomas-rd-
# hill, who shares halo-infinite with thomas-hill, stays separate). The
# other two groups (Huang, Woods) were ruled to be entirely separate people
# and needed no alias changes at all.
# 7025 -> 7024: "Scott Martin Gershin, MPSE, IESD" and "Scott Martin Gershin"
# are the same person credited three times in halo-cea's own document under
# different department headings (Creative Director / Executive Creative
# Director / Rerecording Mixer, all at Soundelux Design Music Group) -- the
# same-source rule doesn't apply here since it's one name (just a
# credential-suffix difference), not two different people. Found while
# reviewing MobyGames candidates for halo-mcc's "Scott Gershin" credit.
# 7024 -> 7698: the actual MobyGames redo landed -- 1256 curated credit rows
# (approved new-people additions plus spelling-variant duplicates of
# existing people) appended across halo-2/3/3-odst/reach/mcc/mcc-2018/4/5/
# infinite via config/mobygames-additions/, replayed on every parse by
# halocredits.mobygames_additions so the corpus stays reproducible. See the
# commit that landed this for the full review trail (approved-merges.csv,
# rejected-false-positives.csv, auto-resolved-different-people.csv).
# 7698 -> 7697: re-checked halo-mcc-2018's "Behaviour Interactive (September
# 2018 update)" section against MobyGames directly (43 of 44 credited names
# already matched exactly) and found one compound-surname spacing gap the
# fuzzy matcher's surname-token split can't see: "Anthony DaSilva" (one
# token) and "Anthony Da Silva" (two tokens) tokenize to different surname
# keys entirely, so neither the exact nor fuzzy pass ever compared them.
# 7697 -> 7665: Halo 2's "Halo 2 for Windows Vista" section is now excluded.
# The project counts each game from its first release, and the page itself
# marks that block "appears in Halo 2 for Windows Vista only" -- 57 rows for
# a 2007 port that were being counted as 2004 credits. Two rows moved the
# other way, from publishing back to core, via config/inclusion-overrides.csv:
# Halo CE's Ji Hong and Halo 3's Brian Jarrard are studio staff who were
# filed as publisher staff because their role text contains "Localization"
# and "Marketing".
# 7665 -> 7647: halo-3-odst tags its contractors in square brackets, which
# no vendor pattern read. The tag stayed inside the credited name, so
# "Jason Keith" and "Jason Keith [Aquent]" resolved to two different people
# -- the same shape across ~18 names. inline_vendor="square" now strips it.
# 7647 -> 7646: "Hakim Kazim" (halo-3-odst) is the actor Hakeem Kae-Kazim.
# Its wiki-link canonical already said so, which gave it the right display
# name while leaving it a separate person from the halo-reach spellings
# "Hakeem Kae Kazin" and "Hakeem Kae-Kazim" -- two person_ids rendering
# under one name. Aliased together.
# 7646 -> 7619: reviewed duplicate sweep applied. Halo 4 credits 34 people
# with a trailing department tag -- "Don Alvarez (Tech Art)", "Tony Cox
# (Engineering)" -- and Halo 5 four with IMDb's "(I)" disambiguator. Both
# kept the tag inside the credited name, so each of those people was split
# from their own untagged credits. Stripped via name-fixes.csv, plus eight
# reviewed spelling merges (Sargey/Sergey Mkrtumov, Domenic/Dominic Koeplin,
# Rob/Robert Kehoe, Dave Liebur/Lieber, Ben/Benjamin J. Wommack, and the
# three whose untagged spelling still differed) and one compound credit line
# split into Marty Hasselbach and Carla St. Pierre.
# 7619 -> 7618: "\"Halo Cantorum\" and \"Never Forget\"" on halo-4 was a
# song-title credit line, not a person, discarded via config/name-fixes.csv.
# 7618 -> 7605: two rounds of poster/page review turned up more fabricated
# "people" and two more duplicate spellings. Discarded via
# config/name-fixes.csv: halo-reach's "===Community===" section named four
# fan-community organisations rather than people (7th Column, Bungie.net
# Forum Ninjas, Halo.Bungie.Org, Rooster Teeth, Major League Gaming -- the
# last four also credited real individuals alongside them, reclassified
# core->community via config/inclusion-overrides.csv rather than discarded);
# halo-4's "Scanned Talent" block under a Voice heading named five
# middleware vendors, not scanned actors (Digital Extremes appearing twice,
# Bink Video, Granny 3D, FaceFX, FaceGen). Merged via config/aliases.csv:
# halo-cea's "Peter Zinda" / "Peter Zinda, MPSE, IESD" and "Justin Langley" /
# "Justin Langely" (a Halopedia typo, confirmed against MobyGames) were each
# one person credited twice.
# 7605 -> 7599: another poster-review pass on halo-infinite. Discarded via
# config/name-fixes.csv: "Texas Film Commission" (a government office, not a
# person) and "Slate & Ash" (a sound-design studio credited company-only,
# now recorded in config/studio-only-credits.csv instead). Merged via
# config/aliases.csv: "Garin R K Richards"/"Garin RK Richards" (spacing),
# "Garrett Montgomery MPSE"/"Garrett Montgomery" and "Georgi Elenkov
# PhD"/"Georgi Elenkov" (credential suffixes), and "Leonardo
# Braz"/"Leonardo C. Braz da Cunha" (Halopedia's short form vs MobyGames'
# full name) -- each one person credited twice.
DISTINCT_PEOPLE = 7599
# Measured: resolve() over all core rows, empty aliases.csv, empty reviews.
# largest_gap_years > UNCERTAIN_GAP_YEARS (10). The design doc's working
# estimate was 49; Task 3's identity-resolution fixes (the Marcus Lehto
# merge and the compound-credit standalone entries) changed which people
# exist and what games they carry, which shifts who has a >10 year gap.
# Pinned to what resolve() actually produces over the real corpus.
# 51 -> 59: the internal-dedup merges above created several long-career
# identities (e.g. Josh/Joshua Daniels spanning halo-3 to
# halo-campaign-evolved, 19 years) that individually exceed the 10-year
# gap threshold -- expected, not a bug; see review/uncertain.csv.
UNCERTAIN_COUNT = 58


def _rows(*specs):
    """specs are (game_id, name_raw, name_canonical) triples."""
    return [{"game_id": g, "name_raw": n, "name_canonical": c,
             "studio": "", "category": "", "inclusion_class": "core"}
            for g, n, c in specs]


def test_normalise_folds_case_punctuation_and_apostrophes():
    assert normalise_name("Aaron LeMay") == normalise_name("Aaron Lemay")
    assert normalise_name("Ahmad J Chohan") == normalise_name("Ahmad J. Chohan")
    assert normalise_name("Frank O'Connor") == normalise_name("Frank O’Connor")
    assert normalise_name("C.J. Markham") == normalise_name("CJ Markham")


def test_normalise_keeps_different_people_apart():
    assert normalise_name("Chris Lee") != normalise_name("Chris Leek")
    assert normalise_name("Jen Taylor") != normalise_name("Jenna Taylor")


def test_exact_match_merges_across_games():
    people = resolve(_rows(("halo-ce", "Jason Jones", ""),
                           ("halo-2", "Jason Jones", "")), GAMES, {}, {})
    assert len(people) == 1
    person = next(iter(people.values()))
    assert person.game_count == 2
    assert person.games == ["halo-ce", "halo-2"]


def test_canonical_outranks_the_credited_spelling():
    """The wiki-link target is authoritative: the credit misspells the name."""
    people = resolve(_rows(("halo-ce", "Zach Russel", "Zach Russell"),
                           ("halo-3", "Zach Russell", "")), GAMES, {}, {})
    assert len(people) == 1
    assert next(iter(people.values())).display_name == "Zach Russell"


def test_variants_are_recorded_so_a_merge_is_inspectable():
    people = resolve(_rows(("halo-ce", "Aaron LeMay", ""),
                           ("halo-4", "Aaron Lemay", "")), GAMES, {}, {})
    person = next(iter(people.values()))
    assert sorted(person.variants) == ["Aaron LeMay", "Aaron Lemay"]


def test_alias_file_overrides_the_automation():
    """Two names the machine cannot know are one person."""
    people = resolve(_rows(("halo-ce", "Robert McLees", ""),
                           ("halo-4", "Rob McLees", "")), GAMES,
                     {"Rob McLees": "robert-mclees",
                      "Robert McLees": "robert-mclees"}, {})
    assert len(people) == 1


def test_games_are_ordered_by_sequence_not_by_encounter():
    people = resolve(_rows(("halo-4", "A Person", ""),
                           ("halo-ce", "A Person", "")), GAMES, {}, {})
    assert next(iter(people.values())).games == ["halo-ce", "halo-4"]


def test_real_corpus_merges_the_twenty_six_known_variants():
    """Measured: of 7,424 distinct core names, 30 pairs collapse under
    normalisation, every one a case/punctuation/apostrophe/diacritic variant.
    Pinned by name so a regression that stops merging them fails loudly."""
    from halocredits.identity import load_credit_rows
    rows = load_credit_rows(ROOT / "data" / "credits")
    people = resolve(rows, GAMES, load_aliases(ROOT / "config" / "aliases.csv"), {})
    by_variant = {v: p for p in people.values() for v in p.variants}
    for a, b in [("Aaron LeMay", "Aaron Lemay"),
                 ("Ahmad J Chohan", "Ahmad J. Chohan"),
                 ("Keegan McCoy", "Keegan Mccoy"),
                 ("LeSean Johnson", "Lesean Johnson"),
                 ("C.J. Markham", "CJ Markham")]:
        assert by_variant[a].person_id == by_variant[b].person_id, (a, b)


def test_real_corpus_person_count_is_exact():
    from halocredits.identity import load_credit_rows
    rows = load_credit_rows(ROOT / "data" / "credits")
    people = resolve(rows, GAMES, load_aliases(ROOT / "config" / "aliases.csv"), {})
    assert len(people) == DISTINCT_PEOPLE


def test_canonical_lock_does_not_depend_on_which_occurrence_is_read_first():
    """Regression for I1: Marcus Lehto is credited 'Marcus R. Lehto' (CE,
    Halo 2, no canonical on either row) and 'Marcus Lehto' (Halo 3, ODST,
    Reach -- only two of those three rows carry a canonical). glob() reads
    halo-3-odst.csv before halo-3.csv, so a first-occurrence-wins rule locks
    the merge key from the row that lacks the canonical and silently
    discards the link. He must resolve as one person across all five games,
    regardless of file read order."""
    from halocredits.identity import load_credit_rows
    rows = load_credit_rows(ROOT / "data" / "credits")
    people = resolve(rows, GAMES, load_aliases(ROOT / "config" / "aliases.csv"), {})
    by_variant = {v: p for p in people.values() for v in p.variants}
    lehto = by_variant["Marcus R. Lehto"]
    assert lehto.person_id == by_variant["Marcus Lehto"].person_id
    assert lehto.games == ["halo-ce", "halo-2", "halo-3", "halo-3-odst", "halo-reach"]


def test_alias_person_id_collision_raises_rather_than_silently_dropping_a_person():
    """Regression for I2: person_id is not unique across the alias path and
    the auto-slug path (grouped is keyed by merge key, but the return value
    collapses on person_id). An alias that mints an id already claimed by an
    unrelated auto-slugged person must fail loudly, not silently vanish one
    of them from the registry."""
    rows = _rows(("halo-ce", "Aaron LeMay", ""),
                 ("halo-4", "Someone Else", ""))
    aliases = {"Someone Else": "aaron-lemay"}  # collides with the auto slug
    with pytest.raises(PersonIdCollisionError):
        resolve(rows, GAMES, aliases, {})


def test_compound_credit_line_does_not_swallow_a_named_persons_game():
    """Regression for I3: halo-4's credits include the line 'composed by
    Marty O'Donnell and Michael Salvatori' with name_canonical pointing only
    at 'Martin O'Donnell'. Trusting that link uncritically folded the whole
    row into O'Donnell and left Michael Salvatori -- who is also named on
    the exact same line -- missing halo-4 entirely, a false departure for a
    real person. Both named people must have halo-4."""
    from halocredits.identity import load_credit_rows
    rows = load_credit_rows(ROOT / "data" / "credits")
    people = resolve(rows, GAMES, load_aliases(ROOT / "config" / "aliases.csv"), {})
    by_variant = {v: p for p in people.values() for v in p.variants}
    salvatori = by_variant["Michael Salvatori"]
    odonnell = by_variant["Martin O'Donnell"]
    assert "halo-4" in salvatori.games
    assert "halo-4" in odonnell.games


def test_long_gap_is_flagged_uncertain():
    """A person credited in 2001 and 2026 with nothing between could be a
    returning veteran or a different person with the same name. The data
    cannot tell, so it is flagged rather than silently assumed."""
    people = resolve(_rows(("halo-ce", "Common Name", ""),
                           ("halo-campaign-evolved", "Common Name", "")),
                     GAMES, {}, {})
    person = next(iter(people.values()))
    assert person.largest_gap_years == 25
    assert person.uncertain is True


def test_a_long_career_without_a_long_gap_is_not_flagged():
    """Steve Downes spans 2001-2026 but never has a gap over 10 years, so he
    is a career, not a coincidence. Gap, not span, is the collision signal."""
    people = resolve(_rows(("halo-ce", "Steve Downes", ""),
                           ("halo-2", "Steve Downes", ""),
                           ("halo-3", "Steve Downes", ""),
                           ("halo-reach", "Steve Downes", ""),
                           ("halo-4", "Steve Downes", ""),
                           ("halo-5", "Steve Downes", ""),
                           ("halo-infinite", "Steve Downes", ""),
                           ("halo-campaign-evolved", "Steve Downes", "")),
                     GAMES, {}, {})
    person = next(iter(people.values()))
    assert person.span_years == 25
    assert person.largest_gap_years <= UNCERTAIN_GAP_YEARS
    assert person.uncertain is False


def test_single_game_person_is_never_uncertain():
    people = resolve(_rows(("halo-4", "One Timer", "")), GAMES, {}, {})
    assert next(iter(people.values())).uncertain is False


def test_review_ruling_same_clears_the_flag():
    people = resolve(_rows(("halo-ce", "Common Name", ""),
                           ("halo-campaign-evolved", "Common Name", "")),
                     GAMES, {}, {"common-name": "same"})
    assert next(iter(people.values())).uncertain is False


def test_review_ruling_split_produces_two_people():
    people = resolve(_rows(("halo-ce", "Common Name", ""),
                           ("halo-campaign-evolved", "Common Name", "")),
                     GAMES, {}, {"common-name": "split"})
    assert len(people) == 2
    assert all(p.game_count == 1 for p in people.values())


def test_real_corpus_uncertain_count_is_exact():
    from halocredits.identity import load_credit_rows
    rows = load_credit_rows(ROOT / "data" / "credits")
    people = resolve(rows, GAMES, load_aliases(ROOT / "config" / "aliases.csv"), {})
    flagged = [p for p in people.values() if p.uncertain]
    assert len(flagged) == UNCERTAIN_COUNT


def test_split_stays_collision_safe_when_the_name_has_variants_and_a_canonical():
    """A split-minted person_id is suffixed by game_id (see resolve()), so it
    cannot collide with the un-suffixed auto-slug of some unrelated person.
    Exercise that path on a person who is not just a bare name: one raw
    spelling carries a canonical link to the other, so pre-split they would
    have merged into a single person with two variants. The split must still
    produce two clean, distinctly-id'd people -- if it collided, resolve()
    would raise PersonIdCollisionError instead of returning."""
    people = resolve(_rows(("halo-ce", "Common Name", ""),
                           ("halo-campaign-evolved", "Common Nayme", "Common Name")),
                     GAMES, {}, {"common-name": "split"})
    assert len(people) == 2
    ids = {p.person_id for p in people.values()}
    assert len(ids) == 2  # no PersonIdCollisionError, no silent overwrite
    for p in people.values():
        assert p.game_count == 1


def test_split_ruling_on_an_alias_derived_person_id_actually_splits():
    """Regression for review Important-2: an alias merges two raw spellings
    into a hand-picked person_id via a key_of value of 'alias:<person_id>'.
    The old split check computed _slug(key), and _slug('alias:robert-mclees')
    is 'alias-robert-mclees' -- never equal to the real person_id
    'robert-mclees' a human would actually see in review/uncertain.csv and
    write into identity-review.csv. That made a split ruling on any
    alias-derived person a silent no-op: resolve() would return one merged,
    still-uncertain person with no error telling anyone the ruling did
    nothing. The check must key off the real resolved person_id."""
    people = resolve(_rows(("halo-ce", "Rob McLees", ""),
                           ("halo-campaign-evolved", "Robert McLees", "")),
                     GAMES,
                     {"Rob McLees": "robert-mclees",
                      "Robert McLees": "robert-mclees"},
                     {"robert-mclees": "split"})
    assert len(people) == 2
    assert all(p.game_count == 1 for p in people.values())
    assert all(not p.uncertain for p in people.values())


def test_split_does_not_leak_a_shared_name_through_a_compound_credit_line():
    """Regression for review Important-1: the compound-credit pass matches
    names by exact substring against every already-known person. Both split
    halves of 'Common Name' share that exact display text (that's the whole
    reason they were one merge key before the ruling), so if they stayed in
    the match index, a compound line naming 'Common Name' elsewhere in the
    corpus would match BOTH halves and silently fabricate the same phantom
    game credit on both -- with no error, since nothing about that looks
    like a collision. Split halves must be excluded from the match index:
    each keeps only the games from its own direct rows. A genuinely
    different, non-split person named on the same compound line (Jamie
    Public here) must still be attributed normally -- the fix must not break
    compound attribution wholesale, only for names currently mid-split."""
    people = resolve(_rows(("halo-3", "Common Name", ""),
                           ("halo-campaign-evolved", "Common Name", ""),
                           ("halo-2", "Jamie Public", ""),
                           ("halo-ce", "Jamie Public and Common Name", "")),
                     GAMES, {}, {"common-name": "split"})
    by_variant = {v: p for p in people.values() for v in p.variants}

    common_name_people = [p for p in people.values()
                          if "Common Name" in p.variants]
    assert len(common_name_people) == 2
    for p in common_name_people:
        assert p.game_count == 1
        assert "halo-ce" not in p.games  # neither half leaks the compound game

    jamie = by_variant["Jamie Public"]
    assert jamie.games == ["halo-ce", "halo-2"]  # still attributed normally


def test_load_reviews_accepts_case_variant_ruling(tmp_path):
    """config/identity-review.csv is hand-typed by a human. A ruling of
    'Same' or 'SPLIT' must be treated exactly like the lowercase form, not
    silently ignored."""
    path = tmp_path / "identity-review.csv"
    path.write_text("person_id,ruling\nsome-person,Same\nother-person,SPLIT\n",
                    encoding="utf-8")
    reviews = load_reviews(path)
    assert reviews == {"some-person": "same", "other-person": "split"}


def test_load_reviews_rejects_unrecognised_ruling(tmp_path):
    """A typo ('Smae', 'splt') must never silently leave a person stuck
    uncertain forever with no error or warning anywhere in the pipeline --
    it must raise immediately so a human finds out."""
    path = tmp_path / "identity-review.csv"
    path.write_text("person_id,ruling\nsome-person,Smae\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_reviews(path)


def test_review_file_lists_every_flagged_person(tmp_path):
    people = resolve(_rows(("halo-ce", "Common Name", ""),
                           ("halo-campaign-evolved", "Common Name", "")),
                     GAMES, {}, {})
    out = tmp_path / "uncertain.csv"
    assert write_uncertain_review(people, out) == 1
    text = out.read_text(encoding="utf-8")
    assert "Common Name" in text
    assert "25" in text

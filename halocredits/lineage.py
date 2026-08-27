import csv
from collections import defaultdict
from pathlib import Path

from .identity import _is_compound_credit
from .studios import classify_studio


def _real_people(people) -> list:
    """Person objects that should count as a distinct individual for
    lineage/carryover purposes. See stats._real_people for the full
    rationale: resolve() deliberately keeps one Person per compound credit
    line (e.g. "composed by Marty O'Donnell and Michael Salvatori") for
    inspectability even after correctly attributing that line's game to
    every real person named on it, so counting the line's own phantom
    Person in addition to the real people it names would double-count the
    same credit. Excluded only when resolve()'s compound-credit pass found
    at least one real match for it (some OTHER person's variants also
    contain this phantom's own display name); a compound-looking name
    resolve() could not match to anyone else stays counted as before.
    """
    by_variant: dict[str, set] = defaultdict(set)
    for p in people.values():
        for v in p.variants:
            by_variant[v].add(p.person_id)
    return [p for p in people.values()
            if not (_is_compound_credit(p.display_name)
                   and len(by_variant[p.display_name]) > 1)]

# CE Anniversary is 343's: they are the credited developer and it was their
# first Halo project. Saber Interactive's remaster work is recorded separately
# in `studio`, so this hides nothing.
#
# Halo Studios is 343 RENAMED (October 2024), not a different company. These
# are studios, not names -- the rename itself must never read as a change of
# studio. MCC's February 2025 update contributes no first-party staff: its 50
# credits are community Reclaimers, excluded by the `core` filter, so its
# roster is always empty regardless of era -- it is placed in "Halo Studios"
# only because that update shipped after the October 2024 rename, and every
# game must have exactly one era for `era_of` to be total.
ERAS = {
    "Bungie": ["halo-ce", "halo-2", "halo-3", "halo-3-odst", "halo-reach"],
    "343 Industries": ["halo-cea", "halo-4", "halo-mcc", "halo-mcc-2018",
                       "halo-mcc-2021", "halo-5", "halo-infinite"],
    "Halo Studios": ["halo-mcc-2025", "halo-campaign-evolved"],
}
_ERA_OF = {g: era for era, gs in ERAS.items() for g in gs}


def era_of(game_id: str) -> str:
    return _ERA_OF[game_id]


def lineage(rows, people, games, classes, first_party_only=False) -> list[dict]:
    """For each game: how many of its people had already worked on a Halo game
    under an earlier studio.

    Carryover is decided against games strictly earlier in `sequence` than
    the game being reported on -- never against the game's own era as a
    whole, which would trivially count every person on a 343 game as "from
    343 Industries" including on the game itself (an earlier draft made this
    exact mistake and reported Halo 4 as 94% ex-343).

    `first_party_only` restricts the input rows to those with a blank
    `studio` column before computing both the roster AND each person's
    appearance history for this view. That is deliberate: a vendor credit
    on an earlier game does not make someone "a Bungie developer" or "a 343
    developer" in the sense the two headline claims mean, so it must not
    count as carryover into a later first-party roster either. The all-staff
    view (the default) keeps every row and answers a different, broader
    question.

    Both views are required outputs: they disagree sharply, and the gap is
    itself the finding. Campaign Evolved reads ~83% new on all staff because
    over a thousand outsourced vendor credits could never recur by
    construction, but its own first-party people are majority carryover.
    Publishing only the all-staff number would give a confidently wrong
    answer to "is this a new studio".

    Roster and appearance history are read off `Person.games` rather than
    re-derived from rows via a variant-string lookup: a row's `name_raw` can
    be a variant shared by more than one real Person (a compound credit line
    naming two people at once) plus a phantom "person" for the line itself,
    and a naive `{variant: person}` lookup silently collapses all of that
    onto whichever one was written last. `Person.games` is what resolve()
    already worked out correctly, compound lines included, so building on it
    directly cannot be fooled by a shared variant string.
    """
    seq = {g.game_id: g.sequence for g in games.values()}

    appearances = defaultdict(set)   # person_id -> game_ids
    roster = defaultdict(set)        # game_id -> person_ids
    real = _real_people(people)
    if first_party_only:
        # A person's first-party appearance in a game is decided per row,
        # scoped on BOTH the variant match and Person.games membership -- the
        # same scoping _vendor_pairs in stats.py uses for the mirror-image
        # question ("does this row's vendor signal belong to this person").
        # That keeps a shared variant string (the compound-credit case) from
        # ever being asked to resolve to a single Person, and iterating only
        # over `real` (not people.values()) keeps a compound line's own
        # already-redundant phantom entry out of the first-party roster too.
        by_variant = defaultdict(list)
        for p in real:
            for v in p.variants:
                by_variant[v].append(p)
        for row in rows:
            if classify_studio(row["studio"], classes) != "":
                continue
            gid = row["game_id"]
            for p in by_variant.get(row["name_raw"], ()):
                if gid in p.games:
                    appearances[p.person_id].add(gid)
                    roster[gid].add(p.person_id)
    else:
        for p in real:
            for gid in p.games:
                appearances[p.person_id].add(gid)
                roster[gid].add(p.person_id)

    out = []
    for game in sorted(games.values(), key=lambda g: g.sequence):
        gid = game.game_id
        crew = roster[gid]
        counts = {"Bungie": 0, "343 Industries": 0, "Halo Studios": 0}
        new = 0
        for pid in crew:
            prior = {g for g in appearances[pid] if seq[g] < seq[gid]}
            eras = {era_of(g) for g in prior}
            if not eras:
                new += 1
            for era in eras:
                counts[era] += 1
        out.append({
            "game_id": gid, "era": era_of(gid), "roster": len(crew),
            "from_bungie": counts["Bungie"],
            "from_343": counts["343 Industries"],
            "from_halo_studios": counts["Halo Studios"],
            "no_prior_halo": new,
            "first_party_only": first_party_only,
        })
    return out


def write_lineage(rows, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return path

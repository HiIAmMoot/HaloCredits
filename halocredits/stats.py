import csv
from collections import Counter, defaultdict
from pathlib import Path

from .identity import _is_compound_credit
from .studios import FIRST_PARTY, INDEPENDENT, classify_studio

# The four MCC entries are release tiers of one product, but they are not all
# adjacent in real chronology: Halo 5 (2015) shipped between the 2014 launch
# and the September 2018 update, and Halo Infinite (2021) shipped between the
# October 2021 update and the February 2025 update. Grouping across either of
# those would silently compare Halo 5/Infinite's continuity against the wrong
# neighbor -- exactly the bug this grouping is meant to avoid, just relocated.
# So only entries with NO other game released between them collapse together:
# 2014 stands alone (Halo 5 follows it directly), 2018+2021 collapse (nothing
# shipped between them), 2025 stands alone (Infinite precedes it directly).
# Headcount and contractor share stay per-entry regardless of grouping.
CONTINUITY_GROUPS = {
    "halo-mcc-2018": "mcc-2018-2021", "halo-mcc-2021": "mcc-2018-2021",
}


def group_of(game_id: str) -> str:
    return CONTINUITY_GROUPS.get(game_id, game_id)


def collapse_spine(games) -> list[str]:
    """The continuity sequence: games in order, MCC entries collapsed to one."""
    spine, seen = [], set()
    for game in sorted(games.values(), key=lambda g: g.sequence):
        key = group_of(game.game_id)
        if key not in seen:
            seen.add(key)
            spine.append(key)
    return spine


def _real_people(people) -> list:
    """Person objects that should count as a distinct individual in
    headcount/roster/flow statistics.

    resolve() deliberately keeps one Person per compound credit line (e.g.
    "composed by Marty O'Donnell and Michael Salvatori") even after
    correctly attributing that line's game to every real person named on it
    -- that phantom entry is what makes the merge inspectable in people.csv.
    But it is not a person: its display name IS the credit line, not a
    name. Counting it as well as the real people it names would double-count
    the same credit, so it is excluded here exactly when the compound-credit
    pass in resolve() found at least one real match for it -- i.e. some
    OTHER person's variants also contain this phantom's own display name.
    A compound-looking name resolve() could not match to anyone else (e.g.
    "James Cassidy & Barry Campbell", never otherwise credited by either
    name) has no real attribution to double-count against and stays
    counted, exactly as it was before this fix.
    """
    by_variant: dict[str, set] = defaultdict(set)
    for p in people.values():
        for v in p.variants:
            by_variant[v].add(p.person_id)
    return [p for p in people.values()
            if not (_is_compound_credit(p.display_name)
                   and len(by_variant[p.display_name]) > 1)]


def _vendor_pairs(rows, people, classes) -> set[tuple[str, str]]:
    """(game_id, person_id) pairs where that person has at least one row in
    that game naming a vendor studio.

    A row's `name_raw` can match more than one person's variant list -- a
    compound credit line like "composed by Marty O'Donnell and Michael
    Salvatori" is recorded, correctly, as a variant on BOTH composers'
    `Person` objects, and also names a third, phantom "person" whose own
    `name_raw` is that same line. Scoping each candidate match on `game_id in
    p.games` as well as the variant match resolves that ambiguity the same
    way the roster does: it attributes the vendor signal to every real person
    who could actually own it, and a match against the phantom is harmless,
    since the phantom is never in the roster (built from `_real_people`) to
    begin with -- its vendor status is never consulted.
    """
    by_variant: dict[str, list] = defaultdict(list)
    for p in _real_people(people):
        for v in p.variants:
            by_variant[v].append(p)

    pairs = set()
    for row in rows:
        cls = classify_studio(row["studio"], classes)
        if cls in ("", FIRST_PARTY, INDEPENDENT):
            continue
        gid = row["game_id"]
        for p in by_variant.get(row["name_raw"], ()):
            if gid in p.games:
                pairs.add((gid, p.person_id))
    return pairs


def _active_spine(games, roster) -> tuple[list[str], dict[str, int]]:
    """Spine positions used for continuity comparisons, with any group that
    has no credited person on any of its games excluded from the index --
    such a group (e.g. MCC's February 2025 update, credited only to
    community Reclaimers) is not a production and cannot break continuity
    for whoever comes next. The excluded group still gets its own row in
    per_game_stats' output; it is only removed from the position index used
    for gap detection, the same way MCC's release tiers share a position."""
    spine = collapse_spine(games)
    group_members = defaultdict(list)
    for game in games.values():
        group_members[group_of(game.game_id)].append(game.game_id)
    active = [key for key in spine if any(roster[gid] for gid in group_members[key])]
    return active, {key: i for i, key in enumerate(active)}


def per_game_stats(rows, people, games, classes) -> list[dict]:
    # Roster and per-person appearance history are read straight off
    # Person.games -- the one place resolve() already worked out, correctly,
    # every game a person was really credited on (compound lines included).
    # Re-deriving that from rows via a variant-string lookup is what caused
    # the bug this replaces: a shared variant string (the compound-credit
    # case) resolves to only one Person, silently dropping the others.
    roster = defaultdict(set)          # game_id -> person_ids
    for p in _real_people(people):
        for gid in p.games:
            roster[gid].add(p.person_id)

    _, position = _active_spine(games, roster)
    positions = defaultdict(set)       # person_id -> spine positions
    for p in _real_people(people):
        for gid in p.games:
            key = group_of(gid)
            if key in position:
                positions[p.person_id].add(position[key])

    vendor_pairs = _vendor_pairs(rows, people, classes)

    out = []
    for game in sorted(games.values(), key=lambda g: g.sequence):
        gid = game.game_id
        # None only when this game's own group is inactive (zero roster),
        # in which case `crew` is empty too and the loop below never
        # dereferences `here`.
        here = position.get(group_of(gid))
        crew = roster[gid]
        newcomers = returning = continuing = departures = contractors = 0
        for pid in crew:
            seen = positions[pid]
            earlier = {p for p in seen if p < here}
            later = {p for p in seen if p > here}
            if not earlier:
                newcomers += 1
            elif max(earlier) < here - 1:
                returning += 1
            else:
                continuing += 1
            if not later:
                departures += 1
            if (gid, pid) in vendor_pairs:
                contractors += 1
        out.append({
            "game_id": gid, "year": game.year, "sequence": game.sequence,
            "headcount": len(crew), "newcomers": newcomers,
            "returning": returning, "continuing_from_previous": continuing,
            "departures": departures, "contractors": contractors,
        })
    return out


def write_per_game(stats, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(stats[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(stats)
    return path


def flows(rows, people, games) -> list[dict]:
    """One row per (earlier position -> next position they appear in).

    Edges connect a person's consecutive spine positions, not every pair, so a
    person credited on three games contributes two edges rather than three.

    `rows` is accepted for interface parity with the other statistics
    functions but unused: each person's position sequence is read directly
    off `Person.games`, the authoritative record resolve() already built,
    rather than re-derived from rows via an ambiguous variant-string lookup
    (see `_vendor_pairs` for why that lookup is ambiguous).
    """
    roster = defaultdict(set)
    for p in _real_people(people):
        for gid in p.games:
            roster[gid].add(p.person_id)
    active_spine, position = _active_spine(games, roster)

    seen = defaultdict(set)
    for p in _real_people(people):
        for gid in p.games:
            key = group_of(gid)
            if key in position:
                seen[p.person_id].add(position[key])

    counts = Counter()
    for positions in seen.values():
        ordered = sorted(positions)
        for a, b in zip(ordered, ordered[1:]):
            counts[(active_spine[a], active_spine[b])] += 1

    return [{"from_game": a, "to_game": b, "count": n}
            for (a, b), n in sorted(counts.items())]


def write_flows(rows, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["from_game", "to_game", "count"],
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return path

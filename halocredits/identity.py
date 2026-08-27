import csv
import glob
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .config import GameConfig

# Typographic apostrophes, straight apostrophes and their absence are all the
# same letter to a human: the corpus writes Frank O'Connor three ways.
_PUNCT = re.compile(r"[^\w ]", re.UNICODE)


def normalise_name(name: str) -> str:
    """Case-fold and strip punctuation for MATCHING ONLY.

    Never written back to a credit row -- `name_raw` keeps the credited
    spelling verbatim, which is what makes a merge inspectable afterwards.
    """
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _PUNCT.sub("", text).lower()
    return re.sub(r"\s+", " ", text).strip()


# Gap, not span. A 25-year career with no gap over a decade is a career; a
# 25-year gap with nothing between is where "returning veteran" and "different
# person, same name" become indistinguishable from this data alone. Named
# constant because the threshold is a judgement, not a fact.
UNCERTAIN_GAP_YEARS = 10

REVIEW_SAME = "same"
REVIEW_SPLIT = "split"


class PersonIdCollisionError(Exception):
    """Two distinct merge keys minted the same person_id.

    A hand-authored alias person_id or an auto-generated slug landed on the
    same string as some other, unrelated person's id. Silently overwriting
    one of them in the returned dict would make a whole person vanish with
    no error and no trace -- failing loudly is the only safe response.
    """


def _is_compound_credit(raw: str) -> bool:
    """True for a credit LINE naming more than one entity, e.g.
    'The Bungie Auxiliary Players and Brian Morden' or 'composed by Marty
    O'Donnell and Michael Salvatori'.

    A `name_canonical` on a compound line points at only one of the named
    entities. Trusting that link uncritically silently drops whoever else is
    named on the line and misattributes the whole row to whichever one the
    wiki link happens to name. resolve() refuses the link for these lines and
    instead matches each already-known person's exact name inside the line
    (see the compound-credit pass in `resolve`), so nobody named on the line
    loses the credit and nobody not named on it gains one.
    """
    lowered = raw.lower()
    return " and " in lowered or "&" in raw or lowered.startswith("composed by")


@dataclass
class Person:
    person_id: str
    display_name: str
    variants: list[str] = field(default_factory=list)
    games: list[str] = field(default_factory=list)
    first_game: str = ""
    last_game: str = ""
    game_count: int = 0
    span_years: int = 0
    largest_gap_years: int = 0
    uncertain: bool = False


def load_aliases(path: Path) -> dict[str, str]:
    """name_variant -> person_id. Hand-edited; wins over every automatic step."""
    if not Path(path).exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["name_variant"]: r["person_id"] for r in csv.DictReader(fh)}


def load_reviews(path: Path) -> dict[str, str]:
    """person_id -> "same" | "split". Human rulings on flagged people.

    This is the one file in the pipeline a human types into directly, so the
    ruling is case-folded ("Same" and "SPLIT" both work) and validated: a
    non-empty value that isn't "same"/"split" after folding is a typo that
    would otherwise leave that person silently stuck `uncertain=True`
    forever, with no error or warning anywhere downstream. Raise immediately
    instead so the mistake is found right away.
    """
    if not Path(path).exists():
        return {}
    out: dict[str, str] = {}
    bad: list[tuple[str, str]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            raw = r["ruling"].strip()
            if not raw:
                continue
            ruling = raw.lower()
            if ruling not in (REVIEW_SAME, REVIEW_SPLIT):
                bad.append((r["person_id"], raw))
                continue
            out[r["person_id"]] = ruling
    if bad:
        detail = ", ".join(f"{pid!r}: {raw!r}" for pid, raw in bad)
        raise ValueError(
            f"{path}: unrecognised ruling value(s) -- expected 'same' or "
            f"'split' (case-insensitive): {detail}"
        )
    return out


def write_uncertain_review(people: dict[str, Person], path: Path) -> int:
    """Write every flagged person with enough context to judge them without
    opening a source. Returns the number written."""
    flagged = sorted((p for p in people.values() if p.uncertain),
                     key=lambda p: -p.largest_gap_years)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["person_id", "name", "games", "years",
                    "largest_gap_years", "ruling"])
        for p in flagged:
            w.writerow([p.person_id, p.display_name, "|".join(p.games),
                        p.span_years, p.largest_gap_years, ""])
    return len(flagged)


def load_credit_rows(credits_dir: Path, inclusion=("core",)) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(str(Path(credits_dir) / "*.csv"))):
        with open(path, newline="", encoding="utf-8") as fh:
            rows.extend(r for r in csv.DictReader(fh)
                        if r["inclusion_class"] in inclusion)
    return rows


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalise_name(name)).strip("-") or "unknown"


def resolve(rows, games: dict[str, GameConfig], aliases, reviews) -> dict[str, Person]:
    """Group credit rows into people.

    Order matters: each step only merges what the previous one left apart.
      1. exact name_raw
      2. name_canonical where present (the wiki-link target, authoritative)
      3. normalised name (case / punctuation / apostrophe style)
      4. aliases.csv, which overrides all of the above

    Two refinements on top of that:

    - A `name_raw` string's canonical is resolved from ALL of its
      occurrences, not just the first one `load_credit_rows` happens to
      yield. `load_credit_rows` globs files alphabetically, which is not
      narrative order (`halo-3-odst.csv` sorts before `halo-3.csv`), so a
      first-wins rule would let a canonical-less row lock a merge key before
      a later row for the same raw string supplies the real canonical link.
    - `name_canonical` is refused for compound credit lines that name more
      than one entity (see `_is_compound_credit`) -- such a line is kept
      standalone rather than folding its whole credit into whichever one
      entity the wiki link happens to name, and a separate pass below
      attributes its game to every already-known person actually named on
      the line by exact substring match.
    """
    # Step 2: aggregate name_canonical across every occurrence of a raw
    # string before deciding merge keys.
    raw_canonical: dict[str, str] = {}
    for row in rows:
        raw = row["name_raw"]
        target = row.get("name_canonical")
        if target and raw not in raw_canonical and not _is_compound_credit(raw):
            raw_canonical[raw] = target

    key_of: dict[str, str] = {}      # name_raw -> merge key
    canonical: dict[str, str] = {}   # merge key -> preferred display name
    for raw, target in raw_canonical.items():
        norm = normalise_name(target)
        key_of[raw] = norm
        canonical[norm] = target

    # Step 3: everything without a (trusted) canonical falls back to its own
    # normalised form.
    for row in rows:
        key_of.setdefault(row["name_raw"], normalise_name(row["name_raw"]))

    # Step 4: hand-edited overrides replace whatever the automation decided.
    for variant, person_id in aliases.items():
        key_of[variant] = f"alias:{person_id}"

    def _person_id(key: str) -> str:
        return key.split("alias:")[-1] if key.startswith("alias:") else _slug(key)

    # A "split" ruling means one name is two people. Give each game its own
    # key so they never merge, suffixed by the game so the ids are stable.
    #
    # The check must be against the person's actual resolved person_id (what
    # a human sees in review/uncertain.csv and writes back into
    # identity-review.csv) -- not _slug(key). An alias-derived key is
    # "alias:<person_id>", and _slug of that string is NOT the person_id
    # (it's "alias-<person_id>-ish"), so a naive _slug(key) check silently
    # never matches an alias-derived split ruling. _person_id(key) is the
    # same function that assigns every other person's id, so this reuses it
    # instead of re-deriving a second, inconsistent notion of "the id".
    split_ids = {pid for pid, ruling in reviews.items() if ruling == REVIEW_SPLIT}
    split_person_ids: set[str] = set()
    if split_ids:
        for row in rows:
            key = key_of[row["name_raw"]]
            if _person_id(key) in split_ids:
                new_key = f"{key}#{row['game_id']}"
                key_of[row["name_raw"] + "\x00" + row["game_id"]] = new_key
                split_person_ids.add(_person_id(new_key))

    grouped: dict[str, Person] = {}       # person_id -> Person
    seen_games: dict[str, set[str]] = {}  # person_id -> games
    key_to_id: dict[str, str] = {}
    compound_rows = []

    for row in rows:
        raw = row["name_raw"]
        key = key_of.get(raw + "\x00" + row["game_id"], key_of[raw])
        person_id = key_to_id.get(key)
        if person_id is None:
            person_id = _person_id(key)
            if person_id in grouped:
                raise PersonIdCollisionError(
                    f"person_id {person_id!r} already claimed by "
                    f"{grouped[person_id].variants!r}; cannot also claim {raw!r}"
                )
            key_to_id[key] = person_id
            grouped[person_id] = Person(person_id=person_id, display_name=canonical.get(key, raw))
            seen_games[person_id] = set()
        person = grouped[person_id]
        if raw not in person.variants:
            person.variants.append(raw)
        seen_games[person_id].add(row["game_id"])
        if _is_compound_credit(raw):
            compound_rows.append(row)

    # Compound-credit pass: attribute the row's game to every already-known
    # person whose display name or a recorded variant appears verbatim, as a
    # whole word, inside the line. Exact substring match only -- no fuzzy
    # matching, no new judgement call, just a name that already appears
    # character-for-character elsewhere in the corpus.
    #
    # Split-affected people are excluded from the index entirely. Splitting
    # exists because the data cannot tell the two halves apart from name
    # alone; both halves share the exact same display name / variant text
    # (that's the whole reason they were one merge key before the ruling).
    # If they stayed in the index, a compound line naming that shared text
    # would match every split half and silently fabricate the same game
    # credit on all of them -- with no error, since nothing about that looks
    # like a collision. There is no way to tell which half a compound line
    # actually means, so neither is auto-credited; a split half only ever
    # carries the games from its own direct rows.
    known: dict[str, list[str]] = {}  # exact name -> [person_id, ...]
    for person_id, person in grouped.items():
        if person_id in split_person_ids:
            continue
        for name in {person.display_name, *person.variants}:
            if name and not _is_compound_credit(name):
                known.setdefault(name, []).append(person_id)

    for row in compound_rows:
        raw = row["name_raw"]
        own_id = key_to_id[key_of[raw]]
        for name, ids in known.items():
            if re.search(r"\b" + re.escape(name) + r"\b", raw):
                for pid in ids:
                    if pid == own_id:
                        continue
                    person = grouped[pid]
                    if raw not in person.variants:
                        person.variants.append(raw)
                    seen_games[pid].add(row["game_id"])

    for person_id, person in grouped.items():
        ordered = sorted(seen_games[person_id], key=lambda g: games[g].sequence)
        person.games = ordered
        person.first_game, person.last_game = ordered[0], ordered[-1]
        person.game_count = len(ordered)

        years = [games[g].year for g in ordered]
        person.span_years = years[-1] - years[0]
        person.largest_gap_years = max(
            (b - a for a, b in zip(years, years[1:])), default=0)
        person.uncertain = person.largest_gap_years > UNCERTAIN_GAP_YEARS

        ruling = reviews.get(person.person_id, "")
        if ruling == REVIEW_SAME:
            person.uncertain = False

    return grouped

"""Curated, one-time credit additions sourced from MobyGames.

Unlike the other parsers, MobyGames data cannot be safely auto-merged on
every parse: reconciling it against the existing corpus requires per-name
human judgement (spelling-variant duplicates, false-positive fuzzy matches,
same-source-proves-different-people checks) that a fresh re-scrape can't
reproduce automatically. So this isn't a live parser wired into
`config/sources.csv` -- it's a static, reviewed snapshot of exactly the rows
that were approved, replayed on every `parse`/`all` run so the committed
CSVs stay reproducible (see `tests/test_integration.py`'s golden-file check)
without ever re-running the fuzzy matcher against unreviewed new scrapes.

`config/mobygames-additions/<game_id>.csv` holds one CSV per game, same
columns as the main credit CSVs minus `game_id` and `credit_order` (both are
assigned when the rows are appended, so the additions file doesn't need to
know where in the primary source's ordering it will land).
"""
import csv
from pathlib import Path

from .models import CreditRow, InclusionClass, ParseResult

_FIELDS = ["name_raw", "name_canonical", "category", "role_raw",
           "character", "studio", "inclusion_class", "source_ref"]


def load_mobygames_additions(path: Path) -> dict[str, list[dict]]:
    """game_id -> list of row dicts, one file per game in the directory."""
    path = Path(path)
    if not path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    for csv_path in sorted(path.glob("*.csv")):
        game_id = csv_path.stem
        with open(csv_path, newline="", encoding="utf-8") as fh:
            out[game_id] = list(csv.DictReader(fh))
    return out


def apply_mobygames_additions(result: ParseResult, additions: dict[str, list[dict]]) -> int:
    """Append this game's curated rows to `result.rows` in place.

    Credit order continues from whatever the primary source's parse ended
    on, so the additions always sort after the primary source's own rows
    regardless of how many rows that source produces.
    """
    rows = additions.get(result.game_id)
    if not rows:
        return 0
    next_order = max((r.credit_order for r in result.rows), default=-1) + 1
    for row in rows:
        result.add(CreditRow(
            game_id=result.game_id,
            credit_order=next_order,
            name_raw=row["name_raw"],
            name_canonical=row["name_canonical"],
            category=row["category"],
            role_raw=row["role_raw"],
            character=row["character"],
            studio=row["studio"],
            inclusion_class=InclusionClass(row["inclusion_class"]),
            source_ref=row["source_ref"],
        ))
        next_order += 1
    return len(rows)

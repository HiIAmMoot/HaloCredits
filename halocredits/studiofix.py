"""Corrections to the `studio` field for rows where it holds something other
than the vendor that actually credited the person.

Unlike `namefix.py`, these are not human judgment calls flagged for review --
each one is confirmed against the raw source HTML: either a lone typo among
many correctly-spelled occurrences of the same agency on the same page, or a
`credits_entry_agency` span whose text is a nickname or first name rather than
a company (Halo Campaign Evolved's Digic VFX team: the agency field there
holds each person's preferred name -- "Tom", "CJ", "Zork" -- while their
`source_ref` confirms every one of them sits under Digic's own credit block).
So this lives in `config/`, applied unconditionally, not `review/`.

Scoped by (name_raw, game_id): the same name can be credited correctly on one
game and wrongly on another, and a blanket name-only rule would overcorrect.
"""
import csv
from dataclasses import replace
from pathlib import Path


class StudioFixError(ValueError):
    pass


def load_studio_fixes(path: Path) -> dict[tuple[str, str], tuple[str, str]]:
    """(name_raw, game_id) -> (wrong_studio, correct_studio). Missing file means none."""
    path = Path(path)
    if not path.exists():
        return {}
    out: dict[tuple[str, str], tuple[str, str]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for line, row in enumerate(csv.DictReader(fh), start=2):
            name = (row.get("name_raw") or "").strip()
            gid = (row.get("game_id") or "").strip()
            wrong = (row.get("wrong_studio") or "").strip()
            correct = (row.get("correct_studio") or "").strip()
            if not name or not gid:
                continue
            if not wrong or not correct:
                raise StudioFixError(f"{path}:{line}: needs both wrong_studio and correct_studio")
            key = (name, gid)
            if key in out:
                raise StudioFixError(f"{path}:{line}: duplicate entry for {key!r}")
            out[key] = (wrong, correct)
    return out


def apply_studio_fixes(result, fixes) -> int:
    """Rewrite ``result.rows`` in place. Returns how many rows changed.

    Scoped on the row's CURRENT studio value matching `wrong_studio`, not just
    the (name, game_id) key: if the source is re-fetched and the typo or
    mislabeled agency is no longer there, this is a silent no-op rather than
    overwriting a value the fix was never meant to touch.
    """
    if not fixes:
        return 0
    changed = 0
    for i, row in enumerate(result.rows):
        entry = fixes.get((row.name_raw, row.game_id))
        if entry is None:
            continue
        wrong, correct = entry
        if row.studio != wrong:
            continue
        result.rows[i] = replace(row, studio=correct)
        changed += 1
    return changed

"""Hand-ruled corrections for credit lines that are not a person's name.

`review/non-persons.csv` flags suspicious entries (very long strings, org
suffixes, connective words, place names) for a human to rule on. The rulings
land in `config/name-fixes.csv` as one of:

    discard  the line is not a person at all -- a studio, a location, a job
             title, a fragment of prose. Drop the row.
    fix      a real name is buried in the line. Replace the row with one row
             per extracted name, optionally overriding `studio` when the line
             also names the company the person appears courtesy of.
    keep     nothing wrong; a real person whose name merely trips a heuristic
             (Matthew London, Sofia Guix, credential suffixes like MPSE).
             Keep is the default, so those get no row in the config at all.

Applied to parser output before the credits CSVs are written, so every
downstream stage sees corrected data and none of them need to know this
step exists.
"""
import csv
from dataclasses import replace
from pathlib import Path

DISCARD = "discard"
FIX = "fix"


class NameFixError(ValueError):
    pass


def load_name_fixes(path: Path) -> dict[str, tuple[str, list[str], str]]:
    """name_raw -> (action, names, studio). Missing file means no fixes."""
    path = Path(path)
    if not path.exists():
        return {}
    out: dict[str, tuple[str, list[str], str]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for line, row in enumerate(csv.DictReader(fh), start=2):
            raw = (row.get("name_raw") or "").strip()
            action = (row.get("action") or "").strip().lower()
            if not raw:
                continue
            if action not in (DISCARD, FIX):
                raise NameFixError(
                    f"{path}:{line}: action must be '{DISCARD}' or '{FIX}', got {action!r}")
            names = [n.strip() for n in (row.get("names") or "").split("|") if n.strip()]
            if action == FIX and not names:
                raise NameFixError(f"{path}:{line}: action 'fix' needs at least one name")
            if raw in out:
                raise NameFixError(f"{path}:{line}: duplicate entry for {raw!r}")

            # `studio` is per-name when it is pipe-separated, because only one
            # of the people on a line is usually the one the company belongs
            # to: "Kiera Schroeder (24 Seven Topco) Sarah Emerson" credits the
            # agency to Kiera alone. A single bare value applies to every name.
            #   ""   keep whatever the parser found on the row
            #   "-"  clear it; the parser mistook something else for a vendor
            raw_studio = (row.get("studio") or "").strip()
            studios = ([s.strip() for s in raw_studio.split("|")]
                       if "|" in raw_studio else [raw_studio] * len(names))
            if action == FIX and len(studios) != len(names):
                raise NameFixError(
                    f"{path}:{line}: {len(names)} names but {len(studios)} studios")
            out[raw] = (action, names, studios)
    return out


def apply_name_fixes(result, fixes) -> tuple[int, int]:
    """Rewrite ``result.rows`` in place. Returns (discarded, extracted).

    A fixed line expands to one row per extracted name. `credit_order` is not
    renumbered: it records where the credit sat in the source, and two people
    named on the same line genuinely do share that position.
    """
    if not fixes:
        return 0, 0
    kept, discarded, extracted = [], 0, 0
    for row in result.rows:
        entry = fixes.get(row.name_raw)
        if entry is None:
            kept.append(row)
            continue
        action, names, studios = entry
        if action == DISCARD:
            result.drop(row.name_raw, "ruled-not-a-person")
            discarded += 1
            continue
        for name, studio in zip(names, studios):
            kept.append(replace(
                row,
                name_raw=name,
                # The old canonical pointed at the whole bad string, so it
                # would drag every extracted name back onto one identity.
                name_canonical="",
                studio="" if studio == "-" else (studio or row.studio),
            ))
            extracted += 1
    result.rows[:] = kept
    return discarded, extracted

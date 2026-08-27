"""Hand-ruled corrections to a credit row's `inclusion_class`.

`inclusion_class` is otherwise decided by the section a name sits under and by
keywords in its role text. That is right almost everywhere, but it misfires
when a lone studio role happens to contain a publishing word: Halo CE's
"Localization Lead" and Halo 3's "Bungie Marketing/PR/Community Lead" are
both Bungie staff sitting in Bungie sections, and both were being filed as
publisher staff on the strength of one word.

Rulings land in `config/inclusion-overrides.csv` as
`game_id,name_raw,inclusion_class,reason`, applied to parser output before
anything is written, so every stage downstream sees the corrected class. The
`reason` column is required: an override is a claim about the source, and the
next person to read it needs to know what the source actually says.
"""
import csv
from dataclasses import replace
from pathlib import Path

from .models import InclusionClass


class InclusionOverrideError(ValueError):
    pass


def load_inclusion_overrides(path: Path) -> dict[tuple[str, str], InclusionClass]:
    """(game_id, name_raw) -> InclusionClass. Missing file means no overrides."""
    path = Path(path)
    if not path.exists():
        return {}
    out = {}
    valid = {c.value for c in InclusionClass}
    with open(path, newline="", encoding="utf-8") as fh:
        for line, row in enumerate(csv.DictReader(fh), start=2):
            game_id = (row.get("game_id") or "").strip()
            name = (row.get("name_raw") or "").strip()
            cls = (row.get("inclusion_class") or "").strip()
            if not game_id or not name:
                continue
            if cls not in valid:
                raise InclusionOverrideError(
                    f"{path}:{line}: inclusion_class must be one of "
                    f"{sorted(valid)}, got {cls!r}")
            if not (row.get("reason") or "").strip():
                raise InclusionOverrideError(
                    f"{path}:{line}: an override needs a reason")
            out[(game_id, name)] = InclusionClass(cls)
    return out


def apply_inclusion_overrides(result, overrides) -> int:
    """Rewrite ``result.rows`` in place. Returns the number of rows changed."""
    if not overrides:
        return 0
    changed = 0
    for i, row in enumerate(result.rows):
        want = overrides.get((result.game_id, row.name_raw))
        if want is not None and row.inclusion_class != want:
            result.rows[i] = replace(row, inclusion_class=want)
            changed += 1
    return changed

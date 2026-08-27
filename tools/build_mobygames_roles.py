"""Index the explicit per-person role MobyGames prints for every credit.

MobyGames states a role beside each name -- "Jason Jones / Project Lead",
"Chris Matthews / Studio Art Director" -- for every game it covers. The wiki
rolls often do not: they group people under a heading and list bare names, or
put a staffing agency where the job should be. So where a row's own source
says nothing about the work, the same person's MobyGames entry for the same
game frequently does.

This indexes (game_id, name) -> role text so halocredits.roles can consult
it. Matching is by name within one game, which is a strong key: two different
people with the same name on the same title is rare, and the alternative is
leaving thousands of credits uncoloured.

Output is data/mobygames-roles.csv, committed, so classification remains a
function of committed data rather than re-parsing HTML on every run.

    python tools/build_mobygames_roles.py
"""
from __future__ import annotations

import csv
import html
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "mobygames-roles.csv"

# MobyGames page stem -> the game_id it belongs to. Infinite is split across
# two pages and Campaign Evolved is filed under an abbreviation.
STEM_GAME = {
    "halo-cev": "halo-campaign-evolved",
    "halo-infinite-campaign": "halo-infinite",
    "halo-infinite-multiplayer": "halo-infinite",
}

RE_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
RE_ROLE = re.compile(r'class="text-right"[^>]*>(.*?)</td>', re.S)
RE_PERSON = re.compile(r'/person/\d+/[^"]*"[^>]*>([^<]+)</a>')


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", text))).strip()


def roles_in(path: Path) -> list[tuple[str, str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    out = []
    for row in RE_ROW.findall(raw):
        m = RE_ROLE.search(row)
        role = _clean(m.group(1)) if m else ""
        if not role:
            continue
        for name in RE_PERSON.findall(row):
            out.append((_clean(name), role))
    return out


def main() -> int:
    found: dict[tuple[str, str], list[str]] = defaultdict(list)
    for path in sorted((ROOT / "raw" / "mobygames").glob("*.html")):
        game = STEM_GAME.get(path.stem, path.stem)
        pairs = roles_in(path)
        for name, role in pairs:
            if role not in found[(game, name)]:
                found[(game, name)].append(role)
        print(f"  {path.stem:28} -> {game:24} {len(pairs):5} pairs")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["game_id", "name", "roles"])
        for (game, name), roles in sorted(found.items()):
            w.writerow([game, name, " | ".join(roles)])
    print(f"\nwrote {OUT}  ({len(found)} person-game entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

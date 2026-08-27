"""Recover the department tags that were stripped off credited names.

Several rolls annotate a person with their department in brackets rather than
in the role column: Halo 4 credits "Aaron Nicholls (Engineering)", "Seth
Gibson (Tech Art)", "Alicia Brattin (Business)". config/name-fixes.csv
removes those brackets so the name resolves to one person -- correctly -- but
the tag itself was discarded with them, and it is the single most reliable
role signal in the corpus: the credit states it about that individual, not
about the block they sit in.

Most bracketed text in the raw sources is a VENDOR, not a role -- Aquent,
Volt, Insight Global, TEKSYSTEMS -- and that is already handled by the
inline_vendor machinery, which turns it into the `studio` column. This tool
only takes tags that name work.

Output is data/name-role-tags.csv, (name, tag). The tag is matched against
the same patterns as headings, so there is one rule set rather than two.

    python tools/build_name_tags.py
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "name-role-tags.csv"

RE_TAG = re.compile(r"\(([^)]{2,30})\)")

# Tags that name a vendor, a nickname, or a disambiguator rather than work.
# "(I)" distinguishes two people of the same name; "(Tom)" is a preferred
# name; the rest are companies.
NOT_WORK = {
    "i", "ii", "iii", "tom", "nikki", "renee", "vicky", "fidde", "sparth",
    "robogabo", "24 seven topco", "volt", "experis", "aquent", "excell",
    "ccpa", "en", "uncredited", "in alphabetical order",
}


def is_work(tag: str) -> bool:
    t = tag.strip().lower()
    if not t or t in NOT_WORK or t.isdigit():
        return False
    # a company suffix means it is an agency, not a department
    if re.search(r"\b(llc|inc|ltd|corp|gmbh|group|services|staffing)\b", t):
        return False
    return True


def main() -> int:
    fixes = ROOT / "config" / "name-fixes.csv"
    found: dict[str, str] = {}
    for row in csv.DictReader(open(fixes, newline="", encoding="utf-8")):
        tags = [t for t in RE_TAG.findall(row["name_raw"]) if is_work(t)]
        if not tags:
            continue
        names = [n.strip() for n in (row.get("names") or "").split("|") if n.strip()]
        if len(names) != 1:
            # a split row: which tag belongs to which name is not recorded,
            # so it is left alone rather than guessed at
            continue
        found.setdefault(names[0], tags[0].strip())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["name", "tag"])
        w.writerows(sorted(found.items()))
    print(f"wrote {OUT}  ({len(found)} names)")
    for name, tag in sorted(found.items())[:12]:
        print(f"    {name:28} ({tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Recover the credit block each row sat under, for sources whose references
do not record it.

Waypoint rows carry their heading path in `source_ref` already
("Digic/MoCap#1204"), so they need nothing. The other two sources do not:

    halopedia   source_ref is a line number, "L395". The wikitext above it
                holds a heading STACK -- "===Audio===" then
                "====[[Pyramind Studios]]====" -- and only the outer level
                names a discipline, so the whole stack is kept, not the
                nearest heading.
    mobygames   source_ref is a row index, "mobygames:tr88". Each <tr> sits
                under an <h4> such as "Halo 2A: Audio - Finishing Move Inc."

Output is data/source-headings.csv, (game_id, source_ref, heading). It is
generated, committed, and read by halocredits.roles, so classification stays
a pure function of committed data rather than re-scraping raw HTML on every
run.

    python tools/build_heading_index.py
"""
from __future__ import annotations

import csv
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "source-headings.csv"

RE_WIKI_HEAD = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
RE_LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
RE_TR = re.compile(r"<tr\b", re.I)
RE_H = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.I | re.S)


def _clean(text: str) -> str:
    text = RE_LINK.sub(r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", text).strip()


def halopedia_headings(path: Path) -> dict[str, str]:
    """L<line> -> the full heading stack above that line."""
    out: dict[str, str] = {}
    stack: dict[int, str] = {}
    for n, line in enumerate(path.read_text(encoding="utf-8",
                                            errors="replace").splitlines(), 1):
        m = RE_WIKI_HEAD.match(line)
        if m:
            level = len(m.group(1))
            stack = {k: v for k, v in stack.items() if k < level}
            stack[level] = _clean(m.group(2))
            continue
        if stack:
            out[f"L{n}"] = " / ".join(stack[k] for k in sorted(stack))
    return out


def mobygames_headings(path: Path) -> dict[str, str]:
    """mobygames:tr<n> -> the <h*> heading the row sits under."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    heads = [(m.start(), _clean(m.group(2))) for m in RE_H.finditer(raw)]
    out: dict[str, str] = {}
    for i, m in enumerate(RE_TR.finditer(raw)):
        pos = m.start()
        current = ""
        for hpos, htext in heads:
            if hpos < pos:
                current = htext
            else:
                break
        if current:
            out[f"mobygames:tr{i}"] = current
    return out


def main() -> int:
    rows = []
    for path in sorted((ROOT / "raw" / "halopedia").glob("*.wikitext")):
        found = halopedia_headings(path)
        rows += [(path.stem, ref, head) for ref, head in found.items()]
        print(f"  halopedia {path.stem:24} {len(found):5} line refs")
    for path in sorted((ROOT / "raw" / "mobygames").glob("*.html")):
        found = mobygames_headings(path)
        rows += [(path.stem, ref, head) for ref, head in found.items()]
        print(f"  mobygames {path.stem:24} {len(found):5} row refs")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["game_id", "source_ref", "heading"])
        w.writerows(sorted(rows))
    print(f"\nwrote {OUT}  ({len(rows)} refs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

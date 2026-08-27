import csv
import re
from pathlib import Path

VENDOR = "vendor"
FIRST_PARTY = "first-party"
INDEPENDENT = "independent"

# Corporate suffixes carry no identity: "Sperasoft, Inc." and "Sperasoft" are
# one company, and the corpus writes both.
_SUFFIX = re.compile(r"[,\s]+(inc|llc|ltd|limited|corp|corporation|co|gmbh|srl|s\.r\.l|plc)\.?$",
                     re.IGNORECASE)


def normalise_studio(name: str) -> str:
    """Case-fold and strip punctuation and corporate suffixes for lookup only.

    Never used to rewrite the `studio` column -- that stays verbatim, since
    the source's own spelling is part of the record.
    """
    text = re.sub(r"\s+", " ", (name or "").strip()).lower()
    prev = None
    while text != prev:
        prev = text
        text = _SUFFIX.sub("", text).strip(" .,")
    return text


def load_studio_classes(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[normalise_studio(row["studio"])] = row["class"].strip()
    return out


def classify_studio(name: str, classes: dict[str, str]) -> str:
    """Blank studio means first-party by absence and returns "".

    Anything not listed defaults to VENDOR: an unrecognised company on a
    credits page is far more likely to be an outsourcer than an Xbox studio.
    Callers log the unknowns so a new vendor is visible rather than absorbed.
    """
    key = normalise_studio(name)
    if not key:
        return ""
    return classes.get(key, VENDOR)

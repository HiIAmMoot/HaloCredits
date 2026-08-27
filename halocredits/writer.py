import csv
from pathlib import Path

from .models import CSV_COLUMNS, ParseResult


def write_credits(result: ParseResult, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.game_id}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in result.rows:
            writer.writerow(row.to_dict())
    return path

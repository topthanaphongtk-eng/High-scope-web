"""Export a local SQLite captures DB to CSV for review / PostgreSQL import.

Legacy helper for stations that ran the old SQLite-backed build. The CSVs
can be loaded into the central PostgreSQL with `\\copy` (see db/README.md).

Writes two files into ./db/exports/ :
    captures.csv
    capture_files.csv

Usage:
    python tools/export_to_csv.py                              # default DB
    python tools/export_to_csv.py --db ./logs/captures.db --out ./db/exports
    python tools/export_to_csv.py --since 2026-01-01

CSV format:
    UTF-8 with BOM (so Excel reads Thai/µ correctly)
    Headers in row 1; same column order as schema_postgres.sql expects
    NULLs encoded as empty string
    Datetimes in ISO 8601
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Column order intentionally matches schema_postgres.sql so a `\copy`
# import lines up without manual re-mapping.
CAPTURES_COLS = [
    "capture_id", "confirmed_at", "lot_id", "bonding_number",
    "lot_location", "mpc", "package", "qs",
    "operator_badge", "hostname", "app_version",
    "mode", "raw_lot_info",
]
CAPTURE_FILES_COLS = [
    "id", "capture_id", "slot",
    "fused_path", "fused_name",
    "size_bytes", "sha256",
]


def export_table(
    con: sqlite3.Connection, table: str, columns: list[str],
    out_path: Path, since: str | None = None,
    since_col: str | None = "confirmed_at",
) -> int:
    where = ""
    params: tuple = ()
    if since is not None and since_col is not None:
        where = f"WHERE {since_col} >= ?"
        params = (since,)
    order = f"ORDER BY {since_col}" if since_col else ""
    cur = con.execute(
        f"SELECT {', '.join(columns)} FROM {table} {where} {order}",
        params,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(columns)
        for row in cur:
            w.writerow(["" if v is None else v for v in row])
            n += 1
    print(f"  -> {out_path.name}: {n} row(s)")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db", default=str(ROOT / "logs" / "captures.db"),
        help="path to source SQLite DB",
    )
    ap.add_argument(
        "--out", default=str(ROOT / "db" / "exports"),
        help="output directory for CSV files",
    )
    ap.add_argument(
        "--since", default=None,
        help="ISO date / datetime — only rows confirmed at or after",
    )
    args = ap.parse_args()

    src = Path(args.db).resolve()
    if not src.exists():
        print(f"DB not found: {src}", file=sys.stderr)
        return 2
    out_dir = Path(args.out).resolve()

    print(f"Source DB: {src}")
    print(f"Output:    {out_dir}")
    if args.since:
        print(f"Filter:    confirmed_at >= {args.since}")
    print()

    con = sqlite3.connect(str(src))
    try:
        export_table(
            con, "captures", CAPTURES_COLS,
            out_dir / "captures.csv", args.since,
        )
        # capture_files has no confirmed_at — order by id only.
        export_table(
            con, "capture_files", CAPTURE_FILES_COLS,
            out_dir / "capture_files.csv", since=None, since_col="id",
        )
    finally:
        con.close()

    (out_dir / "README.txt").write_text(
        f"CSV export from {src.name}\n"
        f"Generated: {datetime.now().isoformat()}\n"
        f"Schema:    db/schema_postgres.sql (column order matches)\n"
        f"Encoding:  UTF-8 with BOM\n"
        f"Nulls:     empty cell\n",
        encoding="utf-8",
    )
    print(f"\nDone. See {out_dir}/README.txt for details.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

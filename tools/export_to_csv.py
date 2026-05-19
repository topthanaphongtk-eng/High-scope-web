"""Export the local SQLite DB to CSV for review / SQL Server import.

Writes two files into ./db/exports/ :
    lot_sessions.csv
    measurements.csv

Usage:
    python tools/export_to_csv.py                          # default DB
    python tools/export_to_csv.py --db ./logs/measurements.db --out ./db/exports
    python tools/export_to_csv.py --since 2026-01-01

CSV format:
    UTF-8 with BOM (so Excel + SSMS Import Wizard read Thai/µ correctly)
    Headers in row 1; same column order as schema_mssql.sql expects
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

# Column order intentionally matches schema_mssql.sql so an SSMS Import
# Wizard / BULK INSERT lines up without manual re-mapping.
LOT_SESSIONS_COLS = [
    "session_id", "confirmed_at", "lot_id", "bonding_number",
    "lot_location", "mpc", "package", "qs",
    "operator_badge", "hostname", "app_version",
    "n_locations", "n_pads", "raw_lot_info",
]
MEASUREMENTS_COLS = [
    "id", "session_id", "confirmed_at",
    "lot_id", "bonding_number", "lot_location",
    "mpc", "package", "qs", "operator_badge",
    "location", "pad_index",
    "pad_w_um", "pad_h_um", "ball_d_um",
    "gap_min_um", "gap_mean_um",
    "confidence", "pixel_size_um",
    "source_ball_path", "source_pad_path",
    "stored_ball_path", "stored_pad_path",
    "extra_json",
]


def export_table(
    con: sqlite3.Connection, table: str, columns: list[str],
    out_path: Path, since: str | None = None,
) -> int:
    where = ""
    params: tuple = ()
    if since is not None:
        where = "WHERE confirmed_at >= ?"
        params = (since,)
    cur = con.execute(
        f"SELECT {', '.join(columns)} FROM {table} {where} ORDER BY confirmed_at",
        params,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    # utf-8-sig adds BOM so Excel/SSMS open Thai correctly.
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
        "--db", default=str(ROOT / "logs" / "measurements.db"),
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
        export_table(con, "lot_sessions", LOT_SESSIONS_COLS,
                     out_dir / "lot_sessions.csv", args.since)
        export_table(con, "measurements", MEASUREMENTS_COLS,
                     out_dir / "measurements.csv", args.since)
    finally:
        con.close()

    # Drop a tiny readme alongside so the team knows what they're looking at.
    (out_dir / "README.txt").write_text(
        f"CSV export from {src.name}\n"
        f"Generated: {datetime.now().isoformat()}\n"
        f"Schema:    db/schema_mssql.sql (column order matches)\n"
        f"Encoding:  UTF-8 with BOM\n"
        f"Nulls:     empty cell\n",
        encoding="utf-8",
    )
    print(f"\nDone. See {out_dir}/README.txt for details.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

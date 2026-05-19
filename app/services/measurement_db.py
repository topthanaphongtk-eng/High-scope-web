"""Local SQLite store for confirmed pad/ball measurements.

One row per pad detection. The same LOT confirm inserts N rows (one per
detected pad across the 4 locations) tied together by `session_id` so a
re-measure of the same LOT is distinguishable from the original.

Layout (web-ready):
    measurements      — per-pad numeric facts + paths + raw JSON
    lot_sessions     — per-confirm context (operator, hostname, version, …)
    v_measurements_full — convenience VIEW that joins both for read APIs

The DB lives next to the app's logs (`./logs/measurements.db`) for fast,
contention-free writes. A web layer can either:
  • copy the .db file periodically (read-only consumers),
  • or call `export_json()` to dump a date range for ingestion, or
  • read the per-LOT `record.json` mirror written into the share folder.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import socket
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)


_SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS lot_sessions (
    session_id      TEXT PRIMARY KEY,         -- UUID per confirm
    confirmed_at    TEXT NOT NULL,
    lot_id          TEXT NOT NULL,
    bonding_number  TEXT,
    lot_location    TEXT,
    mpc             TEXT,
    package         TEXT,
    qs              TEXT,
    operator_badge  TEXT NOT NULL,
    hostname        TEXT,
    app_version     TEXT,
    n_locations     INTEGER NOT NULL,
    n_pads          INTEGER NOT NULL,
    raw_lot_info    TEXT                      -- JSON dump of full LotDetail
);

CREATE INDEX IF NOT EXISTS idx_session_lot
    ON lot_sessions (lot_id, confirmed_at);
CREATE INDEX IF NOT EXISTS idx_session_bonding
    ON lot_sessions (bonding_number, lot_location, confirmed_at);
CREATE INDEX IF NOT EXISTS idx_session_date
    ON lot_sessions (confirmed_at);

CREATE TABLE IF NOT EXISTS measurements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,                     -- FK → lot_sessions.session_id
    confirmed_at    TEXT    NOT NULL,
    lot_id          TEXT    NOT NULL,
    bonding_number  TEXT    NOT NULL,
    lot_location    TEXT,
    mpc             TEXT,
    package         TEXT,
    qs              TEXT,
    operator_badge  TEXT    NOT NULL,
    location        TEXT    NOT NULL,         -- TL/TR/BL/BR (pad position)
    pad_index       INTEGER NOT NULL,
    pad_w_um        REAL,
    pad_h_um        REAL,
    ball_d_um       REAL,
    gap_min_um      REAL,
    gap_mean_um     REAL,
    confidence      TEXT,
    pixel_size_um   REAL,
    source_ball_path TEXT,                    -- focus-ball TIFF (operator drop)
    source_pad_path  TEXT,                    -- focus-pad TIFF
    stored_ball_path TEXT,                    -- destination in share folder
    stored_pad_path  TEXT,
    extra_json      TEXT                      -- full PadMeasurement.to_dict() JSON
);

CREATE INDEX IF NOT EXISTS idx_bonding
    ON measurements (bonding_number, lot_location, confirmed_at);
CREATE INDEX IF NOT EXISTS idx_lot
    ON measurements (lot_id);
CREATE INDEX IF NOT EXISTS idx_date
    ON measurements (confirmed_at);
CREATE INDEX IF NOT EXISTS idx_session
    ON measurements (session_id);
"""

# View is created AFTER column migrations so older DBs that pre-date these
# columns can ALTER TABLE first, then the view sees the full set.
_SCHEMA_VIEW = """
DROP VIEW IF EXISTS v_measurements_full;
CREATE VIEW v_measurements_full AS
SELECT
    m.id, m.session_id, m.confirmed_at,
    m.lot_id, m.bonding_number, m.lot_location,
    m.mpc, m.package, m.qs, m.operator_badge,
    s.hostname, s.app_version,
    m.location, m.pad_index,
    m.pad_w_um, m.pad_h_um,
    m.ball_d_um, m.gap_min_um, m.gap_mean_um,
    m.confidence, m.pixel_size_um,
    m.source_ball_path, m.source_pad_path,
    m.stored_ball_path, m.stored_pad_path,
    m.extra_json,
    s.raw_lot_info
FROM measurements m
LEFT JOIN lot_sessions s ON s.session_id = m.session_id;
"""

# Columns that newer schema versions added — applied via ALTER TABLE on
# existing DBs created before the column existed. Idempotent.
_MIGRATIONS = [
    ("lot_location", "TEXT"),
    ("session_id",   "TEXT"),
    ("mpc",          "TEXT"),
    ("package",      "TEXT"),
    ("qs",           "TEXT"),
    ("source_ball_path", "TEXT"),
    ("source_pad_path",  "TEXT"),
    ("stored_ball_path", "TEXT"),
    ("stored_pad_path",  "TEXT"),
    ("extra_json",   "TEXT"),
]


class MeasurementDB:
    """Thin SQLite wrapper. Connections are short-lived (one per call) so
    the file isn't locked between calls — important if the operator copies
    the DB to a share while the app is running."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(str(self.path))
        try:
            con.row_factory = sqlite3.Row
            yield con
            con.commit()
        finally:
            con.close()

    def _init_schema(self) -> None:
        with self._conn() as con:
            # 1) Base tables + indices (CREATE IF NOT EXISTS — never destructive)
            con.executescript(_SCHEMA_TABLES)
            # 2) Migrate older DBs that may be missing newer columns. Must
            #    happen BEFORE the view is created (the view references
            #    these columns and would fail to bind on an older DB).
            cur = con.execute("PRAGMA table_info(measurements)")
            existing = {row[1] for row in cur.fetchall()}
            for col, ddl in _MIGRATIONS:
                if col not in existing:
                    con.execute(f"ALTER TABLE measurements ADD COLUMN {col} {ddl}")
                    log.info("DB: migrated — added column %s", col)
            # 3) (Re)create the convenience view now that all columns exist.
            con.executescript(_SCHEMA_VIEW)

    # ---------------- writes ----------------

    def insert_lot(
        self,
        *,
        lot_id: str,
        bonding_number: str,
        operator_badge: str,
        per_location_pads: dict[str, list[dict[str, Any]]],
        lot_info: dict[str, Any] | None = None,
        per_location_paths: dict[str, dict[str, Any]] | None = None,
        confirmed_at: datetime | None = None,
        app_version: str | None = None,
    ) -> str:
        """Insert one session row + N measurement rows. Returns the session_id.

        `per_location_pads` shape:
            { "TL": [pad_dict, ...], "TR": [...], ... }
        `per_location_paths` (optional, web-traceability):
            { "TL": {"source_ball": Path, "source_pad": Path,
                     "stored_ball": Path, "stored_pad": Path}, ... }
        """
        ts = (confirmed_at or datetime.now().astimezone()).isoformat()
        info = lot_info or {}
        paths = per_location_paths or {}
        lot_location = (
            info.get("lot_location")
            or info.get("LotLocation")
            or info.get("location")
        )
        session_id = str(uuid.uuid4())
        hostname = socket.gethostname()

        # Build measurement rows + count.
        rows: list[tuple[Any, ...]] = []
        n_pads = 0
        for loc, pads in per_location_pads.items():
            loc_paths = paths.get(loc, {})
            src_b = _path_str(loc_paths.get("source_ball"))
            src_p = _path_str(loc_paths.get("source_pad"))
            sto_b = _path_str(loc_paths.get("stored_ball"))
            sto_p = _path_str(loc_paths.get("stored_pad"))
            for i, p in enumerate(pads, start=1):
                ball = p.get("ball") or {}
                gap = p.get("gap") or {}
                rows.append((
                    session_id, ts, lot_id, bonding_number, lot_location,
                    info.get("mpc"), info.get("package"), info.get("qs"),
                    operator_badge, loc, i,
                    p.get("width_um"), p.get("height_um"),
                    ball.get("diameter_um") if ball else None,
                    gap.get("min_gap_um") if gap else None,
                    gap.get("mean_gap_um") if gap else None,
                    p.get("confidence"),
                    p.get("pixel_size_um"),
                    src_b, src_p, sto_b, sto_p,
                    json.dumps(p, default=str, ensure_ascii=False),
                ))
                n_pads += 1
        if not rows:
            return session_id

        with self._conn() as con:
            con.execute(
                """
                INSERT INTO lot_sessions (
                    session_id, confirmed_at, lot_id, bonding_number,
                    lot_location, mpc, package, qs,
                    operator_badge, hostname, app_version,
                    n_locations, n_pads, raw_lot_info
                ) VALUES (?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?)
                """,
                (
                    session_id, ts, lot_id, bonding_number, lot_location,
                    info.get("mpc"), info.get("package"), info.get("qs"),
                    operator_badge, hostname, app_version,
                    len(per_location_pads), n_pads,
                    json.dumps(info, default=str, ensure_ascii=False),
                ),
            )
            con.executemany(
                """
                INSERT INTO measurements (
                    session_id, confirmed_at, lot_id, bonding_number, lot_location,
                    mpc, package, qs,
                    operator_badge, location, pad_index,
                    pad_w_um, pad_h_um, ball_d_um,
                    gap_min_um, gap_mean_um,
                    confidence, pixel_size_um,
                    source_ball_path, source_pad_path,
                    stored_ball_path, stored_pad_path,
                    extra_json
                ) VALUES (?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?, ?,?, ?,?,?,?, ?)
                """,
                rows,
            )
        log.info(
            "DB: session %s — inserted %d row(s) for LOT %s, bonding %s @ %s",
            session_id, len(rows), lot_id, bonding_number, lot_location or "—",
        )
        return session_id

    # ---------------- reads ----------------

    def history_for_bonding(
        self,
        bonding_number: str,
        *,
        lot_location: str | None = None,
        limit_lots: int = 30,
    ) -> list[dict[str, Any]]:
        """Return rows for the last `limit_lots` LOTs that share
        `bonding_number` (and `lot_location` when provided), oldest → newest.

        Filtering by lot_location lets the operator see trend "by machine"
        without mixing data from different bonding stations. NULL/missing
        lot_location values are treated as their own bucket.
        """
        with self._conn() as con:
            if lot_location is None:
                where = "bonding_number = ?"
                params: tuple[Any, ...] = (bonding_number,)
            else:
                # `lot_location IS ?` matches NULLs cleanly when the value
                # is None — sqlite3's ? binding doesn't allow that on `=`.
                where = (
                    "bonding_number = ? AND COALESCE(lot_location, '') = ?"
                )
                params = (bonding_number, lot_location or "")
            cur = con.execute(
                f"""
                WITH recent_lots AS (
                    SELECT lot_id, MIN(confirmed_at) AS first_ts
                    FROM measurements
                    WHERE {where}
                    GROUP BY lot_id
                    ORDER BY first_ts DESC
                    LIMIT ?
                )
                SELECT m.*
                FROM measurements m
                JOIN recent_lots r ON r.lot_id = m.lot_id
                WHERE {where}
                ORDER BY m.confirmed_at ASC, m.location ASC, m.pad_index ASC
                """,
                (*params, int(limit_lots), *params),
            )
            return [dict(row) for row in cur.fetchall()]

    def all_bondings(self) -> list[tuple[str, int]]:
        """List of (bonding_number, lot_count) — useful for diagnostic UIs."""
        with self._conn() as con:
            cur = con.execute(
                """
                SELECT bonding_number, COUNT(DISTINCT lot_id) AS n_lots
                FROM measurements
                GROUP BY bonding_number
                ORDER BY n_lots DESC
                """
            )
            return [(row["bonding_number"], int(row["n_lots"])) for row in cur.fetchall()]

    # ---------------- web-ready exports ----------------

    def export_json(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        bonding_number: str | None = None,
        lot_location: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return a list of measurement rows from `v_measurements_full`,
        optionally filtered. Designed for ingestion by a web layer (HTTP
        endpoint or batch dump). Each row is a dict ready for JSON encode."""
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("confirmed_at >= ?")
            params.append(since.isoformat())
        if until is not None:
            clauses.append("confirmed_at <= ?")
            params.append(until.isoformat())
        if bonding_number is not None:
            clauses.append("bonding_number = ?")
            params.append(bonding_number)
        if lot_location is not None:
            clauses.append("COALESCE(lot_location, '') = ?")
            params.append(lot_location)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        limit_sql = f"LIMIT {int(limit)}" if limit else ""
        with self._conn() as con:
            cur = con.execute(
                f"""
                SELECT * FROM v_measurements_full
                {where}
                ORDER BY confirmed_at DESC, lot_id, location, pad_index
                {limit_sql}
                """,
                tuple(params),
            )
            out: list[dict[str, Any]] = []
            for row in cur.fetchall():
                d = dict(row)
                # Decode embedded JSON columns so the consumer doesn't have to.
                for col in ("extra_json", "raw_lot_info"):
                    if d.get(col):
                        try:
                            d[col] = json.loads(d[col])
                        except (TypeError, ValueError):
                            pass
                out.append(d)
            return out

    def session_record(self, session_id: str) -> dict[str, Any] | None:
        """Return one session + its measurement rows as a single nested dict.
        Convenient for writing a per-LOT `record.json` to the share folder.
        """
        with self._conn() as con:
            ses_cur = con.execute(
                "SELECT * FROM lot_sessions WHERE session_id = ?",
                (session_id,),
            )
            ses = ses_cur.fetchone()
            if ses is None:
                return None
            ses_d = dict(ses)
            if ses_d.get("raw_lot_info"):
                try:
                    ses_d["raw_lot_info"] = json.loads(ses_d["raw_lot_info"])
                except (TypeError, ValueError):
                    pass
            m_cur = con.execute(
                """
                SELECT * FROM measurements WHERE session_id = ?
                ORDER BY location, pad_index
                """,
                (session_id,),
            )
            measurements = []
            for row in m_cur.fetchall():
                d = dict(row)
                if d.get("extra_json"):
                    try:
                        d["extra_json"] = json.loads(d["extra_json"])
                    except (TypeError, ValueError):
                        pass
                measurements.append(d)
        return {"session": ses_d, "measurements": measurements}

    def mirror_session_to_share(
        self, session_id: str, share_root: Path,
    ) -> Path | None:
        """Write a per-session `record.json` next to the LOT's images so a
        web crawler can scan the share folder without DB access. Returns
        the written path or None if the session was not found.

        Layout: {share_root}/{YYYY}/{MM}/{lot_id}/_records/{session_id}.json
        """
        record = self.session_record(session_id)
        if record is None:
            return None
        ses = record["session"]
        ts_iso = ses.get("confirmed_at") or datetime.now().astimezone().isoformat()
        try:
            ts = datetime.fromisoformat(ts_iso)
        except ValueError:
            ts = datetime.now().astimezone()
        out_dir = (
            Path(share_root)
            / f"{ts:%Y}"
            / f"{ts:%m}"
            / str(ses.get("lot_id"))
            / "_records"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{session_id}.json"
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(record, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(target)
        log.info("DB: mirrored session %s → %s", session_id, target)
        return target


def _path_str(v: Any) -> str | None:
    """Convert Path/str/None → str | None for SQLite storage."""
    if v is None:
        return None
    return str(v)

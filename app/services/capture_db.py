"""Central PostgreSQL store for confirmed image captures.

One row in `captures` per Confirm event, plus N rows in `capture_files` for
the fused images saved on the share folder. Mode 1 has 1 file row, Mode 2
has 3 (Ball / Pad / Weld).

Schema is owned by the DBA — see `db/schema_postgres.sql`. This module only
reads/writes; it does not create tables. All stations + the Next.js web
monitor point at the same database, which is how history is shared.
"""

from __future__ import annotations

import json
import logging
import socket
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json

from app.config import PostgresSettings

log = logging.getLogger(__name__)


def _dumps(obj: Any) -> str:
    """JSON encoder for raw_lot_info: keep Unicode, stringify odd types."""
    return json.dumps(obj, default=str, ensure_ascii=False)


def _connect_kwargs(cfg: PostgresSettings) -> dict[str, Any]:
    return {
        "host": cfg.host,
        "port": cfg.port,
        "dbname": cfg.database,
        "user": cfg.user,
        "password": cfg.password,
        "sslmode": cfg.sslmode,
    }


class CaptureDB:
    """Thin psycopg2 wrapper. Connections are short-lived (one per call) so
    the pool isn't held between Confirm clicks — fits the operator cadence
    and avoids issues if PostgreSQL briefly goes away."""

    def __init__(self, cfg: PostgresSettings) -> None:
        self._cfg = cfg
        self._connect_kwargs = _connect_kwargs(cfg)
        # Connection is *not* verified here so the GUI can still open
        # when settings.yaml is incomplete — operators can then fix it
        # via the Settings dialog. The first read/write surfaces any
        # connectivity error to the user.

    @contextmanager
    def _conn(self):
        con = psycopg2.connect(**self._connect_kwargs)
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # ---------------- writes ----------------

    def insert_capture(
        self,
        *,
        lot_id: str,
        bonding_number: str | None,
        operator_badge: str,
        mode: str,
        files: list[dict[str, Any]],
        lot_info: dict[str, Any] | None = None,
        confirmed_at: datetime | None = None,
        app_version: str | None = None,
    ) -> str:
        """Insert one capture row + N file rows. Returns the capture_id.

        `files` shape:
            [{"slot": "Ball", "fused_path": str, "fused_name": str,
              "size_bytes": int, "sha256": str|None}, ...]
        """
        ts = confirmed_at or datetime.now()
        info = lot_info or {}
        lot_location = (
            info.get("lot_location")
            or info.get("LotLocation")
            or info.get("location")
        )
        capture_id = str(uuid.uuid4())
        hostname = socket.gethostname()

        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                """
                INSERT INTO captures (
                    capture_id, confirmed_at, lot_id, bonding_number,
                    lot_location, mpc, package, qs,
                    operator_badge, hostname, app_version,
                    mode, raw_lot_info
                ) VALUES (%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s)
                """,
                (
                    capture_id, ts, lot_id, bonding_number, lot_location,
                    info.get("mpc"), info.get("package"), info.get("qs"),
                    operator_badge, hostname, app_version, mode,
                    Json(info, dumps=_dumps),
                ),
            )
            cur.executemany(
                """
                INSERT INTO capture_files (
                    capture_id, slot, fused_path, fused_name, size_bytes, sha256
                ) VALUES (%s,%s,%s,%s,%s,%s)
                """,
                [
                    (
                        capture_id,
                        f["slot"],
                        str(f["fused_path"]),
                        f["fused_name"],
                        f.get("size_bytes"),
                        f.get("sha256"),
                    )
                    for f in files
                ],
            )
        log.info(
            "DB: capture %s — %d file(s) for LOT %s, bonding %s @ %s (mode=%s)",
            capture_id, len(files), lot_id, bonding_number, lot_location or "—", mode,
        )
        return capture_id

    # ---------------- reads ----------------

    def recent_captures(
        self,
        *,
        limit: int = 50,
        since: datetime | None = None,
        until: datetime | None = None,
        bonding_number: str | None = None,
        lot_location: str | None = None,
        lot_id: str | None = None,
        mode: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("c.confirmed_at >= %s")
            params.append(since)
        if until is not None:
            clauses.append("c.confirmed_at <= %s")
            params.append(until)
        if bonding_number is not None:
            clauses.append("c.bonding_number = %s")
            params.append(bonding_number)
        if lot_location is not None:
            clauses.append("COALESCE(c.lot_location, '') = %s")
            params.append(lot_location)
        if lot_id is not None:
            clauses.append("c.lot_id = %s")
            params.append(lot_id)
        if mode is not None:
            clauses.append("c.mode = %s")
            params.append(mode)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        # Pick the page of capture_ids first, then JOIN files only for
        # those rows — avoids the old "limit * 4" trick.
        sql = f"""
            WITH paged AS (
                SELECT capture_id, confirmed_at
                FROM captures c
                {where}
                ORDER BY c.confirmed_at DESC, c.capture_id
                LIMIT %s
            )
            SELECT c.*, f.slot, f.fused_path, f.fused_name,
                   f.size_bytes AS file_size_bytes, f.sha256 AS file_sha256
            FROM captures c
            INNER JOIN paged p ON p.capture_id = c.capture_id
            LEFT JOIN capture_files f ON f.capture_id = c.capture_id
            ORDER BY c.confirmed_at DESC, c.capture_id, f.id
        """
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(sql, (*params, int(limit)))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        # Group rows back by capture_id, preserving order
        grouped: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for r in rows:
            cid = str(r["capture_id"])
            if cid not in grouped:
                base = {
                    k: v
                    for k, v in r.items()
                    if k not in ("slot", "fused_path", "fused_name", "file_size_bytes", "file_sha256")
                }
                base["capture_id"] = cid
                if isinstance(base.get("confirmed_at"), datetime):
                    base["confirmed_at"] = base["confirmed_at"].isoformat()
                base["files"] = []
                grouped[cid] = base
                order.append(cid)
            if r.get("slot") is not None:
                grouped[cid]["files"].append({
                    "slot": r["slot"],
                    "fused_path": r["fused_path"],
                    "fused_name": r["fused_name"],
                    "size_bytes": r["file_size_bytes"],
                    "sha256": r["file_sha256"],
                })
        out = [grouped[cid] for cid in order]
        # raw_lot_info is JSONB → psycopg2 already returns a dict; decode only
        # if some row came back as a plain string.
        for c in out:
            if isinstance(c.get("raw_lot_info"), str):
                try:
                    c["raw_lot_info"] = json.loads(c["raw_lot_info"])
                except (TypeError, ValueError):
                    pass
        return out

    def lot_captures(self, lot_id: str) -> list[dict[str, Any]]:
        return self.recent_captures(lot_id=lot_id, limit=500)

    def all_lots(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT lot_id,
                       MAX(confirmed_at) AS last_confirmed_at,
                       COUNT(*) AS capture_count
                FROM captures
                GROUP BY lot_id
                ORDER BY last_confirmed_at DESC
                LIMIT %s
                """,
                (int(limit),),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            if isinstance(r.get("last_confirmed_at"), datetime):
                r["last_confirmed_at"] = r["last_confirmed_at"].isoformat()
        return rows

    # ---------------- web-ready exports ----------------

    def capture_record(self, capture_id: str) -> dict[str, Any] | None:
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                "SELECT * FROM captures WHERE capture_id = %s",
                (capture_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            cap: dict[str, Any] = dict(zip(cols, row))
            cap["capture_id"] = str(cap["capture_id"])
            if isinstance(cap.get("confirmed_at"), datetime):
                cap["confirmed_at"] = cap["confirmed_at"].isoformat()
            if isinstance(cap.get("raw_lot_info"), str):
                try:
                    cap["raw_lot_info"] = json.loads(cap["raw_lot_info"])
                except (TypeError, ValueError):
                    pass
            cur.execute(
                "SELECT * FROM capture_files WHERE capture_id = %s ORDER BY id",
                (capture_id,),
            )
            f_cols = [d[0] for d in cur.description]
            cap["files"] = [dict(zip(f_cols, r)) for r in cur.fetchall()]
            for f in cap["files"]:
                f["capture_id"] = str(f["capture_id"])
        return cap

    def mirror_capture_to_share(
        self, capture_id: str, share_root: Path,
    ) -> Path | None:
        """Write a per-capture `record.json` next to the LOT's images so a web
        crawler can scan the share folder without DB access. Returns the
        written path or None if the capture was not found.

        Layout: {share_root}/{YYYY}/{MM}/{lot_id}/_records/{capture_id}.json
        """
        record = self.capture_record(capture_id)
        if record is None:
            return None
        ts_iso = record.get("confirmed_at") or datetime.now().astimezone().isoformat()
        try:
            ts = datetime.fromisoformat(ts_iso)
        except ValueError:
            ts = datetime.now().astimezone()
        out_dir = (
            Path(share_root)
            / f"{ts:%Y}"
            / f"{ts:%m}"
            / str(record.get("lot_id"))
            / "_records"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{capture_id}.json"
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(record, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(target)
        log.info("DB: mirrored capture %s → %s", capture_id, target)
        return target

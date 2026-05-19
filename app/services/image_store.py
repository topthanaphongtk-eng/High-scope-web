from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

from app import __version__ as APP_VERSION
from app.models.capture import CaptureRecord
from app.services.omexml import parse_tiff

log = logging.getLogger(__name__)

_BKK_UTC_OFFSET_HOURS = 7


def _local_time(utc: datetime | None) -> datetime:
    if utc is None:
        return datetime.now().astimezone()
    return utc.astimezone()


def _sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _format_name(
    lot_id: str,
    acquired: datetime,
    location: str,
    index_in_location: int,
    host: str,
) -> str:
    ts = acquired.strftime("%Y%m%d_%H%M%S")
    safe_lot = "".join(c for c in lot_id if c.isalnum() or c in "-_")
    safe_loc = "".join(c for c in location if c.isalnum())
    safe_host = "".join(c for c in host if c.isalnum() or c in "-_")
    return f"{safe_lot}_{ts}_{safe_loc}_{index_in_location}_{safe_host}.tif"


def _atomic_copy(src: Path, dst: Path) -> None:
    """Copy src to dst via a .tmp file in the same folder, then rename.

    Rename is atomic on NTFS, so readers on a shared folder never see a half-written file.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


class ImageStore:
    """Copies an incoming TIFF into the shared QC folder with a sidecar JSON."""

    def __init__(
        self,
        shared_root: Path,
        *,
        hostname: str | None = None,
        compute_sha256: bool = True,
    ) -> None:
        self.shared_root = Path(shared_root)
        self.hostname = hostname or socket.gethostname()
        self.compute_sha256 = compute_sha256

    def save(
        self,
        *,
        source: Path,
        lot_id: str,
        lot_info: dict[str, Any],
        operator_badge: str,
        location: str,
        index_in_location: int,
        measurement: dict[str, Any] | None = None,
    ) -> CaptureRecord:
        source = Path(source)
        ome = parse_tiff(source)
        acquired_local = _local_time(ome.acquisition_date_utc)

        stored_name = _format_name(
            lot_id, acquired_local, location, index_in_location, self.hostname,
        )
        dest_dir = (
            self.shared_root
            / f"{acquired_local:%Y}"
            / f"{acquired_local:%m}"
            / lot_id
        )
        dest_path = dest_dir / stored_name

        _atomic_copy(source, dest_path)

        size_bytes = dest_path.stat().st_size
        sha = _sha256_of(dest_path) if self.compute_sha256 else None

        record = CaptureRecord(
            lot_id=lot_id,
            lot_info=lot_info,
            operator_badge=operator_badge,
            location=location,
            index_in_location=index_in_location,
            acquired_at_local=acquired_local,
            ome=ome,
            source_path=source,
            stored_path=dest_path,
            stored_name=stored_name,
            size_bytes=size_bytes,
            sha256=sha,
            hostname=self.hostname,
            app_version=APP_VERSION,
            measurement=measurement,
        )

        sidecar = dest_path.with_suffix(".json")
        sidecar_tmp = sidecar.with_suffix(".json.tmp")
        sidecar_tmp.write_text(
            json.dumps(record.to_sidecar(), indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(sidecar_tmp, sidecar)

        log.info("Saved %s (%.1f MB) → %s", source.name, size_bytes / 1e6, dest_path)
        return record

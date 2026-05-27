from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import __version__ as APP_VERSION
from app.models.capture import CaptureRecord, OmeAcquisition

log = logging.getLogger(__name__)


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


def _safe(s: str) -> str:
    return "".join(c for c in s if c.isalnum() or c in "-_")


def _format_fused_name(
    lot_id: str,
    badge: str,
    lot_location: str | None,
    slot: str,
    acquired: datetime,
    host: str,
) -> str:
    """Filename scheme: {LOT}_{Badge}_{LotLoc}_{Slot}_{TS}_{Host}.tif

    Slot is sanitised (e.g. "1st Ball" -> "1stBall") so the filename is
    safe on Windows shares.
    """
    ts = acquired.strftime("%Y%m%d_%H%M%S")
    parts = [_safe(lot_id), _safe(badge), _safe(lot_location or "machine")]
    if slot:
        parts.append(_safe(slot))
    parts.append(ts)
    parts.append(_safe(host))
    return "_".join(p for p in parts if p) + ".tif"


def _write_tiff_atomic(bgr: np.ndarray, dst: Path) -> None:
    """Write a BGR ndarray as TIFF via a temp file in the same folder, then rename.
    Rename is atomic on NTFS, so readers on a shared folder never see a half-written file.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    try:
        ok, encoded = cv2.imencode(".tif", bgr)
        if not ok:
            raise RuntimeError(f"cv2.imencode failed for {dst}")
        tmp.write_bytes(encoded.tobytes())
        os.replace(tmp, dst)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


class ImageStore:
    """Saves a fused image into the shared QC folder with a sidecar JSON."""

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

    def save_fused(
        self,
        fused_bgr: np.ndarray,
        *,
        lot_id: str,
        badge: str,
        lot_info: dict[str, Any],
        slot: str,
        acquired_at: datetime | None = None,
        ome: OmeAcquisition | None = None,
    ) -> CaptureRecord:
        acquired_local = _local_time(acquired_at) if acquired_at is not None else datetime.now().astimezone()
        ome = ome or OmeAcquisition()

        lot_location = (
            lot_info.get("lot_location")
            or lot_info.get("LotLocation")
            or lot_info.get("location")
        )

        stored_name = _format_fused_name(
            lot_id, badge, lot_location, slot, acquired_local, self.hostname,
        )
        dest_dir = (
            self.shared_root
            / f"{acquired_local:%Y}"
            / f"{acquired_local:%m}"
            / lot_id
        )
        dest_path = dest_dir / stored_name

        _write_tiff_atomic(fused_bgr, dest_path)

        size_bytes = dest_path.stat().st_size
        sha = _sha256_of(dest_path) if self.compute_sha256 else None

        record = CaptureRecord(
            lot_id=lot_id,
            lot_info=lot_info,
            operator_badge=badge,
            slot=slot,
            acquired_at_local=acquired_local,
            ome=ome,
            stored_path=dest_path,
            stored_name=stored_name,
            size_bytes=size_bytes,
            sha256=sha,
            hostname=self.hostname,
            app_version=APP_VERSION,
        )

        sidecar = dest_path.with_suffix(".json")
        sidecar_tmp = sidecar.with_suffix(".json.tmp")
        sidecar_tmp.write_text(
            json.dumps(record.to_sidecar(), indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(sidecar_tmp, sidecar)

        log.info("Saved fused %s (%.1f MB) → %s", stored_name, size_bytes / 1e6, dest_path)
        return record

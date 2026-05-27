from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class OmeAcquisition(BaseModel):
    """Parsed metadata from OME-XML embedded in Olympus Stream TIFFs."""

    microscope_model: str | None = None
    detector_manufacturer: str | None = None
    detector_model: str | None = None
    objective_nominal_mag: float | None = None
    objective_calibrated_mag: float | None = None
    objective_lens_na: float | None = None
    objective_working_distance_um: float | None = None
    experimenter: str | None = None
    acquisition_date_utc: datetime | None = None
    physical_size_x: float | None = None
    physical_size_y: float | None = None
    physical_size_unit: str | None = None
    exposure_ms: float | None = None
    binning: str | None = None
    stream_creator: str | None = None
    image_width: int | None = None
    image_height: int | None = None


class CaptureRecord(BaseModel):
    """Everything we know about a single fused image at save time."""

    lot_id: str
    lot_info: dict[str, Any]
    operator_badge: str
    slot: str                     # "1st Ball" or "2nd Ball" (both modes use this set)

    acquired_at_local: datetime
    ome: OmeAcquisition

    stored_path: Path
    stored_name: str

    size_bytes: int
    sha256: str | None = None

    hostname: str
    app_version: str

    def to_sidecar(self) -> dict[str, Any]:
        return {
            "operator": {
                "badge": self.operator_badge,
            },
            "lot": {
                "id": self.lot_id,
                "data_from_server": self.lot_info,
            },
            "capture": {
                "slot": self.slot,
                "acquired_at": self.acquired_at_local.isoformat(),
                "microscope": self.ome.microscope_model,
                "detector_manufacturer": self.ome.detector_manufacturer,
                "detector_model": self.ome.detector_model,
                "objective_nominal_magnification": self.ome.objective_nominal_mag,
                "objective_calibrated_magnification": self.ome.objective_calibrated_mag,
                "objective_lens_na": self.ome.objective_lens_na,
                "objective_working_distance_um": self.ome.objective_working_distance_um,
                "exposure_ms": self.ome.exposure_ms,
                "binning": self.ome.binning,
                "experimenter": self.ome.experimenter,
                "stream_version": self.ome.stream_creator,
                "physical_size_x": self.ome.physical_size_x,
                "physical_size_y": self.ome.physical_size_y,
                "physical_size_unit": self.ome.physical_size_unit,
                "image_width": self.ome.image_width,
                "image_height": self.ome.image_height,
            },
            "file": {
                "stored_name": self.stored_name,
                "size_bytes": self.size_bytes,
                "sha256": self.sha256,
            },
            "source_host": self.hostname,
            "app_version": self.app_version,
        }

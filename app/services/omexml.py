"""Parse OME-XML metadata embedded in Olympus Stream TIFFs (tag 270)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from app.models.capture import OmeAcquisition

log = logging.getLogger(__name__)

_OME_NS = {
    "OME": "http://www.openmicroscopy.org/Schemas/OME/2015-01",
}


def _find(root: ET.Element, path: str) -> ET.Element | None:
    return root.find(path, _OME_NS)


def _attr_float(el: ET.Element | None, name: str) -> float | None:
    if el is None:
        return None
    v = el.get(name)
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _attr_int(el: ET.Element | None, name: str) -> int | None:
    f = _attr_float(el, name)
    return int(f) if f is not None else None


def _parse_ome_datetime(s: str) -> datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def parse_ome_xml(xml_text: str) -> OmeAcquisition:
    """Parse an OME-XML string into an OmeAcquisition model.

    Unknown/missing fields become None rather than raising; the TIFF itself is
    authoritative so we never want parse failures to block a capture.
    """
    meta = OmeAcquisition()

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.warning("OME-XML parse failed: %s", e)
        return meta

    creator = root.get("Creator")
    if creator:
        meta.stream_creator = creator

    microscope = _find(root, ".//OME:Microscope")
    if microscope is not None:
        meta.microscope_model = microscope.get("Model")

    detector = _find(root, ".//OME:Detector")
    if detector is not None:
        meta.detector_manufacturer = detector.get("Manufacturer")
        meta.detector_model = detector.get("Model")

    objective = _find(root, ".//OME:Objective")
    if objective is not None:
        meta.objective_nominal_mag = _attr_float(objective, "NominalMagnification")
        meta.objective_calibrated_mag = _attr_float(objective, "CalibratedMagnification")
        meta.objective_lens_na = _attr_float(objective, "LensNA")
        wd = _attr_float(objective, "WorkingDistance")
        wd_unit = objective.get("WorkingDistanceUnit", "")
        if wd is not None and (
            "µm" in wd_unit or "um" in wd_unit.lower() or wd_unit == ""
        ):
            meta.objective_working_distance_um = wd

    experimenter = _find(root, ".//OME:Experimenter")
    if experimenter is not None:
        meta.experimenter = experimenter.get("UserName")

    acq_el = _find(root, ".//OME:AcquisitionDate")
    if acq_el is not None and acq_el.text:
        meta.acquisition_date_utc = _parse_ome_datetime(acq_el.text.strip())

    pixels = _find(root, ".//OME:Pixels")
    if pixels is not None:
        meta.physical_size_x = _attr_float(pixels, "PhysicalSizeX")
        meta.physical_size_y = _attr_float(pixels, "PhysicalSizeY")
        meta.physical_size_unit = pixels.get("PhysicalSizeXUnit")
        meta.image_width = _attr_int(pixels, "SizeX")
        meta.image_height = _attr_int(pixels, "SizeY")

    plane = _find(root, ".//OME:Plane")
    if plane is not None:
        meta.exposure_ms = _attr_float(plane, "ExposureTime")

    det_settings = _find(root, ".//OME:DetectorSettings")
    if det_settings is None:
        det_settings = root.find(".//{*}DetectorSettings")
    if det_settings is not None:
        meta.binning = det_settings.get("Binning")

    return meta


def parse_tiff(path: Path | str) -> OmeAcquisition:
    """Open a TIFF, extract its OME-XML (tag 270), and parse it."""
    with Image.open(path) as img:
        tag270 = img.tag_v2.get(270) if hasattr(img, "tag_v2") else None
        width, height = img.size

    if not tag270:
        meta = OmeAcquisition(image_width=width, image_height=height)
        log.warning("No OME-XML (tag 270) in %s", path)
        return meta

    xml_text = tag270 if isinstance(tag270, str) else str(tag270)
    xml_text = re.sub(r"^﻿", "", xml_text)
    meta = parse_ome_xml(xml_text)
    if meta.image_width is None:
        meta.image_width = width
    if meta.image_height is None:
        meta.image_height = height
    return meta

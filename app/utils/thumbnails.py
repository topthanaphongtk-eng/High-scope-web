"""Generate QPixmap thumbnails for the preview grid."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
from PyQt6.QtGui import QImage, QPixmap

THUMBNAIL_SIZE = (180, 135)  # 4:3 matches 1920x1440


def make_thumbnail(path: Path | str, size: tuple[int, int] = THUMBNAIL_SIZE) -> QPixmap:
    """Open the TIFF, downscale, return a QPixmap suitable for QLabel/QListView.

    We route through Pillow (rather than QPixmap.load) because PyQt6's built-in TIFF
    plugin is unreliable on some installs — Pillow + PNG-in-memory handoff is rock solid.
    """
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail(size, Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="PNG")
    qimg = QImage.fromData(buf.getvalue(), "PNG")
    return QPixmap.fromImage(qimg)

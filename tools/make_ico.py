"""Render the programmatic app icon to a Windows .ico file used by
PyInstaller as the executable's embedded icon.

Run once before `pyinstaller` (or whenever the icon design changes):
    python tools/make_ico.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication
from PIL import Image

from app.utils.app_icon import _render_icon  # type: ignore


def main() -> int:
    _ = QApplication([])  # required to use Qt painter
    sizes = [16, 24, 32, 48, 64, 128, 256]
    pil_images: list[Image.Image] = []
    for s in sizes:
        pix = _render_icon(s)
        # Qt → PIL via PNG buffer (handles alpha cleanly).
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pix.save(buf, "PNG")
        pil = Image.open(io.BytesIO(buf.data())).convert("RGBA")
        pil_images.append(pil)
    out = ROOT / "build_assets" / "app.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    pil_images[0].save(
        out, format="ICO",
        sizes=[(im.width, im.height) for im in pil_images],
        append_images=pil_images[1:],
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

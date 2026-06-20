"""Programmatic application icon — indigo rounded card with a stylised
microscope glyph. Rendered at multiple sizes so Windows picks the right one
for taskbar / Alt-Tab / window title bar / start menu.

Two-layer approach for the microscope:
  • emoji 🔬 if the system has a colour emoji font (Segoe UI Emoji, …)
  • a thin white "M-on-base" geometric fallback drawn with QPainter for
    monochrome emoji fonts, so the icon never renders blank.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
)


_INDIGO = QColor("#4f46e5")
_INDIGO_DARK = QColor("#3730a3")
_GOLD = QColor("#fbbf24")
_WHITE = QColor("#ffffff")


def _has_emoji_font() -> bool:
    families = QFontDatabase.families()
    return any(
        any(fam.lower().startswith(prefix) for prefix in (
            "segoe ui emoji", "apple color emoji", "noto color emoji"
        ))
        for fam in families
    )


def _draw_emoji(p: QPainter, rect: QRect) -> None:
    f = QFont("Segoe UI Emoji")
    f.setPointSizeF(rect.width() * 0.55)
    p.setFont(f)
    p.setPen(_WHITE)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "🔬")


def _draw_microscope_glyph(p: QPainter, rect: QRect) -> None:
    """Geometric microscope fallback: base + stage + arm + eyepiece."""
    s = rect.width()
    cx = rect.x() + s // 2
    cy = rect.y() + s // 2
    # Layout proportions inside the icon area (tuned to read clean at 32 px+)
    base_w = int(s * 0.55)
    base_h = int(s * 0.10)
    stage_w = int(s * 0.40)
    stage_h = int(s * 0.05)
    arm_w = int(s * 0.10)
    arm_h = int(s * 0.30)
    eye_w = int(s * 0.22)
    eye_h = int(s * 0.10)
    body_w = int(s * 0.18)
    body_h = int(s * 0.20)

    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)

    # Base
    p.setBrush(_WHITE)
    p.drawRoundedRect(
        cx - base_w // 2, cy + int(s * 0.30),
        base_w, base_h, base_h * 0.4, base_h * 0.4,
    )
    # Stage shelf
    p.drawRoundedRect(
        cx - stage_w // 2, cy + int(s * 0.18),
        stage_w, stage_h, stage_h * 0.5, stage_h * 0.5,
    )
    # Arm (vertical)
    p.drawRoundedRect(
        cx - arm_w // 2, cy - int(s * 0.05),
        arm_w, arm_h, arm_w * 0.3, arm_w * 0.3,
    )
    # Body (lens housing)
    p.drawRoundedRect(
        cx - body_w // 2, cy - int(s * 0.20),
        body_w, body_h, body_w * 0.3, body_w * 0.3,
    )
    # Eyepiece (top)
    p.setBrush(_GOLD)
    p.drawRoundedRect(
        cx - eye_w // 2, cy - int(s * 0.36),
        eye_w, eye_h, eye_h * 0.5, eye_h * 0.5,
    )


def _render_icon(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Background: indigo rounded card with subtle gradient (top-left → bottom-right)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, size * 0.20, size * 0.20)
    from PyQt6.QtGui import QLinearGradient
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, _INDIGO)
    grad.setColorAt(1.0, _INDIGO_DARK)
    p.fillPath(path, QBrush(grad))

    # Glyph layer
    inset = int(size * 0.08)
    glyph_rect = QRect(inset, inset, size - 2 * inset, size - 2 * inset)
    if _has_emoji_font() and size >= 48:
        _draw_emoji(p, glyph_rect)
    else:
        _draw_microscope_glyph(p, glyph_rect)

    p.end()
    return pix


def make_app_icon() -> QIcon:
    """Build a multi-resolution QIcon ready for `QApplication.setWindowIcon`."""
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_render_icon(s))
    return icon

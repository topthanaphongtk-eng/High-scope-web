from __future__ import annotations

import logging
import socket
import traceback
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from PyQt6.QtCore import QMimeData, QPoint, QSize, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDrag,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app import __version__ as APP_VERSION
from app.config import Settings
from app.models.capture import (
    LOCATION_LABELS,
    LOCATION_ORDER,
    SHOTS_PER_LOCATION,
    CaptureRecord,
)
from app.models.lot import LotDetail
from app.services.ball_measure import (
    PadMeasurement,
    compute_gap,
    debug_pad_overlay,
    detect_ball_in_pad,
    detect_pad,
    detect_pads_multi,
    draw_ball_only_overlay,
    draw_multi_ball_only_overlay,
    draw_multi_pad_only_overlay,
    draw_multi_pad_overlay,
    draw_pad_only_overlay,
    draw_pad_overlay,
    focus_stack,
    load_as_bgr,
    pixel_size_um_from_ome,
)
from app.services.capture import FileWatcher
from app.gui.trend_dialog import TrendDialog
from app.services.image_store import ImageStore
from app.services.measurement_db import MeasurementDB
from app.utils.app_icon import make_app_icon
from app.services.lot_client import (
    LotClient,
    LotClientError,
    LotNotFound,
    ServerFault,
    ServerUnreachable,
)
from app.services.omexml import parse_tiff
from app.utils.thumbnails import THUMBNAIL_SIZE, make_thumbnail

log = logging.getLogger(__name__)


# Soft-light 2026 theme. Indigo accent, rounded corners, slate text. Targets
# concrete object names (#name) so we can style structural widgets uniquely
# while leaving generic widgets to inherit the base styles.
_MODERN_QSS = """
* { font-family: "Segoe UI Variable", "Segoe UI", "Inter", system-ui, sans-serif; }

QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget {
    background: #f1f5f9;
}

QWidget { color: #0f172a; font-size: 12px; }

/* ---------- buttons ---------- */
QPushButton {
    background: #ffffff;
    color: #1e293b;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
    min-height: 18px;
}
QPushButton:hover { background: #f8fafc; border-color: #94a3b8; }
QPushButton:pressed { background: #e2e8f0; }
QPushButton:disabled { color: #94a3b8; background: #f1f5f9; border-color: #e2e8f0; }
QPushButton:checked {
    background: #4f46e5; color: #ffffff; border-color: #4338ca;
}
QPushButton:checked:hover { background: #4338ca; }

/* Primary action — give #_measure_btn / #_confirm_btn / #_arm_btn / #_fetch_btn the indigo treatment */
QPushButton#primary {
    background: #4f46e5; color: #ffffff; border: 1px solid #4338ca;
    font-weight: 600;
}
QPushButton#primary:hover { background: #4338ca; border-color: #3730a3; }
QPushButton#primary:pressed { background: #3730a3; }
QPushButton#primary:disabled {
    background: #e0e7ff; color: #a5b4fc; border-color: #c7d2fe;
}

QPushButton#danger {
    background: #ffffff; color: #b91c1c; border: 1px solid #fecaca;
}
QPushButton#danger:hover { background: #fef2f2; border-color: #fca5a5; }

QPushButton#success {
    background: #16a34a; color: #ffffff; border: 1px solid #15803d;
    font-weight: 600;
}
QPushButton#success:hover { background: #15803d; }
QPushButton#success:disabled {
    background: #dcfce7; color: #86efac; border-color: #bbf7d0;
}

/* ---------- inputs ---------- */
QLineEdit {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #c7d2fe;
    selection-color: #1e293b;
}
QLineEdit:focus { border-color: #4f46e5; background: #ffffff; }
QLineEdit:disabled { background: #f1f5f9; color: #94a3b8; }

/* ---------- group boxes (cards) ---------- */
QGroupBox {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    margin-top: 10px;
    padding: 12px 12px 10px 12px;
    font-weight: 600;
    color: #334155;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background: #f1f5f9;
}

/* ---------- list widget ---------- */
QListWidget {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 4px;
}
QListWidget::item {
    border-radius: 6px;
    padding: 4px;
    margin: 2px;
}
QListWidget::item:selected {
    background: #eef2ff;
    color: #1e293b;
    border: 1px solid #818cf8;
}
QListWidget::item:hover { background: #f8fafc; }

/* ---------- segmented unit toggle ---------- */
QPushButton#_unit_um_btn, QPushButton#_unit_mil_btn {
    background: #f1f5f9; color: #475569;
    border: 1px solid #cbd5e1;
    padding: 6px 0;
    font-weight: 600;
    font-size: 12px;
    min-height: 22px;
}
QPushButton#_unit_um_btn { border-top-right-radius: 0; border-bottom-right-radius: 0; border-right: none; }
QPushButton#_unit_mil_btn { border-top-left-radius: 0; border-bottom-left-radius: 0; }
QPushButton#_unit_um_btn:hover, QPushButton#_unit_mil_btn:hover {
    background: #e2e8f0; color: #1e293b;
}
QPushButton#_unit_um_btn:checked, QPushButton#_unit_mil_btn:checked {
    background: #4f46e5; color: #ffffff; border-color: #4338ca;
}

/* ---------- checkbox ---------- */
QCheckBox { spacing: 8px; color: #334155; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #cbd5e1; border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:hover { border-color: #94a3b8; }
QCheckBox::indicator:checked {
    background: #4f46e5; border-color: #4338ca;
    image: none;
}

/* ---------- scroll bars ---------- */
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #cbd5e1; border-radius: 5px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #94a3b8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: #cbd5e1; border-radius: 5px; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #94a3b8; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

/* ---------- menu / status bar ---------- */
QMenuBar { background: #ffffff; border-bottom: 1px solid #e2e8f0; padding: 2px; }
QMenuBar::item { padding: 4px 10px; border-radius: 4px; }
QMenuBar::item:selected { background: #eef2ff; color: #4338ca; }
QMenu { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px; }
QMenu::item { padding: 6px 16px; border-radius: 4px; }
QMenu::item:selected { background: #eef2ff; color: #4338ca; }

QStatusBar { background: #ffffff; border-top: 1px solid #e2e8f0; color: #64748b; }
QStatusBar::item { border: none; }

QToolTip {
    background: #1e293b; color: #f1f5f9;
    border: 1px solid #334155; padding: 6px 8px; border-radius: 4px;
}
"""


# ------------------------------------------------------------------ SOAP worker


class _FetchLotWorker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str, str)

    def __init__(self, client: LotClient, lot_id: str) -> None:
        super().__init__()
        self._client = client
        self._lot_id = lot_id

    def run(self) -> None:
        try:
            detail = self._client.get_lot_detail(self._lot_id)
        except LotNotFound as e:
            self.failed.emit("LOT not found", str(e.reply_desc or e))
        except ServerFault as e:
            self.failed.emit("MES server returned a fault", str(e))
        except ServerUnreachable as e:
            self.failed.emit("Cannot reach MES server", str(e))
        except LotClientError as e:
            self.failed.emit("LOT service error", str(e))
        except Exception as e:
            log.exception("Unexpected error fetching LOT")
            self.failed.emit("Unexpected error", f"{e}\n\n{traceback.format_exc()}")
        else:
            self.succeeded.emit(detail)


# ------------------------------------------------------------------ Drag/drop widgets


class _DragThumbnailList(QListWidget):
    """QListWidget that exposes each item's source path (UserRole) as drag
    mime text and renders a compact, rounded "chip" as the drag pixmap so
    aiming for the small slot canvases is easy."""

    DRAG_W = 72
    DRAG_H = 54

    def mimeData(self, items):  # type: ignore[override]
        mime = QMimeData()
        if items:
            path = items[0].data(Qt.ItemDataRole.UserRole)
            if path:
                mime.setText(str(path))
        return mime

    def startDrag(self, supportedActions) -> None:  # type: ignore[override]
        items = self.selectedItems()
        if not items:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))

        # ---- Custom drag pixmap: 72×54 chip with soft shadow + rounded corners ----
        # Renders the item's icon scaled down inside a clean rounded card so
        # the cursor stays small and the operator can land it precisely on a
        # slot. The shadow gives just enough lift to read against any
        # background (light card, dark canvas, dim metal of a TIFF).
        outer_w, outer_h = self.DRAG_W + 6, self.DRAG_H + 6
        pix = QPixmap(outer_w, outer_h)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Drop shadow (soft, offset 2px right + down)
        for off, alpha in ((3, 30), (2, 50), (1, 80)):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(15, 23, 42, alpha)))
            shadow_path = QPainterPath()
            shadow_path.addRoundedRect(
                3 + off, 3 + off,
                self.DRAG_W, self.DRAG_H,
                8, 8,
            )
            painter.drawPath(shadow_path)

        # Card body (rounded rect)
        card_rect = (3, 3, self.DRAG_W, self.DRAG_H)
        clip = QPainterPath()
        clip.addRoundedRect(*card_rect, 8, 8)
        painter.setClipPath(clip)
        # Image fill (the item's icon)
        src_pix = items[0].icon().pixmap(QSize(self.DRAG_W, self.DRAG_H))
        if not src_pix.isNull():
            scaled = src_pix.scaled(
                self.DRAG_W, self.DRAG_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(3, 3, scaled)
        else:
            painter.fillRect(*card_rect, QColor("#0f172a"))
        painter.setClipping(False)

        # Indigo outline so the chip reads as "active payload"
        painter.setPen(QPen(QColor("#4f46e5"), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outline = QPainterPath()
        outline.addRoundedRect(
            3 + 0.5, 3 + 0.5,
            self.DRAG_W - 1, self.DRAG_H - 1,
            8, 8,
        )
        painter.drawPath(outline)
        painter.end()

        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(outer_w // 2, outer_h // 2))
        drag.exec(supportedActions)


class _ClickableLabel(QLabel):
    """QLabel that emits a click signal with its widget-local (x, y) — used to seed detection."""

    clicked = pyqtSignal(float, float)

    def mousePressEvent(self, e) -> None:  # type: ignore[override]
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(e.position().x(), e.position().y())
        super().mousePressEvent(e)


class _DropCanvas(QLabel):
    """Big preview canvas that doubles as a file drop target.

    States:
      empty           → dashed placeholder with role + hint text
      populated       → shows the dropped image's thumbnail
      analysis-shown  → shows an arbitrary pixmap (e.g. detection overlay) while
                        keeping the underlying path

    Emits `pathChanged` whenever the path changes (drop / clear / replace).
    """

    pathChanged = pyqtSignal(object)  # Path | None

    def __init__(self, role: str, hint: str = "") -> None:
        super().__init__()
        self._role = role
        self._hint = hint
        self._path: Path | None = None
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_empty_style()

    # --- public API ---

    def path(self) -> Path | None:
        return self._path

    def set_path(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            from app.utils.thumbnails import make_thumbnail
            pix = make_thumbnail(path, size=(self.width(), self.height()))
        except Exception:
            log.exception("DropCanvas thumbnail failed for %s", path)
            return
        self._path = path
        self.setText("")
        self.setPixmap(pix)
        self._apply_filled_style()
        self.pathChanged.emit(path)

    def clear(self) -> None:  # type: ignore[override]
        super().clear()
        self._path = None
        self._apply_empty_style()
        self.pathChanged.emit(None)

    def revert_to_source(self) -> None:
        """Re-show the source thumbnail (used after analysis is invalidated)."""
        if self._path is not None:
            try:
                from app.utils.thumbnails import make_thumbnail
                self.setPixmap(make_thumbnail(self._path, size=(self.width(), self.height())))
                self.setText("")
                self._apply_filled_style()
            except Exception:
                self.clear()
        else:
            self._apply_empty_style()

    # --- styling ---

    def _apply_empty_style(self) -> None:
        self.setText(f"\n{self._role}\n\n{self._hint}\n\n(drag image here)")
        self.setStyleSheet(
            "QLabel { background: #f8fafc; border: 2px dashed #cbd5e1;"
            " border-radius: 8px; color: #64748b; font-size: 11px; }"
        )

    def _apply_filled_style(self) -> None:
        self.setStyleSheet(
            "QLabel { background: #0f172a; border: 1px solid #1e293b;"
            " border-radius: 8px; }"
        )

    def _apply_drag_hover_style(self) -> None:
        self.setStyleSheet(
            "QLabel { background: #eef2ff; border: 2px dashed #4f46e5;"
            " border-radius: 8px; color: #4338ca; font-size: 11px; }"
        )

    # --- drop protocol ---

    def dragEnterEvent(self, e) -> None:  # type: ignore[override]
        if e.mimeData().hasText():
            e.acceptProposedAction()
            self._apply_drag_hover_style()

    def dragLeaveEvent(self, _e) -> None:  # type: ignore[override]
        if self._path is None:
            self._apply_empty_style()
        else:
            self._apply_filled_style()

    def dropEvent(self, e) -> None:  # type: ignore[override]
        text = e.mimeData().text()
        if not text:
            return
        try:
            path = Path(text)
        except Exception:
            return
        self.set_path(path)
        e.acceptProposedAction()


class DropSlot(QFrame):
    """A square drop target that accepts a thumbnail from the capture grid.

    Emits `pathChanged` when the slot is populated or cleared.
    """

    pathChanged = pyqtSignal(object)  # Path | None

    def __init__(self, title: str, sublabel: str = "") -> None:
        super().__init__()
        self._path: Path | None = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAcceptDrops(True)
        self.setFixedSize(THUMBNAIL_SIZE[0] + 20, THUMBNAIL_SIZE[1] + 58)

        self._title = QLabel(title)
        f = self._title.font()
        f.setBold(True)
        self._title.setFont(f)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._sublabel = QLabel(sublabel)
        self._sublabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sublabel.setStyleSheet("color: #888; font-size: 10px;")

        self._thumb = QLabel("drop image here")
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setFixedSize(*THUMBNAIL_SIZE)
        self._thumb.setStyleSheet(
            "QLabel { border: 2px dashed #aaa; color: #888; background: #fafafa; }"
        )

        self._clear_btn = QPushButton("× clear")
        self._clear_btn.setFlat(True)
        self._clear_btn.setVisible(False)
        self._clear_btn.clicked.connect(self.clear)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._title)
        if sublabel:
            lay.addWidget(self._sublabel)
        lay.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._clear_btn, 0, Qt.AlignmentFlag.AlignCenter)

    # --- drop target protocol ---

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:  # type: ignore[override]
        if e.mimeData().hasText():
            e.acceptProposedAction()
            self._thumb.setStyleSheet(
                "QLabel { border: 2px dashed #2b8a3e; color: #2b8a3e; background: #e6fcf5; }"
            )

    def dragLeaveEvent(self, _e) -> None:  # type: ignore[override]
        self._refresh_placeholder_style()

    def dropEvent(self, e: QDropEvent) -> None:  # type: ignore[override]
        text = e.mimeData().text()
        if not text:
            return
        self.set_path(Path(text))
        e.acceptProposedAction()

    # --- api ---

    def path(self) -> Path | None:
        return self._path

    def set_path(self, path: Path) -> None:
        if not path.exists():
            self.clear()
            return
        try:
            pix = make_thumbnail(path)
        except Exception:
            log.exception("thumbnail failed in drop slot")
            self.clear()
            return
        self._path = path
        self._thumb.setStyleSheet("QLabel { border: 1px solid #444; }")
        self._thumb.setPixmap(pix)
        self._clear_btn.setVisible(True)
        self.pathChanged.emit(path)

    def clear(self) -> None:
        self._path = None
        self._thumb.clear()
        self._thumb.setText("drop image here")
        self._refresh_placeholder_style()
        self._clear_btn.setVisible(False)
        self.pathChanged.emit(None)

    def _refresh_placeholder_style(self) -> None:
        if self._path is None:
            self._thumb.setStyleSheet(
                "QLabel { border: 2px dashed #aaa; color: #888; background: #fafafa; }"
            )
        else:
            self._thumb.setStyleSheet("QLabel { border: 1px solid #444; }")


# ------------------------------------------------------------------ Startup gate


class _StartupGate(QDialog):
    """Modal sign-in card. The operator enters Badge + LOT before the main UI
    is interactive. Sits on the top layer with a soft backdrop so attention is
    pinned on the inputs.
    """

    def __init__(self, lot_client: LotClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lot_client = lot_client
        self._lot_detail: LotDetail | None = None
        self._fetch_worker: _FetchLotWorker | None = None

        self.setWindowTitle("Sign in")
        self.setModal(True)
        # Frameless dialog covering the entire main window with a SOLID
        # gradient — first impression for the operator, no see-through to the
        # main UI behind. Card-style sign-in panel sits centred inside.
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )

        # Solid indigo→slate→indigo gradient backdrop. Painted via the dialog
        # itself (no translucent attribute) so it fully hides the main UI.
        self.setStyleSheet(
            "QDialog {"
            " background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #1e1b4b, stop:0.45 #0f172a, stop:1 #312e81);"
            "}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Hero strip ----
        hero = QFrame()
        hero.setStyleSheet("QFrame { background: transparent; }")
        hero_v = QVBoxLayout(hero)
        hero_v.setContentsMargins(0, 60, 0, 12)
        hero_v.setSpacing(6)
        # Microscope emoji — represents the Olympus STM7 station this app
        # drives. System emoji fonts render in colour automatically, so the
        # styled `color:` is just a fallback for monochrome glyphs.
        logo = QLabel("🔬")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            "QLabel { color: #fbbf24; font-size: 64px; padding: 4px 0; }"
        )
        brand = QLabel("HIGH  SCOPE  CAPTURE")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setStyleSheet(
            "QLabel { color: #ffffff; font-size: 22px; font-weight: 700;"
            " letter-spacing: 6px; }"
        )
        tagline = QLabel("Bond-ball quality measurement station")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setStyleSheet(
            "QLabel { color: #c7d2fe; font-size: 12px;"
            " letter-spacing: 1px; }"
        )
        hero_v.addWidget(logo)
        hero_v.addWidget(brand)
        hero_v.addWidget(tagline)

        # ---- Sign-in card ----
        self._card = QFrame()
        self._card.setObjectName("card")
        self._card.setStyleSheet(
            "#card { background: #ffffff; border-radius: 18px;"
            " border: 1px solid rgba(255,255,255,0.06); }"
        )
        self._card.setFixedWidth(480)

        card_v = QVBoxLayout(self._card)
        card_v.setContentsMargins(36, 32, 36, 30)
        card_v.setSpacing(14)

        head = QLabel("Sign in to begin")
        head.setStyleSheet(
            "QLabel { color: #0f172a; font-size: 18px; font-weight: 700; }"
        )
        sub = QLabel("Enter your operator badge and the LOT ID for this session.")
        sub.setWordWrap(True)
        sub.setStyleSheet(
            "QLabel { color: #64748b; font-size: 12px; padding-bottom: 6px; }"
        )
        card_v.addWidget(head)
        card_v.addWidget(sub)

        # Badge field — generously sized so it reads from a metre away.
        badge_lbl = QLabel("OPERATOR  BADGE")
        badge_lbl.setStyleSheet(
            "QLabel { color: #4338ca; font-size: 11px; font-weight: 700;"
            " letter-spacing: 1.5px; padding-top: 6px; }"
        )
        self._badge_input = QLineEdit()
        self._badge_input.setPlaceholderText("e.g.  B19277")
        self._badge_input.setMaxLength(32)
        self._badge_input.setMinimumHeight(46)
        self._badge_input.setStyleSheet(
            "QLineEdit { font-size: 16px; padding: 8px 14px;"
            " border: 2px solid #e2e8f0; border-radius: 10px;"
            " background: #f8fafc; }"
            "QLineEdit:focus { border-color: #4f46e5; background: #ffffff; }"
        )
        self._badge_input.textChanged.connect(self._update_state)
        self._badge_input.returnPressed.connect(self._focus_lot)
        card_v.addWidget(badge_lbl)
        card_v.addWidget(self._badge_input)

        # LOT field + Fetch
        lot_lbl = QLabel("LOT  ID")
        lot_lbl.setStyleSheet(
            "QLabel { color: #4338ca; font-size: 11px; font-weight: 700;"
            " letter-spacing: 1.5px; padding-top: 6px; }"
        )
        lot_row = QHBoxLayout()
        lot_row.setSpacing(8)
        self._lot_input = QLineEdit()
        self._lot_input.setPlaceholderText("scan or type LOT, then press Fetch")
        self._lot_input.setMinimumHeight(46)
        self._lot_input.setStyleSheet(
            "QLineEdit { font-size: 16px; padding: 8px 14px;"
            " border: 2px solid #e2e8f0; border-radius: 10px;"
            " background: #f8fafc; }"
            "QLineEdit:focus { border-color: #4f46e5; background: #ffffff; }"
        )
        self._lot_input.textChanged.connect(self._on_lot_text_changed)
        self._lot_input.returnPressed.connect(self._on_fetch_clicked)
        lot_row.addWidget(self._lot_input, 1)
        self._fetch_btn = QPushButton("Fetch")
        self._fetch_btn.setObjectName("primary")
        self._fetch_btn.setMinimumHeight(46)
        self._fetch_btn.setMinimumWidth(96)
        self._fetch_btn.clicked.connect(self._on_fetch_clicked)
        lot_row.addWidget(self._fetch_btn)
        card_v.addWidget(lot_lbl)
        card_v.addLayout(lot_row)

        # LOT detail card (hidden until fetched)
        self._lot_detail_label = QLabel("")
        self._lot_detail_label.setWordWrap(True)
        self._lot_detail_label.setStyleSheet(
            "QLabel { padding: 12px 14px; background: #f0fdf4;"
            " border: 1px solid #86efac; border-radius: 10px; color: #14532d;"
            " font-size: 11px; }"
        )
        self._lot_detail_label.setVisible(False)
        card_v.addWidget(self._lot_detail_label)

        card_v.addSpacing(4)

        self._continue_btn = QPushButton("Continue  →")
        self._continue_btn.setObjectName("success")
        self._continue_btn.setMinimumHeight(46)
        self._continue_btn.setEnabled(False)
        self._continue_btn.setStyleSheet(
            "QPushButton#success { font-size: 14px; font-weight: 600; }"
        )
        self._continue_btn.clicked.connect(self.accept)
        card_v.addWidget(self._continue_btn)

        # ---- Footer strip ----
        footer = QLabel(
            f"v{APP_VERSION}    ·    "
            f"<span style='color:#94a3b8'>{socket.gethostname()}</span>"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setTextFormat(Qt.TextFormat.RichText)
        footer.setStyleSheet(
            "QLabel { color: #64748b; font-size: 11px;"
            " letter-spacing: 1px; padding: 16px 0 28px 0; }"
        )

        # Assemble: hero (top) → card (centre) → footer (bottom)
        outer.addWidget(hero)
        h_center = QHBoxLayout()
        h_center.addStretch(1)
        h_center.addWidget(self._card)
        h_center.addStretch(1)
        outer.addSpacing(8)
        outer.addLayout(h_center)
        outer.addStretch(1)
        outer.addWidget(footer)

        self._update_state()
        self._badge_input.setFocus()

    # -------------- Sizing --------------

    def showEvent(self, e) -> None:  # type: ignore[override]
        super().showEvent(e)
        # Match the parent's geometry so the backdrop fills the whole window.
        if self.parent() is not None:
            geo = self.parent().geometry()  # type: ignore[union-attr]
            self.setGeometry(geo)

    def keyPressEvent(self, e) -> None:  # type: ignore[override]
        # Block Esc — operator must complete Badge + LOT before continuing.
        if e.key() == Qt.Key.Key_Escape:
            e.ignore()
            return
        super().keyPressEvent(e)

    def reject(self) -> None:  # type: ignore[override]
        # Disable the dialog's reject path entirely. Continue is the only exit.
        return

    # -------------- Public API --------------

    def badge(self) -> str:
        return self._badge_input.text().strip().upper()

    def lot_id(self) -> str:
        return self._lot_input.text().strip()

    def lot_detail(self) -> LotDetail | None:
        return self._lot_detail

    # -------------- Internals --------------

    def _update_state(self) -> None:
        have_badge = bool(self._badge_input.text().strip())
        have_lot = bool(self._lot_input.text().strip())
        self._fetch_btn.setEnabled(have_lot)
        self._continue_btn.setEnabled(
            have_badge and have_lot and self._lot_detail is not None
        )

    def _focus_lot(self) -> None:
        self._lot_input.setFocus()

    def _on_lot_text_changed(self) -> None:
        # Editing the LOT after a successful fetch invalidates the cached detail.
        if self._lot_detail is not None:
            self._lot_detail = None
            self._lot_detail_label.setVisible(False)
        self._update_state()

    def _on_fetch_clicked(self) -> None:
        lot_id = self._lot_input.text().strip()
        if not lot_id:
            return
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        self._fetch_btn.setEnabled(False)
        self._fetch_btn.setText("Fetching …")
        self._fetch_worker = _FetchLotWorker(self._lot_client, lot_id)
        self._fetch_worker.succeeded.connect(self._on_fetch_success)
        self._fetch_worker.failed.connect(self._on_fetch_failed)
        self._fetch_worker.finished.connect(self._on_fetch_finished)
        self._fetch_worker.start()

    @pyqtSlot(object)
    def _on_fetch_success(self, detail: LotDetail) -> None:
        self._lot_detail = detail
        parts = [
            f"<b>LOT</b> {detail.lot_id or '—'}",
            f"<b>MPC</b> {detail.mpc or '—'}",
            f"<b>Loc</b> {detail.lot_location or '—'}",
            f"<b>Pkg</b> {detail.package or '—'}",
            f"<b>Bonding</b> {detail.bonding_running or '—'}",
        ]
        self._lot_detail_label.setText(
            "<span style='color:#cbd5e1'>  ·  </span>".join(parts)
        )
        self._lot_detail_label.setVisible(True)
        self._update_state()
        self._continue_btn.setFocus()

    @pyqtSlot(str, str)
    def _on_fetch_failed(self, title: str, detail: str) -> None:
        self._lot_detail = None
        self._lot_detail_label.setText(
            f"<span style='color:#7f1d1d'><b>{title}</b><br>{detail}</span>"
        )
        self._lot_detail_label.setStyleSheet(
            "QLabel { padding: 10px 12px; background: #fef2f2;"
            " border: 1px solid #fca5a5; border-radius: 8px; color: #7f1d1d;"
            " font-size: 11px; }"
        )
        self._lot_detail_label.setVisible(True)
        self._update_state()

    def _on_fetch_finished(self) -> None:
        self._fetch_btn.setEnabled(bool(self._lot_input.text().strip()))
        self._fetch_btn.setText("Fetch")


# ------------------------------------------------------------------ Save-success dialog


class _SaveSuccessDialog(QDialog):
    """Replaces the plain `QMessageBox.information("Saved")` after a Confirm.
    Matches the rest of the modern theme: frameless, soft backdrop, white
    rounded card with a green sparkle, file count, LOT id, and a per-location
    measurement table."""

    def __init__(
        self,
        *,
        lot_id: str,
        n_saved: int,
        per_location_pads: dict[str, list[Any]],
        unit: str = "um",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        wrapper = QWidget(self)
        wrapper.setObjectName("backdrop")
        wrapper.setStyleSheet(
            "#backdrop { background: rgba(15, 23, 42, 0.55); }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(wrapper)

        wrap_layout = QVBoxLayout(wrapper)
        wrap_layout.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            "#card { background: #ffffff; border-radius: 14px;"
            " border: 1px solid #e2e8f0; }"
        )
        card.setFixedWidth(520)

        v = QVBoxLayout(card)
        v.setContentsMargins(28, 24, 28, 22)
        v.setSpacing(12)

        # ---- header: green check chip + title ----
        head = QHBoxLayout()
        head.setSpacing(14)
        check_chip = QLabel("✓")
        check_chip.setFixedSize(48, 48)
        check_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        check_chip.setStyleSheet(
            "QLabel { background: #dcfce7; color: #16a34a; border-radius: 24px;"
            " font-size: 26px; font-weight: 700; }"
        )
        head.addWidget(check_chip)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Saved successfully")
        title.setStyleSheet(
            "QLabel { color: #0f172a; font-size: 19px; font-weight: 700; }"
        )
        sub = QLabel(
            f"<b>{n_saved}</b> image(s) saved for LOT "
            f"<b style='color:#4338ca'>{lot_id}</b>"
        )
        sub.setStyleSheet("QLabel { color: #475569; font-size: 12px; }")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        head.addLayout(title_box, 1)
        v.addLayout(head)

        # ---- per-location summary table ----
        if per_location_pads:
            scale = 1.0 / 25.4 if unit == "mil" else 1.0
            u = "mil" if unit == "mil" else "µm"
            rows: list[str] = []
            for code in LOCATION_ORDER:
                pads = per_location_pads.get(code) or []
                if not pads:
                    rows.append(
                        f"<tr>"
                        f"<td style='padding:6px 10px;color:#94a3b8'><b>{code}</b></td>"
                        f"<td colspan='3' style='padding:6px 10px;color:#94a3b8'>"
                        f"— not measured</td>"
                        f"</tr>"
                    )
                    continue
                m = pads[0]  # primary pad summary
                pad_dims = (
                    f"{m.width_um * scale:.2f} × {m.height_um * scale:.2f} {u}"
                )
                ball_str = (
                    f"{m.ball.diameter_um * scale:.2f} {u}"
                    if m.ball is not None else "—"
                )
                badge_extra = (
                    f" <span style='color:#94a3b8;font-size:10px'>"
                    f"+{len(pads) - 1} more</span>" if len(pads) > 1 else ""
                )
                rows.append(
                    f"<tr style='border-top:1px solid #f1f5f9'>"
                    f"<td style='padding:7px 10px;color:#16a34a;font-weight:600'>{code}</td>"
                    f"<td style='padding:7px 10px;color:#64748b;font-size:11px'>"
                    f"{LOCATION_LABELS.get(code, code)}{badge_extra}</td>"
                    f"<td style='padding:7px 10px;text-align:right'>"
                    f"<span style='color:#475569'>pad </span>{pad_dims}</td>"
                    f"<td style='padding:7px 10px;text-align:right'>"
                    f"<span style='color:#a23'>ball </span>{ball_str}</td>"
                    f"</tr>"
                )
            table_html = (
                f"<table style='border-collapse:collapse;font-family:"
                f"Consolas,monospace;font-size:11px;width:100%;"
                f"background:#f8fafc;border-radius:8px;overflow:hidden'>"
                f"{''.join(rows)}</table>"
            )
            details = QLabel(table_html)
            details.setStyleSheet(
                "QLabel { background: #f8fafc; border: 1px solid #e2e8f0;"
                " border-radius: 8px; padding: 0; }"
            )
            details.setTextFormat(Qt.TextFormat.RichText)
            details.setWordWrap(True)
            v.addWidget(details)

        # ---- footer ----
        footer = QLabel(
            "Records added to local database and shared folder."
        )
        footer.setStyleSheet(
            "QLabel { color: #94a3b8; font-size: 11px; padding-top: 4px; }"
        )
        v.addWidget(footer)

        v.addSpacing(2)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok = QPushButton("Continue  →")
        ok.setObjectName("success")
        ok.setMinimumHeight(36)
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        v.addLayout(btn_row)

        # centre card
        h_center = QHBoxLayout()
        h_center.addStretch(1)
        h_center.addWidget(card)
        h_center.addStretch(1)
        wrap_layout.addStretch(1)
        wrap_layout.addLayout(h_center)
        wrap_layout.addStretch(2)

    def showEvent(self, e) -> None:  # type: ignore[override]
        super().showEvent(e)
        if self.parent() is not None:
            self.setGeometry(self.parent().geometry())  # type: ignore[union-attr]


# ------------------------------------------------------------------ Processing overlay


class _ProcessingOverlay(QFrame):
    """Translucent overlay shown during analysis. Backdrop blocks clicks on
    the main window, the centred card animates a spinner + status text so
    the operator can see exactly what's running.

    Usage:
        overlay = _ProcessingOverlay(parent)
        overlay.show_with("Detecting pad + ball …")
        # ... do work, optionally call overlay.set_message(...) ...
        overlay.hide()
    """

    # 10-frame braille spinner — readable at any size, no images needed.
    _SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("processing_overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#processing_overlay { background: rgba(15, 23, 42, 0.55); }"
        )
        # Eat clicks so the underlying UI is unreachable while busy.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.installEventFilter(self)

        # Card centred inside backdrop.
        self._card = QFrame(self)
        self._card.setObjectName("processing_card")
        self._card.setStyleSheet(
            "#processing_card { background: #ffffff; border-radius: 14px;"
            " border: 1px solid #e2e8f0; }"
        )
        self._card.setFixedSize(360, 130)

        v = QVBoxLayout(self._card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(10)

        head_row = QHBoxLayout()
        head_row.setSpacing(12)
        self._spinner = QLabel(self._SPINNER[0])
        self._spinner.setStyleSheet(
            "QLabel { color: #4f46e5; font-size: 32px; font-weight: 600; }"
        )
        head_row.addWidget(self._spinner)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self._title = QLabel("Processing measurements")
        self._title.setStyleSheet(
            "QLabel { color: #0f172a; font-size: 15px; font-weight: 700; }"
        )
        self._msg = QLabel("Detecting pad + ball …")
        self._msg.setStyleSheet(
            "QLabel { color: #64748b; font-size: 12px; }"
        )
        self._msg.setWordWrap(True)
        title_box.addWidget(self._title)
        title_box.addWidget(self._msg)
        head_row.addLayout(title_box, 1)
        v.addLayout(head_row)

        self._sub = QLabel("This may take a few seconds per location.")
        self._sub.setStyleSheet(
            "QLabel { color: #94a3b8; font-size: 11px; }"
        )
        v.addWidget(self._sub)

        self._frame = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

        self.hide()

    # -------- public API --------

    def show_with(self, message: str = "Detecting pad + ball …") -> None:
        self.set_message(message)
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]
        self.show()
        self.raise_()
        self._frame = 0
        self._timer.start()
        # Force a repaint so the overlay is on screen before heavy work.
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    def set_message(self, message: str) -> None:
        self._msg.setText(message)
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    def hide(self) -> None:  # type: ignore[override]
        self._timer.stop()
        super().hide()

    # -------- internal --------

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(self._SPINNER)
        self._spinner.setText(self._SPINNER[self._frame])

    def resizeEvent(self, e) -> None:  # type: ignore[override]
        super().resizeEvent(e)
        # Re-centre card on every resize (parent may shift while we cover it).
        cx = (self.width() - self._card.width()) // 2
        cy = (self.height() - self._card.height()) // 2
        self._card.move(cx, cy)

    def eventFilter(self, obj, event):  # type: ignore[override]
        # Swallow mouse-press events while the overlay is visible so the
        # underlying widgets can't be interacted with.
        from PyQt6.QtCore import QEvent
        if event.type() in (QEvent.Type.MouseButtonPress,
                            QEvent.Type.MouseButtonDblClick):
            return True
        return super().eventFilter(obj, event)


# ------------------------------------------------------------------ Settings dialog


class _SettingsDialog(QDialog):
    """Edit the two paths the operator most often needs to change:
        • Read folder (where Olympus auto-saves new TIFFs)
        • Share folder (where confirmed measurements are stored)
    Persists back to settings.yaml on Save. The caller is responsible for
    re-arming watchers / swapping ImageStore root using the returned values.
    """

    def __init__(
        self,
        watch_root: Path,
        shared_root: Path,
        db_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._watch_root = Path(watch_root)
        self._shared_root = Path(shared_root)
        self._db_path = Path(db_path)

        self.setWindowTitle("Settings — folder locations")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        wrapper = QWidget(self)
        wrapper.setObjectName("backdrop")
        wrapper.setStyleSheet("#backdrop { background: rgba(15, 23, 42, 0.55); }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(wrapper)

        wrap_layout = QVBoxLayout(wrapper)
        wrap_layout.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            "#card { background: #ffffff; border-radius: 14px;"
            " border: 1px solid #e2e8f0; }"
        )
        card.setFixedWidth(620)

        v = QVBoxLayout(card)
        v.setContentsMargins(28, 26, 28, 24)
        v.setSpacing(14)

        title = QLabel("Settings")
        title.setStyleSheet(
            "QLabel { color: #0f172a; font-size: 22px; font-weight: 700; }"
        )
        subtitle = QLabel(
            "Where the program looks for new captures and where confirmed "
            "results are saved. Changes apply immediately."
        )
        subtitle.setStyleSheet("QLabel { color: #64748b; font-size: 12px; }")
        subtitle.setWordWrap(True)
        v.addWidget(title)
        v.addWidget(subtitle)
        v.addSpacing(4)

        # --- Read folder ---
        read_lbl = QLabel("Read folder  (Olympus auto-save location)")
        read_lbl.setStyleSheet(
            "QLabel { color: #334155; font-size: 11px; font-weight: 600; }"
        )
        v.addWidget(read_lbl)
        self._watch_input = QLineEdit(str(self._watch_root))
        self._watch_input.setMinimumHeight(34)
        watch_btn = QPushButton("Browse…")
        watch_btn.clicked.connect(
            lambda: self._pick_folder(
                self._watch_input, "Choose read folder",
            )
        )
        watch_row = QHBoxLayout()
        watch_row.setSpacing(8)
        watch_row.addWidget(self._watch_input, 1)
        watch_row.addWidget(watch_btn)
        v.addLayout(watch_row)

        # --- Share folder ---
        share_lbl = QLabel("Share folder  (where measurements + TIFFs are saved)")
        share_lbl.setStyleSheet(
            "QLabel { color: #334155; font-size: 11px; font-weight: 600; }"
        )
        v.addWidget(share_lbl)
        self._share_input = QLineEdit(str(self._shared_root))
        self._share_input.setMinimumHeight(34)
        share_btn = QPushButton("Browse…")
        share_btn.clicked.connect(
            lambda: self._pick_folder(
                self._share_input, "Choose share folder",
            )
        )
        share_row = QHBoxLayout()
        share_row.setSpacing(8)
        share_row.addWidget(self._share_input, 1)
        share_row.addWidget(share_btn)
        v.addLayout(share_row)

        # --- Database path ---
        db_lbl = QLabel(
            "Database file  (point every station + web at the same DB to "
            "share history)"
        )
        db_lbl.setStyleSheet(
            "QLabel { color: #334155; font-size: 11px; font-weight: 600; }"
        )
        db_lbl.setWordWrap(True)
        v.addWidget(db_lbl)
        self._db_input = QLineEdit(str(self._db_path))
        self._db_input.setMinimumHeight(34)
        db_btn = QPushButton("Browse…")
        db_btn.clicked.connect(self._pick_db_file)
        db_row = QHBoxLayout()
        db_row.setSpacing(8)
        db_row.addWidget(self._db_input, 1)
        db_row.addWidget(db_btn)
        v.addLayout(db_row)

        # Validation hint (lit on Save attempt if either path is empty/invalid).
        self._hint = QLabel("")
        self._hint.setStyleSheet(
            "QLabel { color: #b91c1c; font-size: 11px; padding-top: 4px; }"
        )
        self._hint.setWordWrap(True)
        v.addWidget(self._hint)

        v.addSpacing(8)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("danger")
        cancel.setMinimumHeight(36)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        btn_row.addStretch(1)
        save = QPushButton("✓  Save")
        save.setObjectName("success")
        save.setMinimumHeight(36)
        save.clicked.connect(self._on_save)
        btn_row.addWidget(save)
        v.addLayout(btn_row)

        # Centre card.
        h_center = QHBoxLayout()
        h_center.addStretch(1)
        h_center.addWidget(card)
        h_center.addStretch(1)
        wrap_layout.addStretch(1)
        wrap_layout.addLayout(h_center)
        wrap_layout.addStretch(2)

    def showEvent(self, e) -> None:  # type: ignore[override]
        super().showEvent(e)
        if self.parent() is not None:
            self.setGeometry(self.parent().geometry())  # type: ignore[union-attr]

    def _pick_folder(self, target: QLineEdit, title: str) -> None:
        from PyQt6.QtWidgets import QFileDialog
        start = target.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, title, start,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if chosen:
            target.setText(chosen)

    def _pick_db_file(self) -> None:
        """File picker for the SQLite DB. Existing or new — Save will
        create the file if it doesn't exist."""
        from PyQt6.QtWidgets import QFileDialog
        start = self._db_input.text().strip() or str(Path.home())
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Choose / create measurements database", start,
            "SQLite database (*.db *.sqlite);;All files (*.*)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if chosen:
            self._db_input.setText(chosen)

    def _on_save(self) -> None:
        watch_text = self._watch_input.text().strip()
        share_text = self._share_input.text().strip()
        db_text = self._db_input.text().strip()
        if not watch_text or not share_text or not db_text:
            self._hint.setText("All three paths are required.")
            return
        try:
            self._watch_root = Path(watch_text)
            self._shared_root = Path(share_text)
            self._db_path = Path(db_text)
        except Exception as e:
            self._hint.setText(f"Invalid path: {e}")
            return
        self.accept()

    def watch_root(self) -> Path:
        return self._watch_root

    def shared_root(self) -> Path:
        return self._shared_root

    def db_path(self) -> Path:
        return self._db_path


# ------------------------------------------------------------------ Slot canvas


class _SlotCanvas(_DropCanvas):
    """Compact drop slot used in the 4×2 location grid. Clicking the slot
    bubbles a `clicked` signal so the parent can switch active location."""

    clicked = pyqtSignal(str, str)  # (code, role)  e.g. ("TL", "ball")

    def __init__(self, code: str, role: str, *, size: tuple[int, int] = (130, 160)) -> None:
        super().__init__(role=role.title(), hint=f"{code} {role}")
        self._code = code
        self._role = role  # "ball" or "pad"
        self.setFixedSize(*size)

    def mousePressEvent(self, e) -> None:  # type: ignore[override]
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._code, self._role)
        super().mousePressEvent(e)


# ------------------------------------------------------------------ Mode select


class _ModeSelectDialog(QDialog):
    """Pops up immediately after LOT confirm. Operator picks how to feed the
    measurement pipeline: one location at a time, or all four together."""

    SINGLE = "single"
    BATCH = "batch"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode: str | None = None

        self.setWindowTitle("Choose mode")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        wrapper = QWidget(self)
        wrapper.setObjectName("backdrop")
        wrapper.setStyleSheet("#backdrop { background: rgba(15, 23, 42, 0.55); }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(wrapper)

        wrap_layout = QVBoxLayout(wrapper)
        wrap_layout.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            "#card { background: #ffffff; border-radius: 14px;"
            " border: 1px solid #e2e8f0; }"
        )
        card.setFixedWidth(560)

        card_v = QVBoxLayout(card)
        card_v.setContentsMargins(28, 26, 28, 24)
        card_v.setSpacing(14)

        title = QLabel("Choose measurement mode")
        title.setStyleSheet(
            "QLabel { color: #0f172a; font-size: 22px; font-weight: 700; }"
        )
        subtitle = QLabel(
            "How would you like to fuse and measure the four locations?"
        )
        subtitle.setStyleSheet("QLabel { color: #64748b; font-size: 12px; }")
        subtitle.setWordWrap(True)
        card_v.addWidget(title)
        card_v.addWidget(subtitle)
        card_v.addSpacing(4)

        # Two large mode cards side by side.
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        def make_card(label: str, hint: str, mode: str) -> QPushButton:
            btn = QPushButton(f"{label}\n\n{hint}")
            btn.setMinimumHeight(140)
            btn.setStyleSheet(
                "QPushButton {"
                " background: #f8fafc; color: #0f172a;"
                " border: 2px solid #e2e8f0; border-radius: 12px;"
                " padding: 18px 16px; text-align: left; font-size: 13px;"
                " font-weight: 500;"
                "}"
                "QPushButton:hover {"
                " background: #eef2ff; border-color: #818cf8; color: #4338ca;"
                "}"
                "QPushButton:pressed { background: #e0e7ff; }"
            )
            btn.clicked.connect(lambda: self._pick(mode))
            return btn

        single_btn = make_card(
            "🎯  Per location",
            "Drop a pair into the slots, fuse, see the result, repeat for the "
            "next location. Best when you want to review each location before "
            "moving on.",
            self.SINGLE,
        )
        batch_btn = make_card(
            "⚡  Batch (all 4)",
            "Drop pairs for every location first, then click Fuse once. "
            "Results appear in a single pop-up to review and confirm together.",
            self.BATCH,
        )
        cards_row.addWidget(single_btn)
        cards_row.addWidget(batch_btn)
        card_v.addLayout(cards_row)

        # Centre card.
        h_center = QHBoxLayout()
        h_center.addStretch(1)
        h_center.addWidget(card)
        h_center.addStretch(1)
        wrap_layout.addStretch(1)
        wrap_layout.addLayout(h_center)
        wrap_layout.addStretch(2)

    def showEvent(self, e) -> None:  # type: ignore[override]
        super().showEvent(e)
        if self.parent() is not None:
            self.setGeometry(self.parent().geometry())  # type: ignore[union-attr]

    def _pick(self, mode: str) -> None:
        self._mode = mode
        self.accept()

    def chosen_mode(self) -> str | None:
        return self._mode


# ------------------------------------------------------------------ Batch results popup


class _BatchResultsDialog(QDialog):
    """Popup shown after a batch fuse: 2x2 grid of overlay thumbnails, one per
    location, plus a per-location measurement summary. Operator clicks
    Confirm to accept all measurements, or Cancel to discard them."""

    def __init__(
        self,
        results: dict[str, dict[str, Any]],
        unit: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._results = results
        self.setWindowTitle("Batch measurement — review")
        self.setModal(True)
        self.setMinimumSize(960, 720)
        self.setStyleSheet(
            "QDialog { background: #f1f5f9; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("Review batch measurements")
        title.setStyleSheet(
            "QLabel { color: #0f172a; font-size: 18px; font-weight: 700; }"
        )
        subtitle = QLabel(
            f"{len(results)} of 4 location(s) measured — confirm to save, "
            "or cancel to redo."
        )
        subtitle.setStyleSheet("QLabel { color: #64748b; font-size: 12px; }")
        root.addWidget(title)
        root.addWidget(subtitle)

        # 2x2 grid of result tiles.
        grid_widget = QWidget()
        grid = QHBoxLayout(grid_widget)
        grid.setSpacing(12)

        col_left = QVBoxLayout()
        col_right = QVBoxLayout()
        col_left.setSpacing(12)
        col_right.setSpacing(12)
        # Top: TL, TR. Bottom: BL, BR.
        layout_map = {
            "TL": col_left, "BL": col_left,
            "TR": col_right, "BR": col_right,
        }

        scale = 1.0 / 25.4 if unit == "mil" else 1.0
        u = "mil" if unit == "mil" else "µm"

        for code in LOCATION_ORDER:
            tile = self._build_tile(code, results.get(code), scale, u)
            layout_map[code].addWidget(tile)
        col_left.addStretch(1)
        col_right.addStretch(1)

        grid.addLayout(col_left)
        grid.addLayout(col_right)
        root.addWidget(grid_widget, 1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("danger")
        cancel.setMinimumHeight(36)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        btn_row.addStretch(1)
        confirm = QPushButton("✓  Confirm results")
        confirm.setObjectName("success")
        confirm.setMinimumHeight(36)
        confirm.clicked.connect(self.accept)
        btn_row.addWidget(confirm)
        root.addLayout(btn_row)

    def _build_tile(
        self,
        code: str,
        result: dict[str, Any] | None,
        scale: float,
        unit_str: str,
    ) -> QWidget:
        tile = QFrame()
        tile.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #e2e8f0;"
            " border-radius: 10px; }"
        )
        v = QVBoxLayout(tile)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        head = QLabel(f"<b>{code}</b> &nbsp; <span style='color:#64748b'>"
                      f"{LOCATION_LABELS.get(code, code)}</span>")
        head.setStyleSheet("QLabel { font-size: 13px; color: #0f172a; }")
        v.addWidget(head)

        if result is None or not result.get("pads"):
            empty = QLabel("— not measured —")
            empty.setStyleSheet(
                "QLabel { color: #94a3b8; padding: 30px; }"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(empty)
            return tile

        # Render the overlay pixmap.
        pads = result["pads"]
        fused = result["fused"]
        overlay = draw_multi_pad_overlay(fused, pads, unit=("mil" if scale != 1.0 else "um"))
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setStyleSheet("QLabel { border: 1px solid #cbd5e1; border-radius: 6px; }")
        img_label.setPixmap(MainWindow._bgr_to_pixmap(overlay, max_w=380, max_h=240))
        v.addWidget(img_label)

        # Compact measurement summary
        rows = []
        for i, m in enumerate(pads, start=1):
            pad_dims = f"{m.width_um * scale:.2f} × {m.height_um * scale:.2f}"
            ball_str = (
                f"{m.ball.diameter_um * scale:.2f}" if m.ball else "—"
            )
            gap_str = (
                f"{m.gap.min_gap_um * scale:.2f}/{m.gap.mean_gap_um * scale:.2f}"
                if m.gap else "—"
            )
            rows.append(
                f"<tr>"
                f"<td style='padding:1px 6px;color:#16a34a'>#{i}</td>"
                f"<td style='padding:1px 6px'>{pad_dims}</td>"
                f"<td style='padding:1px 6px;color:#a23'>{ball_str}</td>"
                f"<td style='padding:1px 6px;color:#a14ba1'>{gap_str}</td>"
                f"</tr>"
            )
        head_row = (
            f"<tr style='color:#64748b'>"
            f"<th style='text-align:left;padding:1px 6px'>#</th>"
            f"<th style='text-align:left;padding:1px 6px'>PAD W×H ({unit_str})</th>"
            f"<th style='text-align:left;padding:1px 6px'>BALL d</th>"
            f"<th style='text-align:left;padding:1px 6px'>GAP min/mean</th>"
            f"</tr>"
        )
        tbl = QLabel(
            f"<table style='border-collapse:collapse;font-size:10px;"
            f"font-family:Consolas,monospace'>"
            f"{head_row}{''.join(rows)}</table>"
        )
        tbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(tbl)
        return tile


# ------------------------------------------------------------------ Main window


class MainWindow(QMainWindow):
    """Operator workflow: Badge + LOT → 3 shots × 4 locations → drag into measurement slots → Confirm."""

    _file_ready_signal = pyqtSignal(str)

    def __init__(
        self,
        settings: Settings,
        lot_client: LotClient,
        settings_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._settings_path = settings_path
        self._lot_client = lot_client
        self._store = ImageStore(
            shared_root=settings.storage.shared_root,
            compute_sha256=settings.storage.compute_sha256,
        )
        # Measurements DB — path comes from settings (default: ./logs).
        # Operator can repoint this to a share-folder UNC path via the
        # Settings dialog so multiple stations + the web monitor share
        # history.
        self._db = MeasurementDB(settings.storage.db_path)
        self._watcher: FileWatcher | None = None
        self._fetch_worker: _FetchLotWorker | None = None

        self._current_lot: LotDetail | None = None
        self._operator_badge: str = ""

        self._staged: dict[str, list[Path]] = {code: [] for code in LOCATION_ORDER}
        self._current_location: str = LOCATION_ORDER[0]
        self._selection_state: dict[tuple[str, Path], bool] = {}

        self._measurement: PadMeasurement | None = None    # primary (first/best) pad
        self._measurements: list[PadMeasurement] = []      # all detected pads
        self._last_fused: np.ndarray | None = None      # for display
        self._last_focus_ball: np.ndarray | None = None # source frame for ball detection
        self._last_focus_pad: np.ndarray | None = None  # source frame for pad detection
        self._last_pixel_size_um: float = 1.0
        self._display_unit: str = "um"   # "um" or "mil"

        # Measurement mode + batch state. In batch mode the operator drags one
        # pair per location; the pair gets stashed when they switch location
        # and restored on return. A single Fuse click then runs every paired
        # location through the pipeline.
        self._batch_mode: bool = False
        self._batch_pairs: dict[str, dict[str, Path | None]] = {
            code: {"ball": None, "pad": None} for code in LOCATION_ORDER
        }
        # After batch fuse: per-location measurements list.
        self._batch_measurements: dict[str, list[PadMeasurement]] = {}

        self.setWindowIcon(make_app_icon())
        self._build_ui()
        self._apply_modern_theme()
        # Modal-style overlay shown during analysis (backdrop + spinner).
        # Created AFTER `_build_ui` so its parent (`central` via the scroll
        # area) is already laid out.
        self._processing_overlay = _ProcessingOverlay(self)
        self._file_ready_signal.connect(self._on_file_ready)
        self._update_input_state()
        # Show the sign-in gate the first time the window is shown. Done via a
        # one-shot flag to avoid re-prompting on every show event (e.g. when
        # the OS hides+shows the window).
        self._gate_shown = False

    def _apply_modern_theme(self) -> None:
        """Apply a clean 2026-era light theme: soft slate background, indigo
        accent, rounded corners, generous padding, semantic state colors.
        Stylesheet covers ALL standard widgets so every dialog/menu is
        consistent without per-widget styling.
        """
        self.setStyleSheet(_MODERN_QSS)

    # ---------- UI construction ----------

    def _build_ui(self) -> None:
        self.setWindowTitle(f"High Scope Capture  v{APP_VERSION}")
        self.resize(1340, 880)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(8)

        # ===== TOP: canvases + result panel =====
        # Layout: [Focus Ball ↑]  [    Fused    ]  [Result panel]
        #         [Focus Pad  ↓]   <stacked col>     <fixed size>
        # Each title label is locked to a fixed height so the stacked side
        # column (2 panels + 2 titles + 2 spacers) ends up exactly the same
        # tall as the Fused/Result columns (1 panel + 1 title + 1 spacer).
        title_h = 22
        spacing = 2
        # Compact sizes that survive Windows DPI scaling up to 150% on a 1080p
        # monitor. Math invariants kept so the stacked side column equals the
        # Fused/Result column heights exactly.
        main_w, main_h = 600, 450        # Fused canvas
        side_h = (main_h - title_h - spacing) // 2   # = 213
        side_w = int(round(side_h * 4 / 3))          # = 284, keeps 4:3 aspect
        result_w, result_h = 280, main_h
        canvas_style = "QLabel { background: #222; border: 1px solid #555; }"

        def _wrap_canvas(title: str, label: QLabel, canvas_h: int) -> QWidget:
            box = QWidget()
            # Lock the wrapper to title + spacing + canvas height — Qt's QVBoxLayout
            # would otherwise add internal margins and let stretch policies compress
            # whichever child happens to lose the fight (typically the bottom one).
            box.setFixedHeight(title_h + spacing + canvas_h)
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(spacing)
            t = QLabel(title)
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setFixedHeight(title_h)
            f = t.font()
            f.setBold(True)
            t.setFont(f)
            v.addWidget(t)
            v.addWidget(label, 0, Qt.AlignmentFlag.AlignCenter)
            return box

        # Side preview — large readonly canvas that mirrors whatever
        # thumbnail the operator currently has selected in the captures
        # grid. Replaces the old Focus-Ball + Focus-Pad drop canvases (drops
        # now go directly into the per-location slot grid in the centre).
        side_total_h = 2 * (title_h + spacing + side_h)
        self._selected_preview = QLabel()
        self._selected_preview.setFixedSize(side_w, side_total_h - title_h - spacing)
        self._selected_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._selected_preview.setStyleSheet(
            "QLabel { background: #0f172a; border: 1px solid #1e293b;"
            " border-radius: 8px; color: #64748b; font-size: 11px; }"
        )
        self._selected_preview.setText(
            "\nselected image\n\n(click a thumbnail below)"
        )
        # Keep the legacy slot-canvas references as hidden no-op drop targets.
        # Code paths that draw ball-only / pad-only overlays still call into
        # these (e.g. after fuse), but the drawn pixmaps simply aren't shown.
        self._focus_ball_preview = _DropCanvas("Focus Ball", "")
        self._focus_ball_preview.setFixedSize(1, 1)
        self._focus_ball_preview.setVisible(False)
        self._focus_pad_preview = _DropCanvas("Focus Pad", "")
        self._focus_pad_preview.setFixedSize(1, 1)
        self._focus_pad_preview.setVisible(False)

        side_col_widget = _wrap_canvas(
            "Selected image", self._selected_preview,
            side_total_h - title_h - spacing,
        )

        # Fused (main canvas)
        self._fused_preview = _ClickableLabel()
        self._fused_preview.setFixedSize(main_w, main_h)
        self._fused_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fused_preview.setToolTip("Click on the ball to refine detection")
        self._fused_preview.setCursor(Qt.CursorShape.CrossCursor)
        self._fused_preview.setStyleSheet(canvas_style)
        self._fused_preview.clicked.connect(self._on_fused_clicked)

        # Result panel — slightly shorter to leave room for an action strip
        # (Fuse&measure + unit toggle) directly below it inside the same column.
        result_panel_h = result_h - 88            # leave 88 px for the strip
        action_strip_h = 80                        # title + buttons
        self._result_panel = QLabel()
        self._result_panel.setFixedSize(result_w, result_panel_h)
        self._result_panel.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._result_panel.setWordWrap(True)
        self._result_panel.setStyleSheet(
            "QLabel { background: #ffffff; border: 1px solid #e2e8f0;"
            " border-radius: 10px; padding: 12px;"
            " font-family: 'JetBrains Mono', 'Cascadia Mono', Consolas, monospace;"
            " font-size: 11px; color: #1e293b; }"
        )
        self._result_panel.setText(
            '<span style="color:#94a3b8">No measurement yet</span>'
        )

        # Right-column container: title → result panel → action strip.
        right_col_widget = QWidget()
        right_col_widget.setFixedSize(result_w, result_h)
        right_v = QVBoxLayout(right_col_widget)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(spacing)
        right_title = QLabel("Measurement detail")
        right_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_title.setFixedHeight(title_h)
        rt_f = right_title.font(); rt_f.setBold(True); right_title.setFont(rt_f)
        right_v.addWidget(right_title)
        right_v.addWidget(self._result_panel, 0, Qt.AlignmentFlag.AlignCenter)

        # ----- action strip (replaces the old "Measurement controls" groupbox) -----
        action_card = QFrame()
        action_card.setFixedSize(result_w, action_strip_h)
        action_card.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #e2e8f0;"
            " border-radius: 10px; }"
        )
        ac_v = QVBoxLayout(action_card)
        ac_v.setContentsMargins(10, 8, 10, 8)
        ac_v.setSpacing(6)

        self._measure_btn = QPushButton("⚡  Fuse && measure pad")
        self._measure_btn.setObjectName("primary")
        self._measure_btn.clicked.connect(self._on_measure_clicked)
        self._measure_btn.setMinimumHeight(28)
        ac_v.addWidget(self._measure_btn)

        # Segmented unit toggle — [ µm ] [ mil ]
        self._unit_um_btn = QPushButton("µm")
        self._unit_um_btn.setObjectName("_unit_um_btn")
        self._unit_um_btn.setCheckable(True)
        self._unit_um_btn.setChecked(True)
        self._unit_um_btn.clicked.connect(lambda: self._set_unit("um"))
        self._unit_mil_btn = QPushButton("mil")
        self._unit_mil_btn.setObjectName("_unit_mil_btn")
        self._unit_mil_btn.setCheckable(True)
        self._unit_mil_btn.clicked.connect(lambda: self._set_unit("mil"))
        unit_row = QHBoxLayout()
        unit_row.setContentsMargins(0, 0, 0, 0)
        unit_row.setSpacing(0)
        unit_row.addWidget(QLabel("Display:"))
        unit_row.addSpacing(6)
        unit_row.addWidget(self._unit_um_btn, 1)
        unit_row.addWidget(self._unit_mil_btn, 1)
        unit_row.addStretch(0)
        ac_v.addLayout(unit_row)

        # Vestigial widgets — `Show all candidates` / `Show pad measurement`
        # were removed from the UI, but several handlers still toggle their
        # visibility. We use a `_HiddenButton` subclass that ignores
        # `setVisible(True)` so the dead widgets can never reappear (whether
        # as a child overlapping the Fuse button or as a top-level python
        # window).
        class _HiddenButton(QPushButton):
            def setVisible(self, _v: bool) -> None:  # type: ignore[override]
                super().setVisible(False)

        self._show_pad_btn = _HiddenButton(action_card)
        self._show_pad_btn.setVisible(False)
        self._show_pad_btn.clicked.connect(self._on_show_pad_clicked)
        self._show_ball_btn = _HiddenButton(action_card)
        self._show_ball_btn.setVisible(False)
        self._show_ball_btn.clicked.connect(self._on_show_ball_clicked)
        # Legacy alias: existing code may still reference this checkbox.
        self._unit_checkbox = QCheckBox(action_card)
        self._unit_checkbox.setVisible(False)

        right_v.addWidget(action_card, 0, Qt.AlignmentFlag.AlignCenter)

        # Init location-state containers BEFORE the slot grid is built —
        # `_build_location_row` mutates `_loc_buttons` / `_loc_slots`.
        self._loc_group = QButtonGroup(self)
        self._loc_buttons: dict[str, QPushButton] = {}
        self._loc_slots: dict[tuple[str, str], _SlotCanvas] = {}
        self._batch_status_lbl = QLabel(parent=self)
        self._batch_status_lbl.setVisible(False)

        # ----- Central widget: 4-location pair-slot grid (replaces Fused) -----
        # The Fused canvas (`self._fused_preview`) is still constructed and
        # used internally for redraw paths, but is NOT added to the layout —
        # the operator-facing surface here is the 2×2 grid of TL/TR/BL/BR
        # cards, each holding ball + pad drop slots.
        slots_widget = QWidget()
        slots_widget.setFixedSize(main_w, main_h)
        slots_widget.setStyleSheet(
            "QWidget { background: transparent; }"
        )
        slots_grid = QHBoxLayout(slots_widget)
        slots_grid.setContentsMargins(0, 0, 0, 0)
        slots_grid.setSpacing(8)
        # Two columns, each holding 2 location cards stacked vertically.
        col_a = QVBoxLayout()
        col_a.setSpacing(8)
        col_b = QVBoxLayout()
        col_b.setSpacing(8)
        layout_for_code = {"TL": col_a, "BL": col_a, "TR": col_b, "BR": col_b}
        for code in LOCATION_ORDER:
            layout_for_code[code].addWidget(self._build_location_row(code))
        col_a.addStretch(0)
        col_b.addStretch(0)
        slots_grid.addLayout(col_a)
        slots_grid.addLayout(col_b)

        canvases_row = QHBoxLayout()
        canvases_row.setSpacing(10)
        canvases_row.addStretch(1)
        canvases_row.addWidget(side_col_widget)
        canvases_row.addWidget(_wrap_canvas(
            "Pair slots — drop ball + pad per location",
            slots_widget, main_h,
        ))
        canvases_row.addWidget(right_col_widget)
        canvases_row.addStretch(1)
        root.addLayout(canvases_row)

        # ===== MIDDLE: split horizontally =====
        # Left = operator workflow (Badge → LOT → location → captures grid)
        # Right = measurement controls + result panel
        middle_row = QHBoxLayout()
        middle_row.setSpacing(12)

        # ---- Left column: workflow ----
        left_col = QVBoxLayout()
        left_col.setSpacing(6)

        # Badge + LOT — DISPLAY ONLY here. Values are entered through the
        # startup gate (modal popup) and are not editable from the main UI.
        badge_lot_row = QHBoxLayout()
        badge_lot_row.addWidget(QLabel("Badge:"))
        self._badge_input = QLineEdit()
        self._badge_input.setPlaceholderText("—")
        self._badge_input.setMaxLength(32)
        self._badge_input.setMaximumWidth(140)
        self._badge_input.setReadOnly(True)
        self._badge_input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._badge_input.setStyleSheet(
            "QLineEdit { background: #f1f5f9; color: #334155;"
            " border: 1px solid #e2e8f0; }"
        )
        badge_lot_row.addWidget(self._badge_input)
        badge_lot_row.addSpacing(12)
        badge_lot_row.addWidget(QLabel("LOT ID:"))
        self._lot_input = QLineEdit()
        self._lot_input.setPlaceholderText("—")
        self._lot_input.setReadOnly(True)
        self._lot_input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._lot_input.setStyleSheet(
            "QLineEdit { background: #f1f5f9; color: #334155;"
            " border: 1px solid #e2e8f0; }"
        )
        badge_lot_row.addWidget(self._lot_input, 1)
        # Fetch button no longer used in main UI — gate handles fetching.
        self._fetch_btn = QPushButton("Fetch")
        self._fetch_btn.setObjectName("primary")
        self._fetch_btn.setVisible(False)
        self._fetch_btn.clicked.connect(self._on_fetch_clicked)
        badge_lot_row.addWidget(self._fetch_btn)
        left_col.addLayout(badge_lot_row)

        # LOT info
        self._lot_info_label = QLabel("LOT info: —")
        self._lot_info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lot_info_label.setWordWrap(True)
        self._lot_info_label.setStyleSheet(
            "QLabel { padding: 10px 12px; background: #ffffff;"
            " border: 1px solid #e2e8f0; border-radius: 8px; color: #475569; }"
        )
        left_col.addWidget(self._lot_info_label)

        # The 4-location pair slot grid lives in the central canvas area
        # (built earlier). Containers above were initialised before the grid.

        # Captures grid
        self._preview_group = QGroupBox("Captures at Top-left")
        prev_layout = QVBoxLayout(self._preview_group)
        self._preview_list = _DragThumbnailList()
        self._preview_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._preview_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._preview_list.setMovement(QListWidget.Movement.Static)
        self._preview_list.setIconSize(QSize(*THUMBNAIL_SIZE))
        self._preview_list.setGridSize(QSize(THUMBNAIL_SIZE[0] + 24, THUMBNAIL_SIZE[1] + 44))
        # Single-select: operator picks one image, drags it into a slot.
        # The selection auto-clears after a successful drop so the next pick
        # starts cleanly (no lingering highlights).
        self._preview_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._preview_list.setUniformItemSizes(True)
        self._preview_list.setSpacing(6)
        self._preview_list.setDragEnabled(True)
        self._preview_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._preview_list.itemSelectionChanged.connect(self._on_selection_changed)
        prev_layout.addWidget(self._preview_list, 1)

        self._sel_hint = QLabel("Pick exactly 3 — click to toggle.  Drag into slots on the right to measure.")
        self._sel_hint.setStyleSheet("color: #666;")
        prev_layout.addWidget(self._sel_hint)
        left_col.addWidget(self._preview_group, 1)

        # The Measurement-controls groupbox used to live here; the Fuse &
        # measure button + unit toggle have moved up into the right column
        # (next to the result panel) where they're spatially adjacent to the
        # measurement they affect.

        # Pack the workflow column directly into the row.
        left_widget = QWidget()
        left_widget.setLayout(left_col)
        middle_row.addWidget(left_widget, 1)
        root.addLayout(middle_row, 1)

        # ===== BOTTOM: action row =====
        # Arm-for-capture is now automatic — fired the moment the operator
        # signs in via the startup gate. Kept as a hidden widget so the rest
        # of the codebase (`_update_input_state`, etc.) can still toggle its
        # state without conditional checks. Parented to `central` so a stray
        # `setVisible(True)` won't promote it to a free-floating top-level
        # window (Qt's default for orphan widgets).
        self._arm_btn = QPushButton(central)
        self._arm_btn.setVisible(False)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self._cancel_btn = QPushButton("Cancel session")
        self._cancel_btn.setObjectName("danger")
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        action_row.addWidget(self._cancel_btn)

        action_row.addStretch(1)
        self._arm_state = QLabel("● Disarmed")
        self._arm_state.setStyleSheet(
            "QLabel { color: #94a3b8; background: #f1f5f9;"
            " border: 1px solid #e2e8f0; border-radius: 999px;"
            " padding: 4px 14px; font-weight: 600; }"
        )
        action_row.addWidget(self._arm_state)
        action_row.addSpacing(8)

        self._confirm_btn = QPushButton("✓  Confirm && Save")
        self._confirm_btn.setObjectName("success")
        self._confirm_btn.clicked.connect(self._on_confirm_clicked)
        action_row.addWidget(self._confirm_btn)
        root.addLayout(action_row)

        # Menu + status
        open_shared = QAction("Open shared folder", self)
        open_shared.triggered.connect(self._open_shared_folder)
        self.menuBar().addAction(open_shared)

        # Settings popup — edit the read + share folders without touching
        # config/settings.yaml by hand.
        settings_action = QAction("⚙  Settings", self)
        settings_action.triggered.connect(self._open_settings_dialog)
        self.menuBar().addAction(settings_action)

        # Lock minimum size on the CONTENT so layouts never collapse / overlap.
        # When the window is smaller than this, the QScrollArea below shows
        # scrollbars instead of squeezing widgets together. Sized for the
        # canvas + workflow + action row to all fit at their natural sizes.
        # Width: side(284) + spacing(10) + fused(600) + spacing(10) + result(280)
        #        + margins ≈ 1230
        # Height: top(474) + middle min(220) + action(44) + margins(30) ≈ 768
        central.setMinimumSize(1230, 780)

        # Scroll area: when the OS window is smaller than the minimum content
        # size (e.g. 1080p with 150% DPI scaling, or a deliberately resized
        # window), scrollbars appear instead of widgets clipping or hiding the
        # action row.
        scroll = QScrollArea()
        scroll.setWidget(central)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.setCentralWidget(scroll)
        # Window itself can be small — scroll handles the overflow.
        self.setMinimumSize(800, 500)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Enter Badge number to begin")
        self._badge_input.setFocus()

    # ---------- Badge ----------

    def _on_badge_text_changed(self, _: str) -> None:
        if not self._badge_input.text().strip():
            self._operator_badge = ""
            self._clear_lot_info()
        self._update_input_state()

    def _on_badge_confirmed(self) -> None:
        badge = self._badge_input.text().strip().upper()
        if not badge:
            return
        self._operator_badge = badge
        self._badge_input.setText(badge)
        self._update_input_state()
        self._lot_input.setFocus()

    # ---------- Input-state machine ----------

    def _update_input_state(self) -> None:
        armed = self._watcher is not None
        have_badge = bool(self._operator_badge)
        have_lot = self._current_lot is not None
        have_any_staged = any(self._staged[c] for c in LOCATION_ORDER)

        # Badge / LOT / Fetch are display-only in the main UI now; values
        # come from the startup-gate popup. Keep them enabled so the text
        # renders cleanly (read-only is set on the widgets themselves).
        self._badge_input.setEnabled(True)
        self._lot_input.setEnabled(True)
        self._fetch_btn.setEnabled(False)

        self._arm_btn.setEnabled(have_badge and have_lot and not armed)
        # Confirm enables once at least one location has BOTH ball + pad in
        # the slot grid AND a measurement has been produced (per-location or
        # batch). Watching is allowed to stay armed — operator can confirm and
        # immediately roll into the next LOT.
        any_pair = any(
            p.get("ball") is not None and p.get("pad") is not None
            for p in self._batch_pairs.values()
        )
        have_any_measurement = (
            bool(self._measurements) or bool(self._batch_measurements)
        )
        self._cancel_btn.setEnabled(armed or have_any_staged or any_pair)
        self._confirm_btn.setEnabled(any_pair and have_any_measurement)

        # Counter labels stay static ("TL · Top-left" etc.) — they're
        # display-only since location buttons are no longer clickable.
        for code, btn in self._loc_buttons.items():
            btn.setText(f"{code}  ·  {LOCATION_LABELS[code]}")
            btn.setEnabled(False)

        if self._batch_mode:
            # Stash any pair currently in the slots first, then count.
            self._save_current_pair_to_location()
            n_paired = sum(
                1 for p in self._batch_pairs.values()
                if p.get("ball") is not None and p.get("pad") is not None
            )
            self._measure_btn.setEnabled(n_paired >= 1)
            self._measure_btn.setText(
                f"⚡  Fuse && measure ({n_paired}/4)" if n_paired < 4
                else "⚡  Fuse && measure all 4"
            )
        else:
            has_ball_pair = (
                self._focus_ball_preview.path() is not None
                and self._focus_pad_preview.path() is not None
            )
            self._measure_btn.setEnabled(has_ball_pair)
            self._measure_btn.setText("⚡  Fuse && measure pad")

        self._update_selection_hint()

    def _update_selection_hint(self) -> None:
        n = len(self._preview_list.selectedItems())
        total = self._preview_list.count()
        if n < SHOTS_PER_LOCATION:
            self._sel_hint.setText(
                f"Select {SHOTS_PER_LOCATION - n} more  "
                f"({n} / {SHOTS_PER_LOCATION} selected, {total} captured) — drag into slots to measure"
            )
            self._sel_hint.setStyleSheet("QLabel { color: #64748b; padding: 4px 0; }")
        elif n == SHOTS_PER_LOCATION:
            self._sel_hint.setText(
                f"✓  {n} / {SHOTS_PER_LOCATION} selected ({total} captured) — drag into slots to measure"
            )
            self._sel_hint.setStyleSheet(
                "QLabel { color: #166534; font-weight: 600; padding: 4px 0; }"
            )
        else:
            self._sel_hint.setText(
                f"Too many selected — deselect {n - SHOTS_PER_LOCATION}  ({n} / {SHOTS_PER_LOCATION})"
            )
            self._sel_hint.setStyleSheet(
                "QLabel { color: #b91c1c; font-weight: 600; padding: 4px 0; }"
            )

    # ---------- Fetch LOT ----------

    def _on_fetch_clicked(self) -> None:
        lot_id = self._lot_input.text().strip()
        if not lot_id:
            self.statusBar().showMessage("Enter a LOT ID first", 3000)
            return
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        self._fetch_btn.setEnabled(False)
        self.statusBar().showMessage(f"Fetching {lot_id} from MES ...")
        self._fetch_worker = _FetchLotWorker(self._lot_client, lot_id)
        self._fetch_worker.succeeded.connect(self._on_fetch_success)
        self._fetch_worker.failed.connect(self._on_fetch_failed)
        self._fetch_worker.finished.connect(self._update_input_state)
        self._fetch_worker.start()

    @pyqtSlot(object)
    def _on_fetch_success(self, detail: LotDetail) -> None:
        self._current_lot = detail
        parts = [
            f"<b style='color:#16a34a'>LOT</b> {detail.lot_id or '—'}",
            f"<b style='color:#475569'>MPC</b> {detail.mpc or '—'}",
            f"<b style='color:#475569'>Loc</b> {detail.lot_location or '—'}",
            f"<b style='color:#475569'>Pkg</b> {detail.package or '—'}",
            f"<b style='color:#475569'>QS</b> {detail.qs or '—'}",
            f"<b style='color:#475569'>Bonding</b> {detail.bonding_running or '—'}",
        ]
        self._lot_info_label.setText(
            "<span style='color:#cbd5e1'>  ·  </span>".join(parts)
        )
        self._lot_info_label.setStyleSheet(
            "QLabel { padding: 10px 14px; background: #f0fdf4;"
            " border: 1px solid #86efac; border-radius: 8px; color: #14532d; }"
        )
        self._update_input_state()
        self.statusBar().showMessage(f"LOT {detail.lot_id} loaded — press Arm to start", 5000)

    @pyqtSlot(str, str)
    def _on_fetch_failed(self, title: str, detail: str) -> None:
        self._clear_lot_info(mark_error=True)
        QMessageBox.warning(self, title, detail)
        self.statusBar().showMessage(title, 5000)

    def _clear_lot_info(self, *, mark_error: bool = False) -> None:
        self._current_lot = None
        self._lot_info_label.setText(
            "<span style='color:#94a3b8'>LOT info — fetch to begin</span>"
        )
        self._lot_info_label.setStyleSheet(
            "QLabel { padding: 10px 14px; background: #fef2f2;"
            " border: 1px solid #fca5a5; border-radius: 8px; color: #7f1d1d; }"
            if mark_error else
            "QLabel { padding: 10px 14px; background: #ffffff;"
            " border: 1px solid #e2e8f0; border-radius: 8px; color: #475569; }"
        )
        self._update_input_state()

    # ---------- Location selection ----------

    def _set_current_location(self, code: str) -> None:
        if code == self._current_location:
            self._loc_buttons[code].setChecked(True)
            return
        self._current_location = code
        # Update active highlights on the location cards.
        self._highlight_active_card()
        for c, btn in self._loc_buttons.items():
            btn.setChecked(c == code)
        self._preview_group.setTitle(f"Captures at {LOCATION_LABELS[code]}")
        self._reload_preview_grid()
        # Mirror this location's pair into the top Focus-Ball / Focus-Pad
        # canvases. Pair is stored persistently in `_batch_pairs[code]`,
        # populated by drops into the slot grid.
        self._restore_pair_from_location(code)
        # If we have measurement results for this location (batch fuse done),
        # swap the main overlay + previews.
        if code in self._batch_measurements and self._batch_measurements[code]:
            self._show_batch_location(code)

    def _show_batch_location(self, code: str) -> None:
        """Re-load the source images for `code` and re-render its overlay."""
        pair = self._batch_pairs.get(code, {})
        ball_path = pair.get("ball")
        pad_path = pair.get("pad")
        pads = self._batch_measurements.get(code)
        if not (ball_path and pad_path and pads):
            return
        try:
            focus_ball = load_as_bgr(ball_path)
            focus_pad = load_as_bgr(pad_path)
            fused = focus_stack(focus_ball, focus_pad)
        except Exception:
            log.exception("could not reload batch images for %s", code)
            return
        u = self._display_unit
        self._measurement = pads[0]
        self._measurements = pads
        self._last_fused = fused
        self._last_focus_ball = focus_ball
        self._last_focus_pad = focus_pad
        self._set_canvas_pixmap(
            self._fused_preview, draw_multi_pad_overlay(fused, pads, unit=u),
        )
        self._set_canvas_pixmap(
            self._focus_ball_preview,
            draw_multi_ball_only_overlay(focus_ball, pads, unit=u),
        )
        self._set_canvas_pixmap(
            self._focus_pad_preview,
            draw_multi_pad_only_overlay(focus_pad, pads, unit=u),
        )
        self._result_panel.setText(self._format_batch_result(code))

    def _selected_count(self, code: str) -> int:
        if code != self._current_location:
            return sum(
                1 for p in self._staged[code]
                if self._selection_state.get((code, p), False)
            )
        return len(self._preview_list.selectedItems())

    def _reload_preview_grid(self) -> None:
        self._preview_list.blockSignals(True)
        self._preview_list.clear()
        for path in self._staged[self._current_location]:
            self._add_thumbnail_item(path)
        for i in range(self._preview_list.count()):
            item = self._preview_list.item(i)
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            if self._selection_state.get((self._current_location, path), False):
                item.setSelected(True)
        self._preview_list.blockSignals(False)
        self._update_selection_hint()
        self._update_input_state()

    def _add_thumbnail_item(self, path: Path) -> None:
        try:
            pix = make_thumbnail(path)
        except Exception as e:
            log.exception("Failed to build thumbnail for %s", path)
            item = QListWidgetItem(f"[thumb failed] {path.name}\n{e}")
            self._preview_list.addItem(item)
            return
        item = QListWidgetItem(QIcon(pix), path.name)
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        item.setToolTip(str(path))
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self._preview_list.addItem(item)

    def _on_selection_changed(self) -> None:
        # Update the side "Selected image" preview to mirror the highlighted
        # thumbnail. Clearing selection (e.g. after a drop) blanks the preview.
        items = self._preview_list.selectedItems()
        if items:
            try:
                path_str = items[0].data(Qt.ItemDataRole.UserRole)
                path = Path(path_str)
                pix = make_thumbnail(
                    path,
                    size=(
                        self._selected_preview.width() - 4,
                        self._selected_preview.height() - 4,
                    ),
                )
                self._selected_preview.setPixmap(pix)
                self._selected_preview.setText("")
            except Exception:
                log.exception("preview render failed")
        else:
            self._selected_preview.clear()
            self._selected_preview.setText(
                "\nselected image\n\n(click a thumbnail below)"
            )
        self._update_input_state()

    def _all_locations_complete(self) -> bool:
        return all(
            self._selected_count(code) == SHOTS_PER_LOCATION for code in LOCATION_ORDER
        )

    # ---------- Arm / Cancel / Confirm ----------

    def _on_arm_clicked(self) -> None:
        if self._current_lot is None or not self._operator_badge:
            return
        if self._watcher is not None:
            return
        cap = self._settings.capture
        self._watcher = FileWatcher(
            root=cap.watch_root,
            patterns=cap.file_patterns,
            on_ready=self._watcher_callback,
            recursive=cap.recursive,
            stable_poll_ms=cap.stable_poll_ms,
            stable_required_checks=cap.stable_required_checks,
        )
        self._watcher.start()
        self._arm_state.setText(
            f"● Armed — {LOCATION_LABELS[self._current_location]}"
        )
        self._arm_state.setStyleSheet(
            "QLabel { color: #166534; background: #dcfce7;"
            " border: 1px solid #86efac; border-radius: 999px;"
            " padding: 4px 14px; font-weight: 600; }"
        )
        self._update_input_state()
        self.statusBar().showMessage(
            f"Armed — take {SHOTS_PER_LOCATION} shots for "
            f"{LOCATION_LABELS[self._current_location]}",
            0,
        )

    def _on_cancel_clicked(self) -> None:
        reply = QMessageBox.question(
            self, "Cancel session?",
            "Discard all captures, slots, and measurement?\n\n"
            "(Files in the Olympus auto-save folder are not deleted.)",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._reset_session()
        self.statusBar().showMessage("Session cancelled", 4000)
        # Re-prompt the sign-in gate so the next operator can begin a new
        # session without restarting the program. Cancelling the gate this
        # time leaves them on the empty main window (not exit).
        QTimer.singleShot(50, lambda: self._show_startup_gate(exit_on_cancel=False))

    def _on_confirm_clicked(self) -> None:
        if self._current_lot is None or not self._operator_badge:
            return

        # New workflow: save based on pair slots (one ball + one pad per
        # location). Each filled slot becomes a CaptureRecord; the matching
        # measurement (per-location for batch, or the single live
        # measurement for per-location mode) is attached as the sidecar.
        to_save: list[tuple[str, int, Path, dict[str, Any] | None]] = []
        for code in LOCATION_ORDER:
            pair = self._batch_pairs.get(code, {})
            ball = pair.get("ball")
            pad = pair.get("pad")
            if ball is None and pad is None:
                continue
            # Per-location measurement: prefer batch results, fall back to the
            # active single-pad measurement when this is the active location.
            pads_for_loc = self._batch_measurements.get(code)
            if pads_for_loc is None and code == self._current_location:
                pads_for_loc = self._measurements
            meas: dict[str, Any] | None = None
            if pads_for_loc:
                meas = {
                    "pads": [p.to_dict() for p in pads_for_loc],
                    "pad_count": len(pads_for_loc),
                }
            idx = 0
            if ball is not None:
                idx += 1
                to_save.append((code, idx, ball,
                                None if meas is None else {**meas, "role_in_pair": "FocusBall"}))
            if pad is not None:
                idx += 1
                to_save.append((code, idx, pad,
                                None if meas is None else {**meas, "role_in_pair": "FocusPad"}))

        if not to_save:
            QMessageBox.warning(
                self, "Nothing to save",
                "Drop a ball + pad pair into at least one location's slots first.",
            )
            return

        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None

        # Visual lock-out while we copy files + write sidecars — file copies
        # to a network share can take seconds, sha256 + atomic-rename adds
        # a bit more. The overlay tells the operator the click registered.
        self._confirm_btn.setEnabled(False)
        self._processing_overlay.show_with(
            f"Saving 0 of {len(to_save)} file(s) …"
        )

        saved: list[CaptureRecord] = []
        for i, (code, idx, src, meas) in enumerate(to_save, start=1):
            self._processing_overlay.set_message(
                f"[{i}/{len(to_save)}]  Saving {src.name}  →  {code}"
            )
            try:
                rec = self._store.save(
                    source=src,
                    lot_id=self._current_lot.lot_id,
                    lot_info=self._current_lot.raw,
                    operator_badge=self._operator_badge,
                    location=code,
                    index_in_location=idx,
                    measurement=meas,
                )
            except Exception as e:
                log.exception("Save failed: %s", src)
                self._processing_overlay.hide()
                self._confirm_btn.setEnabled(True)
                QMessageBox.critical(
                    self, "Save failed",
                    f"Error saving {src.name} ({code} #{idx}):\n{e}\n\n"
                    f"{len(saved)} file(s) already saved successfully.",
                )
                self._update_input_state()
                return
            saved.append(rec)

        # ---- Insert measurements + mirror, while the overlay is still up ----
        # DB write + share-folder JSON mirror happen BEFORE the success dialog
        # so the operator sees a single transition: progress → done.
        self._processing_overlay.set_message("Recording measurements to database …")
        bonding_number = (self._current_lot.bonding_running or "").strip()
        session_id: str | None = None
        try:
            per_loc_pads: dict[str, list[dict[str, Any]]] = {}
            per_loc_paths: dict[str, dict[str, Any]] = {}
            stored_lookup: dict[Path, Path] = {
                rec.source_path: rec.stored_path for rec in saved
            }
            for code in LOCATION_ORDER:
                pads = self._batch_measurements.get(code)
                if pads is None and code == self._current_location:
                    pads = self._measurements
                if pads:
                    per_loc_pads[code] = [p.to_dict() for p in pads]
                pair = self._batch_pairs.get(code, {})
                src_ball = pair.get("ball")
                src_pad = pair.get("pad")
                if src_ball or src_pad:
                    per_loc_paths[code] = {
                        "source_ball": src_ball,
                        "source_pad": src_pad,
                        "stored_ball": stored_lookup.get(src_ball) if src_ball else None,
                        "stored_pad":  stored_lookup.get(src_pad)  if src_pad  else None,
                    }
            if per_loc_pads and bonding_number:
                session_id = self._db.insert_lot(
                    lot_id=self._current_lot.lot_id,
                    bonding_number=bonding_number,
                    operator_badge=self._operator_badge,
                    per_location_pads=per_loc_pads,
                    per_location_paths=per_loc_paths,
                    lot_info=self._current_lot.raw,
                    app_version=APP_VERSION,
                )
                self._processing_overlay.set_message(
                    "Mirroring record to shared folder …"
                )
                try:
                    self._db.mirror_session_to_share(
                        session_id, self._settings.storage.shared_root,
                    )
                except Exception:
                    log.exception("DB session mirror to share failed")
        except Exception:
            log.exception("DB insert failed (file save still succeeded)")

        # All disk work done — drop the overlay before showing the success
        # dialog (otherwise the dialog would render on top of the dimmed UI
        # but underneath the spinner card, looking confused).
        self._processing_overlay.hide()
        self._confirm_btn.setEnabled(True)

        # Build per-location pad list for the success dialog.
        per_loc_for_dialog: dict[str, list[PadMeasurement]] = {}
        for code in LOCATION_ORDER:
            pads = self._batch_measurements.get(code) or (
                self._measurements if code == self._current_location else None
            )
            if pads:
                per_loc_for_dialog[code] = pads

        success = _SaveSuccessDialog(
            lot_id=self._current_lot.lot_id,
            n_saved=len(saved),
            per_location_pads=per_loc_for_dialog,
            unit=self._display_unit,
            parent=self,
        )
        success.exec()

        # Pop up the trend chart filtered by bonding × machine. lot_location
        # in the SOAP response (e.g. "MTAI_WB158") identifies the bonding
        # station — combining it with bonding_number lets the operator see
        # trends per machine, not blended across stations.
        if bonding_number:
            try:
                lot_loc = (self._current_lot.lot_location or "").strip() or None
                rows = self._db.history_for_bonding(
                    bonding_number,
                    lot_location=lot_loc,
                    limit_lots=30,
                )
                trend = TrendDialog(
                    bonding_number=bonding_number,
                    rows=rows,
                    current_lot_id=self._current_lot.lot_id,
                    unit=self._display_unit,
                    lot_location=lot_loc,
                    parent=self,
                )
                trend.exec()
            except Exception:
                log.exception("trend dialog failed")

        self._reset_session()
        self.statusBar().showMessage(
            f"Saved {len(saved)} images. Ready for next LOT.", 5000,
        )
        # Loop back to the sign-in gate so the next operator / LOT can begin
        # immediately. Cancel on the gate this time leaves them on the empty
        # main window (it's a normal idle state, not a crash exit).
        QTimer.singleShot(80, lambda: self._show_startup_gate(exit_on_cancel=False))

    def _reset_session(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None

        self._operator_badge = ""
        self._badge_input.clear()
        self._lot_input.clear()
        self._clear_lot_info()

        self._staged = {code: [] for code in LOCATION_ORDER}
        self._selection_state = {}
        self._current_location = LOCATION_ORDER[0]
        for code, btn in self._loc_buttons.items():
            btn.setText(f"{code}  0 / {SHOTS_PER_LOCATION}")
        self._loc_buttons[LOCATION_ORDER[0]].setChecked(True)
        self._preview_group.setTitle(f"Captures at {LOCATION_LABELS[LOCATION_ORDER[0]]}")
        self._preview_list.clear()

        self._focus_ball_preview.clear()
        self._focus_pad_preview.clear()
        self._measurement = None
        self._measurements = []
        self._last_fused = None
        self._last_focus_ball = None
        self._last_focus_pad = None
        self._batch_pairs = {
            code: {"ball": None, "pad": None} for code in LOCATION_ORDER
        }
        self._batch_measurements = {}
        self._update_batch_status_text()
        # Clear every drop slot in the location grid + their status pills.
        for (code, _role), slot in self._loc_slots.items():
            slot.clear()
        for code in LOCATION_ORDER:
            status = self.findChild(QLabel, f"loc_status_{code}")
            if status is not None:
                status.setText("○")
                status.setStyleSheet(
                    "QLabel { color: #cbd5e1; font-size: 14px; }"
                )
        self._highlight_active_card()
        self._result_panel.setText("No measurement yet")
        self._fused_preview.clear()
        self._focus_ball_preview.clear()
        self._focus_pad_preview.clear()
        # Reset the side "Selected image" preview to its empty placeholder.
        self._selected_preview.clear()
        self._selected_preview.setText(
            "\nselected image\n\n(click a thumbnail below)"
        )
        self._show_pad_btn.setVisible(True)
        self._show_ball_btn.setVisible(False)

        self._arm_state.setText("● Disarmed")
        self._arm_state.setStyleSheet(
            "QLabel { color: #94a3b8; background: #f1f5f9;"
            " border: 1px solid #e2e8f0; border-radius: 999px;"
            " padding: 4px 14px; font-weight: 600; }"
        )
        self._update_input_state()
        self._badge_input.setFocus()

    # ---------- Measurement ----------

    def _on_slot_changed(self, _path: object) -> None:
        # Either focus canvas changed — invalidate the previous measurement, but
        # keep showing the dropped source thumbnails (operator's drop is intentional).
        self._measurement = None
        self._measurements = []
        self._last_fused = None
        self._last_focus_ball = None
        self._last_focus_pad = None
        self._result_panel.setText("No measurement yet — click Fuse & Measure")
        self._fused_preview.clear()
        # Re-show source thumbnails (the canvases ARE the slots — we don't clear them).
        self._focus_ball_preview.revert_to_source()
        self._focus_pad_preview.revert_to_source()
        # In batch mode, persist the change into the per-location pair store
        # so it survives a location switch.
        if self._batch_mode:
            self._save_current_pair_to_location()
        self._update_input_state()

    def _on_measure_clicked(self) -> None:
        """Pad detection on Focus-Pad image; ball detection on Focus-Ball image."""
        # In batch mode, route to the batch processor: every location with a
        # complete pair gets measured in one shot.
        if self._batch_mode:
            self._on_batch_measure_clicked()
            return
        focus_ball_path = self._focus_ball_preview.path()
        focus_pad_path = self._focus_pad_preview.path()
        if focus_ball_path is None or focus_pad_path is None:
            return
        self._measure_btn.setEnabled(False)
        self.statusBar().showMessage("Detecting pad + ball …")
        # Visual lock-out: spinner overlay while the pipeline runs.
        self._processing_overlay.show_with("Detecting pad + ball …")
        QWidget.repaint(self)

        try:
            ome = parse_tiff(focus_pad_path)
            px_um = pixel_size_um_from_ome(ome.physical_size_x, ome.physical_size_unit)
            focus_ball = load_as_bgr(focus_ball_path)
            focus_pad = load_as_bgr(focus_pad_path)

            # Multi-pad detection: every pad clearing the filters is returned,
            # each with its own ball + gap measurement.
            pads = detect_pads_multi(
                focus_pad, focus_ball,
                pixel_size_um=px_um,
                source_a_name=focus_ball_path.name,
                source_b_name=focus_pad_path.name,
            )
            if not pads:
                raise ValueError(
                    "No pad contour found — see logs/pad_fail_*.png for diagnostics."
                )

            # Fused image is for DISPLAY only — gives an all-in-focus background.
            fused = focus_stack(focus_ball, focus_pad)
            u = self._display_unit
            overlay_fused = draw_multi_pad_overlay(fused, pads, unit=u)
            overlay_ball = draw_multi_ball_only_overlay(focus_ball, pads, unit=u)
            overlay_pad = draw_multi_pad_only_overlay(focus_pad, pads, unit=u)
            m = pads[0]   # primary pad for click-refine + status
        except Exception as e:
            log.exception("measurement failed")
            self._processing_overlay.hide()
            QMessageBox.critical(self, "Measurement failed", str(e))
            self._measure_btn.setEnabled(True)
            return
        finally:
            # Always hide the overlay — even on the success path.
            self._processing_overlay.hide()

        self._measurement = m
        self._measurements = pads
        self._last_fused = fused
        self._last_focus_ball = focus_ball
        self._last_focus_pad = focus_pad
        self._last_pixel_size_um = px_um
        self._result_panel.setText(self._format_result_multi(pads))
        self._set_canvas_pixmap(self._fused_preview, overlay_fused)
        self._set_canvas_pixmap(self._focus_ball_preview, overlay_ball)
        self._set_canvas_pixmap(self._focus_pad_preview, overlay_pad)
        self._measure_btn.setEnabled(True)
        self._show_pad_btn.setVisible(True)
        self._show_ball_btn.setVisible(False)
        log.info("multi-pad detected: %d pads", len(pads))
        for i, p in enumerate(pads, 1):
            log.info("  #%d  %.1fx%.1f um  fill=%.3f  %s | ball %s",
                     i, p.width_um, p.height_um, p.fill_ratio, p.confidence,
                     f"d={p.ball.diameter_um:.1f}um" if p.ball else "(none)")
        self.statusBar().showMessage(
            f"Detected {len(pads)} pad(s) — see table on the right",
            0,
        )
        self._update_input_state()

    def _on_batch_measure_clicked(self) -> None:
        """Run multi-pad detection on every paired location in one go.

        The currently-active location's slots are stashed first so the user
        doesn't have to switch away to "commit" the active pair. Each
        successful location's pads land in `self._batch_measurements[code]`.
        After processing, the active location's overlay is shown in the main
        canvas and the result panel summarises every location's measurements.
        """
        # Make sure whatever's in the slots right now is captured.
        self._save_current_pair_to_location()

        paired_codes = [
            code for code in LOCATION_ORDER
            if self._batch_pairs[code].get("ball") is not None
            and self._batch_pairs[code].get("pad") is not None
        ]
        if not paired_codes:
            self.statusBar().showMessage(
                "Drop a pair into the slots first (or switch to per-location mode)",
                4000,
            )
            return

        self._measure_btn.setEnabled(False)
        self.statusBar().showMessage(
            f"Detecting {len(paired_codes)} location(s) …"
        )
        self._processing_overlay.show_with(
            f"Preparing batch — {len(paired_codes)} location(s)"
        )
        QWidget.repaint(self)

        results: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for i, code in enumerate(paired_codes, start=1):
            self._processing_overlay.set_message(
                f"[{i}/{len(paired_codes)}]  {code}  ·  detecting pad + ball …"
            )
            pair = self._batch_pairs[code]
            ball_path = pair["ball"]
            pad_path = pair["pad"]
            try:
                ome = parse_tiff(pad_path)
                px_um = pixel_size_um_from_ome(
                    ome.physical_size_x, ome.physical_size_unit,
                )
                focus_ball = load_as_bgr(ball_path)
                focus_pad = load_as_bgr(pad_path)
                pads = detect_pads_multi(
                    focus_pad, focus_ball,
                    pixel_size_um=px_um,
                    source_a_name=Path(ball_path).name,
                    source_b_name=Path(pad_path).name,
                    debug_dump=False,
                )
                if not pads:
                    raise ValueError("no pad contour found")
                fused = focus_stack(focus_ball, focus_pad)
                results[code] = {
                    "pads": pads,
                    "fused": fused,
                    "focus_ball": focus_ball,
                    "focus_pad": focus_pad,
                    "px_um": px_um,
                    "ball_path": ball_path,
                    "pad_path": pad_path,
                }
            except Exception as e:
                log.exception("batch measurement failed for %s", code)
                errors.append(f"{code}: {e}")

        self._processing_overlay.hide()
        self._measure_btn.setEnabled(True)
        if not results:
            QMessageBox.critical(
                self, "Batch measurement failed",
                "No location produced a valid measurement.\n\n"
                + "\n".join(errors),
            )
            return
        if errors:
            self.statusBar().showMessage(
                f"Done — {len(results)}/{len(paired_codes)} OK, "
                f"{len(errors)} failed",
                0,
            )
        else:
            self.statusBar().showMessage(
                f"Done — measured {len(results)}/4 locations", 0,
            )

        self._batch_measurements = {
            code: r["pads"] for code, r in results.items()
        }
        # Pop up a review dialog with thumbnails + summary for each location.
        # Operator confirms to keep results, or cancels to discard and redo.
        review = _BatchResultsDialog(results, self._display_unit, parent=self)
        if review.exec() != QDialog.DialogCode.Accepted:
            self._batch_measurements = {}
            self.statusBar().showMessage("Batch results discarded — re-fuse to retry", 4000)
            self._update_input_state()
            return

        # Show the ACTIVE location's overlay (or the first measured one).
        active = self._current_location
        show = active if active in results else next(iter(results))
        r = results[show]
        self._measurement = r["pads"][0]
        self._measurements = r["pads"]
        self._last_fused = r["fused"]
        self._last_focus_ball = r["focus_ball"]
        self._last_focus_pad = r["focus_pad"]
        self._last_pixel_size_um = r["px_um"]
        u = self._display_unit
        self._set_canvas_pixmap(
            self._fused_preview, draw_multi_pad_overlay(r["fused"], r["pads"], unit=u),
        )
        self._set_canvas_pixmap(
            self._focus_ball_preview,
            draw_multi_ball_only_overlay(r["focus_ball"], r["pads"], unit=u),
        )
        self._set_canvas_pixmap(
            self._focus_pad_preview,
            draw_multi_pad_only_overlay(r["focus_pad"], r["pads"], unit=u),
        )
        self._result_panel.setText(self._format_batch_result(show))
        self.statusBar().showMessage(
            f"Confirmed — {len(self._batch_measurements)} location(s) ready to save",
            5000,
        )
        self._update_input_state()

    def _format_batch_result(self, active_code: str) -> str:
        """HTML summary of all measured locations. The active location is
        highlighted; others render in a compact form. Each location's table
        carries the same column header so the operator can read off any row
        without having to remember which column is which."""
        if self._display_unit == "mil":
            sc = 1.0 / 25.4
            u = "mil"
        else:
            sc = 1.0
            u = "µm"
        # One shared header row used for every location's table.
        header_row = (
            f"<tr style='color:#475569;background:#f1f5f9'>"
            f"<th style='padding:3px 6px;text-align:left;border-bottom:1px solid #cbd5e1'>#</th>"
            f"<th style='padding:3px 6px;text-align:left;border-bottom:1px solid #cbd5e1'>"
            f"PAD W×H<br><span style='color:#94a3b8;font-weight:normal'>({u})</span></th>"
            f"<th style='padding:3px 6px;text-align:left;border-bottom:1px solid #cbd5e1'>"
            f"BALL d<br><span style='color:#94a3b8;font-weight:normal'>({u})</span></th>"
            f"<th style='padding:3px 6px;text-align:left;border-bottom:1px solid #cbd5e1'>"
            f"GAP min/mean<br><span style='color:#94a3b8;font-weight:normal'>({u})</span></th>"
            f"</tr>"
        )
        sections = []
        for code in LOCATION_ORDER:
            pads = self._batch_measurements.get(code)
            if not pads:
                sections.append(
                    f"<div style='padding:6px 8px;color:#94a3b8'>"
                    f"<b>{code}</b> — not measured</div>"
                )
                continue
            badge_color = "#16a34a" if code == active_code else "#475569"
            head = (
                f"<div style='padding:6px 8px;'>"
                f"<b style='color:{badge_color}'>{code}</b>"
                f" &nbsp; <span style='color:#64748b'>"
                f"{LOCATION_LABELS.get(code, code)} · {len(pads)} pad(s)</span></div>"
            )
            rows = []
            for i, m in enumerate(pads, start=1):
                pad_dims = f"{m.width_um * sc:.2f} × {m.height_um * sc:.2f}"
                ball_str = (
                    f"{m.ball.diameter_um * sc:.2f}" if m.ball else "—"
                )
                gap_str = (
                    f"{m.gap.min_gap_um * sc:.2f} / {m.gap.mean_gap_um * sc:.2f}"
                    if m.gap is not None else "—"
                )
                rows.append(
                    f"<tr>"
                    f"<td style='padding:2px 6px;color:#16a34a'>#{i}</td>"
                    f"<td style='padding:2px 6px'>{pad_dims}</td>"
                    f"<td style='padding:2px 6px;color:#a23'>{ball_str}</td>"
                    f"<td style='padding:2px 6px;color:#a14ba1'>{gap_str}</td>"
                    f"</tr>"
                )
            tbl = (
                f"<table style='border-collapse:collapse;font-size:10px'>"
                f"{header_row}{''.join(rows)}</table>"
            )
            sections.append(head + tbl)
        scale_note = (
            f"<br><span style='color:#94a3b8;font-size:10px'>"
            f"All values in <b>{u}</b>. "
            f"<span style='color:#16a34a'>#</span> = pad index, "
            f"<span style='color:#a23'>BALL d</span> = ball diameter, "
            f"<span style='color:#a14ba1'>GAP min/mean</span> = closest "
            f"and average pad-to-ball gap.</span>"
        )
        return (
            f"<b>Batch — {sum(1 for v in self._batch_measurements.values() if v)} / 4 measured</b>"
            + "<br>" + "".join(sections) + scale_note
        )

    def _on_show_pad_clicked(self) -> None:
        """Display the pad-detection debug overlay (all candidates) on the current fused image."""
        if self._last_fused is None:
            self.statusBar().showMessage("Run Fuse & Measure first", 3000)
            return
        overlay = debug_pad_overlay(self._last_fused)
        self._set_canvas_pixmap(self._fused_preview, overlay)
        self._show_pad_btn.setVisible(False)
        self._show_ball_btn.setVisible(True)
        self.statusBar().showMessage(
            "Candidates view: green = chosen, yellow = rejected, grey = out of size range",
            0,
        )

    def _on_show_ball_clicked(self) -> None:
        """Return to the multi-pad measurement overlay."""
        if self._last_fused is None or not self._measurements:
            self._show_pad_btn.setVisible(True)
            self._show_ball_btn.setVisible(False)
            return
        overlay = draw_multi_pad_overlay(self._last_fused, self._measurements, unit=self._display_unit)
        self._set_canvas_pixmap(self._fused_preview, overlay)
        self._show_pad_btn.setVisible(True)
        self._show_ball_btn.setVisible(False)

    # ---------- Location row helpers ----------

    def _build_location_row(self, code: str) -> QWidget:
        """One card per location: header (code + label + status pill) + 2
        drop slots. Cards are NOT clickable — they're pure drop targets;
        which slot the operator drops into determines the location."""
        card = QFrame()
        card.setObjectName(f"loc_card_{code}")
        card.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #e2e8f0;"
            " border-radius: 10px; }"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        # Static label — `_loc_buttons[code]` is kept as a QLabel-shaped
        # "button" so legacy code (capture counters etc.) can still update
        # `.setText()` without crashing. Non-clickable.
        counter = QPushButton(f"{code}  ·  {LOCATION_LABELS[code]}")
        counter.setEnabled(False)
        counter.setFlat(True)
        counter.setStyleSheet(
            "QPushButton {"
            " background: transparent; border: 0; color: #475569;"
            " font-weight: 600; padding: 0; text-align: left;"
            "}"
            "QPushButton:disabled { color: #475569; }"
        )
        self._loc_buttons[code] = counter
        head.addWidget(counter)
        head.addStretch(1)
        status = QLabel("○")
        status.setObjectName(f"loc_status_{code}")
        status.setStyleSheet("QLabel { color: #cbd5e1; font-size: 14px; }")
        head.addWidget(status)
        v.addLayout(head)

        slots_row = QHBoxLayout()
        slots_row.setSpacing(6)
        slot_ball = _SlotCanvas(code, "ball")
        slot_ball.pathChanged.connect(
            lambda p, c=code, r="ball": self._on_slot_drop(c, r, p)
        )
        # No click handler — slots are pure drop targets.
        self._loc_slots[(code, "ball")] = slot_ball
        slot_pad = _SlotCanvas(code, "pad")
        slot_pad.pathChanged.connect(
            lambda p, c=code, r="pad": self._on_slot_drop(c, r, p)
        )
        self._loc_slots[(code, "pad")] = slot_pad
        slots_row.addWidget(slot_ball)
        slots_row.addWidget(slot_pad)
        v.addLayout(slots_row)
        return card

    def _on_slot_drop(self, code: str, role: str, path: object) -> None:
        """Drop into a slot — store in batch_pairs and clear any prior
        measurement (the new image needs a fresh fuse). Cards aren't
        clickable / "active" anymore; each slot owns its own (code, role)."""
        path_obj = path if isinstance(path, Path) else None
        self._batch_pairs[code][role] = path_obj
        # Clear the captures-grid selection so the next drag starts fresh.
        if path_obj is not None:
            self._preview_list.blockSignals(True)
            self._preview_list.clearSelection()
            self._preview_list.blockSignals(False)
        # New image invalidates any prior measurement that referenced it.
        self._measurement = None
        self._measurements = []
        self._last_fused = None
        self._last_focus_ball = None
        self._last_focus_pad = None
        self._fused_preview.clear()
        if not self._batch_measurements:
            self._result_panel.setText(
                '<span style="color:#94a3b8">No measurement yet — drop pairs '
                'and click Fuse</span>'
            )
        # Update per-row status pill.
        pair = self._batch_pairs[code]
        full = pair.get("ball") is not None and pair.get("pad") is not None
        status = self.findChild(QLabel, f"loc_status_{code}")
        if status is not None:
            status.setText("●" if full else "○")
            status.setStyleSheet(
                "QLabel { color: #16a34a; font-size: 14px; }" if full
                else "QLabel { color: #cbd5e1; font-size: 14px; }"
            )
        self._update_input_state()

    def _highlight_active_card(self) -> None:
        """No-op — location cards no longer have an "active" highlight (they
        are pure drop targets, no click selection). Kept so legacy callers
        don't error."""
        return

    # ---------- Measurement mode ----------

    def _set_measure_mode(self, batch: bool) -> None:
        """Programmatic mode setter — used by the mode-select popup. The
        in-UI toggle was removed in favour of that popup."""
        self._batch_mode = batch
        self._update_input_state()

    def _save_current_pair_to_location(self) -> None:
        """Legacy no-op. Drops now write directly into `_batch_pairs[code]`
        via `_on_slot_drop`; there is nothing extra to stash from the
        (hidden) Focus-Ball / Focus-Pad previews."""
        return

    def _restore_pair_from_location(self, code: str) -> None:
        """Push the pair stashed for `code` into the slot canvases."""
        pair = self._batch_pairs.get(code, {"ball": None, "pad": None})
        # Block slot-change signals while we restore so we don't echo back.
        self._focus_ball_preview.blockSignals(True)
        self._focus_pad_preview.blockSignals(True)
        try:
            ball = pair.get("ball")
            pad = pair.get("pad")
            if ball is not None and ball.exists():
                self._focus_ball_preview.set_path(ball)
            else:
                self._focus_ball_preview.clear()
            if pad is not None and pad.exists():
                self._focus_pad_preview.set_path(pad)
            else:
                self._focus_pad_preview.clear()
        finally:
            self._focus_ball_preview.blockSignals(False)
            self._focus_pad_preview.blockSignals(False)
        # Manually fire the local-only side effects (don't double-save).
        self._measurement = None
        self._measurements = []
        self._last_fused = None
        self._fused_preview.clear()

    def _update_batch_status_text(self) -> None:
        if not self._batch_mode:
            self._batch_status_lbl.setText("")
            return
        chips = []
        for code in LOCATION_ORDER:
            pair = self._batch_pairs.get(code, {})
            paired = pair.get("ball") is not None and pair.get("pad") is not None
            if paired:
                chips.append(
                    f"<span style='color:#16a34a;font-weight:600'>{code}✓</span>"
                )
            else:
                chips.append(f"<span style='color:#94a3b8'>{code}·</span>")
        n_paired = sum(
            1 for p in self._batch_pairs.values()
            if p.get("ball") is not None and p.get("pad") is not None
        )
        self._batch_status_lbl.setText(
            "  ".join(chips) + f"  &nbsp; <span style='color:#64748b'>"
            f"{n_paired}/4 paired</span>"
        )

    def _set_unit(self, unit_str: str) -> None:
        """Segmented-control handler: pick µm or mil, sync both buttons,
        re-render every visible measurement in the new unit.

        Batch results: every location's row in the result panel is converted
        on the spot (no re-fuse / re-load needed).
        Per-location: the active pad table is re-rendered.
        """
        unit_str = "mil" if unit_str == "mil" else "um"
        self._display_unit = unit_str
        # Sync the segmented toggle pair so exactly one is checked.
        self._unit_um_btn.setChecked(unit_str == "um")
        self._unit_mil_btn.setChecked(unit_str == "mil")
        u = self._display_unit

        # Batch mode (all 4 locations measured) — render the combined summary.
        if self._batch_measurements:
            self._result_panel.setText(
                self._format_batch_result(self._current_location)
            )
        elif self._measurements:
            self._result_panel.setText(
                self._format_result_multi(self._measurements)
            )

        # Re-draw the (hidden) Fused / Focus-Ball / Focus-Pad overlays so any
        # later display path that reads from these widgets keeps the labels
        # in sync with the picked unit. Cheap when state is empty.
        if self._last_fused is not None and self._measurements:
            self._set_canvas_pixmap(
                self._fused_preview,
                draw_multi_pad_overlay(self._last_fused, self._measurements, unit=u),
            )
        if self._last_focus_ball is not None and self._measurements:
            self._set_canvas_pixmap(
                self._focus_ball_preview,
                draw_multi_ball_only_overlay(self._last_focus_ball, self._measurements, unit=u),
            )
        if self._last_focus_pad is not None and self._measurements:
            self._set_canvas_pixmap(
                self._focus_pad_preview,
                draw_multi_pad_only_overlay(self._last_focus_pad, self._measurements, unit=u),
            )

    def _on_unit_toggled(self, checked: bool) -> None:
        """Compat shim — old callers (legacy QCheckBox) still route through here."""
        self._set_unit("mil" if checked else "um")

    def _on_fused_clicked(self, label_x: float, label_y: float) -> None:
        """Operator clicked the fused preview.

        Single-pad mode: re-detect pad+ball at the click (legacy click-refine).
        Multi-pad mode: identify which pad contains the click, then re-run ball
        detection for that pad biased toward the click — used to fix wrong
        dark blob picks (e.g. when there are multiple dark spots in a pad).
        """
        log.info("fused preview clicked at label (%.1f, %.1f)", label_x, label_y)
        if self._last_fused is None or not self._measurements:
            self.statusBar().showMessage(
                "Click ignored — run Fuse & Measure first", 3000,
            )
            return
        pix = self._fused_preview.pixmap()
        if pix is None or pix.isNull():
            self.statusBar().showMessage("Click ignored — no preview image", 3000)
            return
        pw, ph = pix.width(), pix.height()
        lw, lh = self._fused_preview.width(), self._fused_preview.height()
        # Centered pixmap: offset from both sides
        offset_x = max(0.0, (lw - pw) / 2.0)
        offset_y = max(0.0, (lh - ph) / 2.0)
        rel_x = label_x - offset_x
        rel_y = label_y - offset_y
        # Clamp to pixmap bounds (forgiving — small overshoot still counts)
        rel_x = max(0.0, min(pw - 1.0, rel_x))
        rel_y = max(0.0, min(ph - 1.0, rel_y))
        fh, fw = self._last_fused.shape[:2]
        seed = (rel_x * fw / pw, rel_y * fh / ph)
        log.info("click mapped to fused coords (%.1f, %.1f) of %dx%d", seed[0], seed[1], fw, fh)
        if self._last_focus_pad is None or self._last_focus_ball is None:
            return

        # Multi-pad mode: figure out which pad's polygon contains the click,
        # then re-run ball detection for that pad with the click as a seed bias.
        if len(self._measurements) > 1:
            hit_idx = -1
            for i, m in enumerate(self._measurements):
                poly = np.array(m.corners_px, dtype=np.int32)
                if cv2.pointPolygonTest(poly, (float(seed[0]), float(seed[1])), False) >= 0:
                    hit_idx = i
                    break
            if hit_idx < 0:
                self.statusBar().showMessage(
                    "Click on a pad to re-target its ball", 3000,
                )
                return
            target = self._measurements[hit_idx]
            try:
                new_ball = detect_ball_in_pad(
                    self._last_focus_ball, target,
                    pixel_size_um=self._last_pixel_size_um,
                    seed_xy_fused=seed,
                )
            except Exception as e:
                log.exception("seeded ball redetect failed")
                self.statusBar().showMessage(f"refine failed: {e}", 4000)
                return
            if new_ball is None:
                self.statusBar().showMessage(
                    "No dark blob containing the click — try clicking the ball centre", 4000,
                )
                return
            new_ball.method = f"{new_ball.method}[FocusBall+seed]"
            target.ball = new_ball
            target.gap = compute_gap(target)
            self._measurements[hit_idx] = target
            self._measurement = self._measurements[0]  # primary stays as the first
            u = self._display_unit
            self._result_panel.setText(self._format_result_multi(self._measurements))
            self._set_canvas_pixmap(
                self._fused_preview,
                draw_multi_pad_overlay(self._last_fused, self._measurements, unit=u),
            )
            self._set_canvas_pixmap(
                self._focus_ball_preview,
                draw_multi_ball_only_overlay(self._last_focus_ball, self._measurements, unit=u),
            )
            self._set_canvas_pixmap(
                self._focus_pad_preview,
                draw_multi_pad_only_overlay(self._last_focus_pad, self._measurements, unit=u),
            )
            self.statusBar().showMessage(
                f"Pad #{hit_idx + 1} ball re-targeted at ({int(seed[0])}, {int(seed[1])}) "
                f"→ d = {new_ball.diameter_um:.2f} µm",
                0,
            )
            return

        # Single-pad mode: legacy click-refine the pad itself.
        try:
            new_pad = detect_pad(
                self._last_focus_pad,
                pixel_size_um=self._last_pixel_size_um,
                source_a_name=self._measurement.source_a_name,
                source_b_name=self._measurement.source_b_name,
                seed_center=seed,
            )
            new_pad.method = f"{new_pad.method}[FocusPad]"
            new_ball = detect_ball_in_pad(
                self._last_focus_ball, new_pad,
                pixel_size_um=self._last_pixel_size_um,
            )
            if new_ball is not None:
                new_ball.method = f"{new_ball.method}[FocusBall]"
            new_pad.ball = new_ball
            new_pad.gap = compute_gap(new_pad)
        except Exception as e:
            log.exception("redetect failed")
            self.statusBar().showMessage(f"refine failed: {e}", 4000)
            return
        self._measurement = new_pad
        self._measurements = [new_pad]
        self._result_panel.setText(self._format_result(new_pad))
        u = self._display_unit
        self._set_canvas_pixmap(self._fused_preview, draw_pad_overlay(self._last_fused, new_pad, unit=u))
        self._set_canvas_pixmap(self._focus_ball_preview, draw_ball_only_overlay(self._last_focus_ball, new_pad, unit=u))
        self._set_canvas_pixmap(self._focus_pad_preview, draw_pad_only_overlay(self._last_focus_pad, new_pad, unit=u))
        self._show_pad_btn.setVisible(True)
        self._show_ball_btn.setVisible(False)
        log.info(
            "pad re-detected at seed (%d,%d): %.1fx%.1f um  fill=%.3f  %s",
            int(seed[0]), int(seed[1]),
            new_pad.width_um, new_pad.height_um,
            new_pad.fill_ratio, new_pad.confidence,
        )
        self.statusBar().showMessage(
            f"Re-targeted at ({int(seed[0])}, {int(seed[1])}) → "
            f"{new_pad.width_um:.1f} × {new_pad.height_um:.1f} µm",
            0,
        )

    def _format_result_multi(self, pads: list[PadMeasurement]) -> str:
        """Compact HTML table summarising every detected pad (and its ball/gap)."""
        if not pads:
            return "No measurement yet"
        if self._display_unit == "mil":
            sc = 1.0 / 25.4
            u = "mil"
        else:
            sc = 1.0
            u = "µm"
        rows = []
        for i, m in enumerate(pads, start=1):
            pad_dims = f"{m.width_um * sc:.2f} × {m.height_um * sc:.2f}"
            ball_str = f"{m.ball.diameter_um * sc:.2f}" if m.ball else "—"
            if m.gap is not None:
                gap_str = f"{m.gap.min_gap_um * sc:.2f} / {m.gap.mean_gap_um * sc:.2f}"
            else:
                gap_str = "—"
            rows.append(
                f"<tr style='vertical-align:top'>"
                f"<td style='padding:4px 8px;color:#2b8a3e'><b>#{i}</b></td>"
                f"<td style='padding:4px 8px'>{pad_dims}</td>"
                f"<td style='padding:4px 8px;color:#a23'>{ball_str}</td>"
                f"<td style='padding:4px 8px;color:#a14ba1'>{gap_str}</td>"
                f"<td style='padding:4px 8px;color:#666'>{m.confidence}</td>"
                f"</tr>"
            )
        header = (
            f"<tr style='color:#475569;background:#f1f5f9'>"
            f"<th style='padding:4px 8px;text-align:left;border-bottom:1px solid #cbd5e1'>#</th>"
            f"<th style='padding:4px 8px;text-align:left;border-bottom:1px solid #cbd5e1'>"
            f"PAD W×H<br><span style='color:#94a3b8;font-weight:normal'>({u})</span></th>"
            f"<th style='padding:4px 8px;text-align:left;border-bottom:1px solid #cbd5e1'>"
            f"BALL d<br><span style='color:#94a3b8;font-weight:normal'>({u})</span></th>"
            f"<th style='padding:4px 8px;text-align:left;border-bottom:1px solid #cbd5e1'>"
            f"GAP min/mean<br><span style='color:#94a3b8;font-weight:normal'>({u})</span></th>"
            f"<th style='padding:4px 8px;text-align:left;border-bottom:1px solid #cbd5e1'>conf</th>"
            f"</tr>"
        )
        legend = (
            f"<br><span style='color:#94a3b8;font-size:10px'>"
            f"<span style='color:#16a34a'>#</span> = pad index, "
            f"<b>PAD W×H</b> = pad width × height, "
            f"<span style='color:#a23'>BALL d</span> = ball diameter, "
            f"<span style='color:#a14ba1'>GAP min/mean</span> = closest "
            f"and average pad-to-ball gap.</span>"
        )
        table = (
            f"<b>Detected {len(pads)} pad(s)</b><br><br>"
            f"<table style='border-collapse:collapse;font-family:Consolas,monospace;font-size:10px'>"
            f"{header}{''.join(rows)}"
            f"</table>"
            f"<br><span style='color:#94a3b8;font-size:10px'>"
            f"Scale: {pads[0].pixel_size_um:.4f} µm/px</span>"
            f"{legend}"
        )
        return table

    def _format_result(self, m: PadMeasurement) -> str:
        if self._display_unit == "mil":
            s = 1.0 / 25.4
            u = "mil"
        else:
            s = 1.0
            u = "µm"
        s2 = s * s
        a = "mil²" if u == "mil" else "µm²"

        pad_block = (
            f"<b>PAD</b><br>"
            f"Width : {m.width_um * s:.2f} {u}<br>"
            f"Height: {m.height_um * s:.2f} {u}<br>"
            f"Diag  : {m.diagonal_um * s:.2f} {u}<br>"
            f"Area  : {m.area_um2 * s2:.1f} {a}<br>"
            f"Aspect: {m.aspect_ratio:.3f}  Fill: {m.fill_ratio:.3f}<br>"
            f"Conf  : {m.confidence}"
        )
        if m.ball is not None:
            b = m.ball
            ball_block = (
                f"<br><br><b>BALL</b><br>"
                f"Diameter: {b.diameter_um * s:.2f} {u}<br>"
                f"Radius  : {b.radius_um * s:.2f} {u}<br>"
                f"Center  : ({b.center_x_px}, {b.center_y_px})<br>"
                f"Circularity: {b.circularity:.3f}<br>"
                f"Fill       : {b.fill_ratio:.3f}"
            )
        else:
            ball_block = "<br><br><b>BALL</b><br><i>not detected</i>"

        if m.gap is not None:
            g = m.gap
            per_side = "  ".join(f"{v * s:.2f}" for v in g.per_side_um)
            gap_block = (
                f"<br><br><b>GAP  (pad → ball edge)</b><br>"
                f"Min  : {g.min_gap_um * s:.2f} {u}  (side #{g.min_gap_side})<br>"
                f"Max  : {g.max_gap_um * s:.2f} {u}<br>"
                f"Mean : {g.mean_gap_um * s:.2f} {u}<br>"
                f"Sides: {per_side} {u}<br>"
                f"Annulus area: {g.annulus_area_um2 * s2:.1f} {a}"
            )
        else:
            gap_block = ""

        scale = f"<br><br>Scale: {m.pixel_size_um:.4f} µm/px"
        return pad_block + ball_block + gap_block + scale

    @staticmethod
    def _bgr_to_pixmap(bgr: np.ndarray, max_w: int = 480, max_h: int = 360) -> QPixmap:
        """Downscale BGR for preview, preserving aspect ratio."""
        h, w = bgr.shape[:2]
        scale = min(max_w / w, max_h / h, 1.0)
        if scale < 1.0:
            bgr = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h2, w2 = rgb.shape[:2]
        img = QImage(rgb.data, w2, h2, 3 * w2, QImage.Format.Format_RGB888).copy()
        return QPixmap.fromImage(img)

    def _set_canvas_pixmap(self, canvas: QLabel, bgr: np.ndarray) -> None:
        """Scale `bgr` to the canvas's actual size before assigning. Prevents the
        pixmap from overflowing the widget's bounds (which would otherwise leak
        into adjacent widgets after a window resize)."""
        # subtract a 2-pixel border so the pixmap never overlaps the canvas frame
        target_w = max(20, canvas.width() - 2)
        target_h = max(20, canvas.height() - 2)
        canvas.setPixmap(self._bgr_to_pixmap(bgr, max_w=target_w, max_h=target_h))

    # ---------- Watcher callback ----------

    def _watcher_callback(self, path: Path) -> None:
        self._file_ready_signal.emit(str(path))

    @pyqtSlot(str)
    def _on_file_ready(self, path_str: str) -> None:
        if self._watcher is None or self._current_lot is None or not self._operator_badge:
            return
        path = Path(path_str)
        code = self._current_location
        if path in self._staged[code]:
            return
        self._staged[code].append(path)

        if code == self._current_location:
            self._add_thumbnail_item(path)

        if self._selected_count(code) < SHOTS_PER_LOCATION:
            item = self._preview_list.item(self._preview_list.count() - 1)
            if item is not None:
                self._preview_list.blockSignals(True)
                item.setSelected(True)
                self._preview_list.blockSignals(False)
                self._selection_state[(code, path)] = True

        self._update_selection_hint()
        self._update_input_state()
        self.statusBar().showMessage(
            f"Captured at {LOCATION_LABELS[code]}: {path.name}", 4000,
        )

    # ---------- misc ----------

    def _open_settings_dialog(self) -> None:
        """Edit read / share / DB paths. On Save, persists back to
        settings.yaml AND applies live (re-arm watcher, swap ImageStore,
        reopen DB at the new path)."""
        dlg = _SettingsDialog(
            watch_root=self._settings.capture.watch_root,
            shared_root=self._settings.storage.shared_root,
            db_path=self._settings.storage.db_path,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_watch = dlg.watch_root()
        new_share = dlg.shared_root()
        new_db    = dlg.db_path()

        # Update the in-memory settings.
        self._settings.capture.watch_root = new_watch
        self._settings.storage.shared_root = new_share
        self._settings.storage.db_path = new_db

        # Persist to disk if we know where the file is.
        if self._settings_path is not None:
            try:
                self._settings.to_yaml(self._settings_path)
                log.info("settings written to %s", self._settings_path)
            except Exception as e:
                log.exception("failed to save settings.yaml")
                QMessageBox.warning(
                    self, "Saved in memory only",
                    "Could not write settings.yaml:\n\n"
                    f"{e}\n\n"
                    "Changes apply to this session but won't persist after restart.",
                )

        # Apply live: swap the image store, reopen the DB at the new path,
        # and re-arm the watcher under the new read root.
        self._store = ImageStore(
            shared_root=new_share,
            compute_sha256=self._settings.storage.compute_sha256,
        )
        try:
            self._db = MeasurementDB(new_db)
        except Exception as e:
            log.exception("could not open DB at %s", new_db)
            QMessageBox.warning(
                self, "Database not reachable",
                f"Couldn't open the database at:\n{new_db}\n\n{e}\n\n"
                "Old DB will keep being used until the path is fixed.",
            )
        was_armed = self._watcher is not None
        if was_armed:
            self._watcher.stop()
            self._watcher = None
            self._on_arm_clicked()
        self.statusBar().showMessage(
            f"Settings saved — read: {new_watch} · share: {new_share} · db: {new_db}",
            5000,
        )

    def _open_shared_folder(self) -> None:
        import os
        try:
            os.startfile(str(self._settings.storage.shared_root))
        except OSError as e:
            QMessageBox.warning(self, "Cannot open folder", str(e))

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._watcher is not None:
            self._watcher.stop()
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            self._fetch_worker.wait(2000)
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        # Keep the processing overlay covering the whole window when visible.
        ov = getattr(self, "_processing_overlay", None)
        if ov is not None and ov.isVisible():
            ov.setGeometry(self.rect())

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        # Defer the gate one tick so the main window is fully painted first —
        # the gate sizes itself to the parent's geometry on first show.
        if not self._gate_shown:
            self._gate_shown = True
            QTimer.singleShot(50, self._show_startup_gate)

    def _show_startup_gate(self, *, exit_on_cancel: bool = True) -> None:
        """Display the modal sign-in card. Auto-arm capture on success and
        immediately ask the operator to choose a measurement mode.

        `exit_on_cancel`: True for the initial gate (cancelling = quit the
        program), False when the gate is re-shown after Cancel session
        (cancelling = stay on the empty main window).
        """
        gate = _StartupGate(self._lot_client, parent=self)
        result = gate.exec()
        if result != QDialog.DialogCode.Accepted:
            if exit_on_cancel:
                # First-time gate: Exit closes the program.
                QTimer.singleShot(0, self.close)
            return
        # Populate the (still-present) main-window inputs from the gate so the
        # rest of the workflow continues exactly as before.
        badge = gate.badge()
        self._operator_badge = badge
        self._badge_input.setText(badge)
        self._lot_input.setText(gate.lot_id())
        detail = gate.lot_detail()
        if detail is not None:
            self._on_fetch_success(detail)
        # Auto-arm: the operator just confirmed Badge + LOT, so start
        # watching the auto-save folder immediately. No separate Arm click.
        if self._watcher is None:
            self._on_arm_clicked()
        # Chain into mode-select popup.
        QTimer.singleShot(50, self._show_mode_select)

    def _show_mode_select(self) -> None:
        """Pop the mode-picker. Default to Per-location if cancelled."""
        dlg = _ModeSelectDialog(parent=self)
        dlg.exec()
        chosen = dlg.chosen_mode()
        # Default to Per-location if dialog dismissed.
        self._batch_mode = (chosen == _ModeSelectDialog.BATCH)
        self.statusBar().showMessage(
            "Batch mode — drop pairs into all 4 location slots, then Fuse"
            if self._batch_mode else
            "Per-location mode — drop a pair, click Fuse for the active location",
            6000,
        )
        self._update_input_state()

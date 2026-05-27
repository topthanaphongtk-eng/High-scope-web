from __future__ import annotations

import logging
import socket
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PyQt6.QtCore import QMimeData, QPoint, QSize, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDrag,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
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
from app.config import MssqlSettings, Settings
from app.models.capture import CaptureRecord
from app.models.lot import LotDetail
from app.services.capture import FileWatcher
from app.services.capture_db import CaptureDB
from app.services.image_fuse import focus_stack, load_as_bgr
from app.services.image_store import ImageStore
from app.services.lot_client import (
    LotClient,
    LotClientError,
    LotNotFound,
    ServerFault,
    ServerUnreachable,
)
from app.utils.app_icon import make_app_icon
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

QListWidget {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 4px;
}
QListWidget::item { border-radius: 6px; padding: 4px; margin: 2px; }
QListWidget::item:selected {
    background: #eef2ff; color: #1e293b; border: 1px solid #818cf8;
}
QListWidget::item:hover { background: #f8fafc; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical {
    background: #cbd5e1; border-radius: 5px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #94a3b8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

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

        outer_w, outer_h = self.DRAG_W + 6, self.DRAG_H + 6
        pix = QPixmap(outer_w, outer_h)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for off, alpha in ((3, 30), (2, 50), (1, 80)):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(15, 23, 42, alpha)))
            shadow_path = QPainterPath()
            shadow_path.addRoundedRect(
                3 + off, 3 + off, self.DRAG_W, self.DRAG_H, 8, 8,
            )
            painter.drawPath(shadow_path)
        card_rect = (3, 3, self.DRAG_W, self.DRAG_H)
        clip = QPainterPath()
        clip.addRoundedRect(*card_rect, 8, 8)
        painter.setClipPath(clip)
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
        painter.setPen(QPen(QColor("#4f46e5"), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outline = QPainterPath()
        outline.addRoundedRect(
            3 + 0.5, 3 + 0.5, self.DRAG_W - 1, self.DRAG_H - 1, 8, 8,
        )
        painter.drawPath(outline)
        painter.end()

        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(outer_w // 2, outer_h // 2))
        drag.exec(supportedActions)


class _DropCanvas(QLabel):
    """Drop target with a thumbnail preview when a path is dropped."""

    pathChanged = pyqtSignal(object)  # Path | None

    def __init__(self, hint: str = "") -> None:
        super().__init__()
        self._hint = hint
        self._path: Path | None = None
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_empty_style()

    def path(self) -> Path | None:
        return self._path

    def set_path(self, path: Path) -> None:
        if not path.exists():
            return
        try:
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

    def _apply_empty_style(self) -> None:
        self.setText(f"\n{self._hint}\n\n(drag image here)")
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


# ------------------------------------------------------------------ Sign-in gate


class _StartupGate(QDialog):
    """Modal sign-in card. The operator enters Badge + LOT before the main UI
    is interactive. Sits on the top layer with a soft backdrop so attention is
    pinned on the inputs."""

    def __init__(self, lot_client: LotClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lot_client = lot_client
        self._lot_detail: LotDetail | None = None
        self._fetch_worker: _FetchLotWorker | None = None

        self.setWindowTitle("Sign in")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setStyleSheet(
            "QDialog {"
            " background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #1e1b4b, stop:0.45 #0f172a, stop:1 #312e81);"
            "}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        hero = QFrame()
        hero.setStyleSheet("QFrame { background: transparent; }")
        hero_v = QVBoxLayout(hero)
        hero_v.setContentsMargins(0, 60, 0, 12)
        hero_v.setSpacing(6)
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
        tagline = QLabel("Image capture station")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setStyleSheet(
            "QLabel { color: #c7d2fe; font-size: 12px; letter-spacing: 1px; }"
        )
        hero_v.addWidget(logo)
        hero_v.addWidget(brand)
        hero_v.addWidget(tagline)

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

    def showEvent(self, e) -> None:  # type: ignore[override]
        super().showEvent(e)
        if self.parent() is not None:
            geo = self.parent().geometry()  # type: ignore[union-attr]
            self.setGeometry(geo)

    def keyPressEvent(self, e) -> None:  # type: ignore[override]
        if e.key() == Qt.Key.Key_Escape:
            e.ignore()
            return
        super().keyPressEvent(e)

    def reject(self) -> None:  # type: ignore[override]
        return

    def badge(self) -> str:
        return self._badge_input.text().strip().upper()

    def lot_id(self) -> str:
        return self._lot_input.text().strip()

    def lot_detail(self) -> LotDetail | None:
        return self._lot_detail

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


# ------------------------------------------------------------------ Mode picker


class _ModeSelectDialog(QDialog):
    """Pops up after sign-in. Operator picks Mode 1 (single fuse) or
    Mode 2 (Ball + Pad + Weld fuses)."""

    MODE_SINGLE = "mode1"
    MODE_TRIPLE = "mode2"

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
        card.setFixedWidth(620)

        card_v = QVBoxLayout(card)
        card_v.setContentsMargins(28, 26, 28, 24)
        card_v.setSpacing(14)

        title = QLabel("Choose capture mode")
        title.setStyleSheet(
            "QLabel { color: #0f172a; font-size: 22px; font-weight: 700; }"
        )
        subtitle = QLabel(
            "How many fused images do you want to save for this LOT?"
        )
        subtitle.setStyleSheet("QLabel { color: #64748b; font-size: 12px; }")
        subtitle.setWordWrap(True)
        card_v.addWidget(title)
        card_v.addWidget(subtitle)
        card_v.addSpacing(4)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        def make_card(label: str, hint: str, mode: str) -> QPushButton:
            btn = QPushButton(f"{label}\n\n{hint}")
            btn.setMinimumHeight(160)
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
            "🎯  200X Monitoring",
            "Drop 2 source images each for 1st Ball and 2nd Ball — the app "
            "fuses each pair and saves 2 fused images with the LOT.",
            self.MODE_SINGLE,
        )
        triple_btn = make_card(
            "⚡  Engineering lot",
            "Same workflow as 200X Monitoring (1st Ball + 2nd Ball) — tagged "
            "as engineering so the lot can be filtered separately on the web.",
            self.MODE_TRIPLE,
        )
        cards_row.addWidget(single_btn)
        cards_row.addWidget(triple_btn)
        card_v.addLayout(cards_row)

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


# ------------------------------------------------------------------ Save success


class _SaveSuccessDialog(QDialog):
    """Frameless success popup shown after a Confirm. Lists the fused images
    saved (filename + thumbnail) — no measurement values."""

    def __init__(
        self,
        *,
        lot_id: str,
        files: list[dict[str, Any]],
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

        v = QVBoxLayout(card)
        v.setContentsMargins(28, 24, 28, 22)
        v.setSpacing(12)

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
        n = len(files)
        sub = QLabel(
            f"<b>{n}</b> fused image{'s' if n != 1 else ''} saved for LOT "
            f"<b style='color:#4338ca'>{lot_id}</b>"
        )
        sub.setStyleSheet("QLabel { color: #475569; font-size: 12px; }")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        head.addLayout(title_box, 1)
        v.addLayout(head)

        for f in files:
            row = QHBoxLayout()
            row.setSpacing(10)
            thumb = QLabel()
            thumb.setFixedSize(84, 64)
            thumb.setStyleSheet(
                "QLabel { background: #0f172a; border-radius: 6px; }"
            )
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            try:
                pix = make_thumbnail(Path(f["fused_path"]), size=(84, 64))
                thumb.setPixmap(pix)
            except Exception:
                thumb.setText("—")
                thumb.setStyleSheet(
                    "QLabel { background: #f1f5f9; color: #94a3b8;"
                    " border-radius: 6px; font-size: 11px; }"
                )
            row.addWidget(thumb)

            text_box = QVBoxLayout()
            text_box.setSpacing(2)
            slot_lbl = QLabel(f"<b>{f['slot']}</b>")
            slot_lbl.setStyleSheet(
                "QLabel { color: #16a34a; font-size: 13px; }"
            )
            name_lbl = QLabel(f["fused_name"])
            name_lbl.setStyleSheet(
                "QLabel { color: #475569; font-size: 11px;"
                " font-family: Consolas, monospace; }"
            )
            name_lbl.setWordWrap(True)
            text_box.addWidget(slot_lbl)
            text_box.addWidget(name_lbl)
            row.addLayout(text_box, 1)
            v.addLayout(row)

        footer = QLabel("Records added to local database and shared folder.")
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
    """Translucent overlay shown during fuse + save. Backdrop blocks clicks
    on the main window, the centred card animates a spinner + status text
    so the operator can see what's running."""

    _SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("processing_overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#processing_overlay { background: rgba(15, 23, 42, 0.55); }"
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.installEventFilter(self)

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
        self._title = QLabel("Processing")
        self._title.setStyleSheet(
            "QLabel { color: #0f172a; font-size: 15px; font-weight: 700; }"
        )
        self._msg = QLabel("Working …")
        self._msg.setStyleSheet("QLabel { color: #64748b; font-size: 12px; }")
        self._msg.setWordWrap(True)
        title_box.addWidget(self._title)
        title_box.addWidget(self._msg)
        head_row.addLayout(title_box, 1)
        v.addLayout(head_row)

        self._sub = QLabel("This may take a few seconds.")
        self._sub.setStyleSheet("QLabel { color: #94a3b8; font-size: 11px; }")
        v.addWidget(self._sub)

        self._frame = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

        self.hide()

    def show_with(self, message: str = "Working …") -> None:
        self.set_message(message)
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]
        self.show()
        self.raise_()
        self._frame = 0
        self._timer.start()
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    def set_message(self, message: str) -> None:
        self._msg.setText(message)
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    def hide(self) -> None:  # type: ignore[override]
        self._timer.stop()
        super().hide()

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(self._SPINNER)
        self._spinner.setText(self._SPINNER[self._frame])

    def resizeEvent(self, e) -> None:  # type: ignore[override]
        super().resizeEvent(e)
        cx = (self.width() - self._card.width()) // 2
        cy = (self.height() - self._card.height()) // 2
        self._card.move(cx, cy)

    def eventFilter(self, obj, event):  # type: ignore[override]
        from PyQt6.QtCore import QEvent
        if event.type() in (QEvent.Type.MouseButtonPress,
                            QEvent.Type.MouseButtonDblClick):
            return True
        return super().eventFilter(obj, event)


# ------------------------------------------------------------------ Settings dialog


class _SettingsDialog(QDialog):
    """Edit the operator-facing settings:
        • Read folder (where Olympus auto-saves new TIFFs)
        • Share folder (where fused captures are stored)
        • SQL Server connection (server / database / user / password)
    Persists back to settings.yaml on Save. The caller is responsible for
    re-arming watchers / swapping ImageStore + DB using the returned values."""

    def __init__(
        self,
        watch_root: Path,
        shared_root: Path,
        mssql: MssqlSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._watch_root = Path(watch_root)
        self._shared_root = Path(shared_root)
        self._mssql = mssql.model_copy()

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
            "fused images are saved. Changes apply immediately."
        )
        subtitle.setStyleSheet("QLabel { color: #64748b; font-size: 12px; }")
        subtitle.setWordWrap(True)
        v.addWidget(title)
        v.addWidget(subtitle)
        v.addSpacing(4)

        read_lbl = QLabel("Read folder  (Olympus auto-save location)")
        read_lbl.setStyleSheet(
            "QLabel { color: #334155; font-size: 11px; font-weight: 600; }"
        )
        v.addWidget(read_lbl)
        self._watch_input = QLineEdit(str(self._watch_root))
        self._watch_input.setMinimumHeight(34)
        watch_btn = QPushButton("Browse…")
        watch_btn.clicked.connect(
            lambda: self._pick_folder(self._watch_input, "Choose read folder")
        )
        watch_row = QHBoxLayout()
        watch_row.setSpacing(8)
        watch_row.addWidget(self._watch_input, 1)
        watch_row.addWidget(watch_btn)
        v.addLayout(watch_row)

        share_lbl = QLabel("Share folder  (where fused images are saved)")
        share_lbl.setStyleSheet(
            "QLabel { color: #334155; font-size: 11px; font-weight: 600; }"
        )
        v.addWidget(share_lbl)
        self._share_input = QLineEdit(str(self._shared_root))
        self._share_input.setMinimumHeight(34)
        share_btn = QPushButton("Browse…")
        share_btn.clicked.connect(
            lambda: self._pick_folder(self._share_input, "Choose share folder")
        )
        share_row = QHBoxLayout()
        share_row.setSpacing(8)
        share_row.addWidget(self._share_input, 1)
        share_row.addWidget(share_btn)
        v.addLayout(share_row)

        db_lbl = QLabel(
            "SQL Server  (every station + web monitor points at the same "
            "instance — that's how history is shared)"
        )
        db_lbl.setStyleSheet(
            "QLabel { color: #334155; font-size: 11px; font-weight: 600; }"
        )
        db_lbl.setWordWrap(True)
        v.addWidget(db_lbl)

        self._mssql_server_input = QLineEdit(self._mssql.server)
        self._mssql_server_input.setPlaceholderText("server host or IP (e.g. mth-sql.local)")
        self._mssql_server_input.setMinimumHeight(34)
        v.addWidget(self._mssql_server_input)

        mssql_db_row = QHBoxLayout()
        mssql_db_row.setSpacing(8)
        self._mssql_db_input = QLineEdit(self._mssql.database)
        self._mssql_db_input.setPlaceholderText("database name")
        self._mssql_db_input.setMinimumHeight(34)
        self._mssql_port_input = QLineEdit(str(self._mssql.port))
        self._mssql_port_input.setPlaceholderText("port")
        self._mssql_port_input.setMinimumHeight(34)
        self._mssql_port_input.setFixedWidth(90)
        mssql_db_row.addWidget(self._mssql_db_input, 1)
        mssql_db_row.addWidget(self._mssql_port_input)
        v.addLayout(mssql_db_row)

        mssql_auth_row = QHBoxLayout()
        mssql_auth_row.setSpacing(8)
        self._mssql_user_input = QLineEdit(self._mssql.user)
        self._mssql_user_input.setPlaceholderText("user (blank = Windows auth)")
        self._mssql_user_input.setMinimumHeight(34)
        self._mssql_pwd_input = QLineEdit(self._mssql.password)
        self._mssql_pwd_input.setPlaceholderText("password")
        self._mssql_pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._mssql_pwd_input.setMinimumHeight(34)
        mssql_auth_row.addWidget(self._mssql_user_input, 1)
        mssql_auth_row.addWidget(self._mssql_pwd_input, 1)
        v.addLayout(mssql_auth_row)

        self._hint = QLabel("")
        self._hint.setStyleSheet(
            "QLabel { color: #b91c1c; font-size: 11px; padding-top: 4px; }"
        )
        self._hint.setWordWrap(True)
        v.addWidget(self._hint)

        v.addSpacing(8)

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
        start = target.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, title, start,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if chosen:
            target.setText(chosen)

    def _on_save(self) -> None:
        watch_text = self._watch_input.text().strip()
        share_text = self._share_input.text().strip()
        server_text = self._mssql_server_input.text().strip()
        db_text = self._mssql_db_input.text().strip()
        if not watch_text or not share_text or not server_text or not db_text:
            self._hint.setText("Read folder, share folder, server, and database are required.")
            return
        try:
            port = int(self._mssql_port_input.text().strip() or "1433")
        except ValueError:
            self._hint.setText("Port must be a number.")
            return
        try:
            self._watch_root = Path(watch_text)
            self._shared_root = Path(share_text)
        except Exception as e:
            self._hint.setText(f"Invalid path: {e}")
            return
        self._mssql = self._mssql.model_copy(update={
            "server": server_text,
            "database": db_text,
            "user": self._mssql_user_input.text().strip(),
            "password": self._mssql_pwd_input.text(),
            "port": port,
        })
        self.accept()

    def watch_root(self) -> Path:
        return self._watch_root

    def shared_root(self) -> Path:
        return self._shared_root

    def mssql(self) -> MssqlSettings:
        return self._mssql


# ------------------------------------------------------------------ Slot panel


# Slot accent colors — tints the top stripe + the status pill so each slot
# is visually distinct in Mode 2 without resorting to large text labels.
_SLOT_ACCENTS: dict[str, tuple[str, str]] = {
    # slot_name -> (accent hex, soft-tint hex)
    "1st Ball": ("#f59e0b", "#fef3c7"),  # amber — ball bond
    "2nd Ball": ("#8b5cf6", "#ede9fe"),  # violet — weld/stitch bond
}


class _FuseWorker(QThread):
    """Runs `load_as_bgr` + `focus_stack` off the GUI thread so the window
    stays responsive while a slot auto-fuses."""

    finished_ok = pyqtSignal(object)   # np.ndarray
    finished_err = pyqtSignal(str)

    def __init__(self, path_a: Path, path_b: Path) -> None:
        super().__init__()
        self._a = path_a
        self._b = path_b

    def run(self) -> None:
        try:
            img_a = load_as_bgr(self._a)
            img_b = load_as_bgr(self._b)
            fused = focus_stack(img_a, img_b)
        except Exception as e:
            log.exception("Fuse worker failed")
            self.finished_err.emit(str(e))
            return
        self.finished_ok.emit(fused)


class _FuseSlotPanel(QFrame):
    """One slot in the slot grid. Has 2 drop targets (image A + image B) and
    a large fused-preview canvas. Auto-fuses when both A and B paths are set.

    The card has a colored accent stripe (per slot), a header row with a
    status pill, two compact numbered drop targets, and a hero-sized fused
    preview that fills any extra vertical space — so a Mode 1 single-slot
    card occupies the whole right pane, and Mode 2 cards stretch evenly.
    """

    fusedReady = pyqtSignal(str)  # slot name

    _SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(
        self,
        slot_name: str,
        label: str,
        *,
        requires_fuse: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.slot_name = slot_name
        self._requires_fuse = requires_fuse
        self._fused: np.ndarray | None = None
        self._accent, self._tint = _SLOT_ACCENTS.get(slot_name, ("#4f46e5", "#eef2ff"))
        self._worker: _FuseWorker | None = None
        self._spinner_frame = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(90)
        self._spinner_timer.timeout.connect(self._tick_spinner)

        self.setObjectName("slot_card")
        self.setStyleSheet(
            "#slot_card {"
            " background: #ffffff; border-radius: 14px;"
            f" border: 1px solid #e2e8f0; border-top: 4px solid {self._accent};"
            "}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)

        # ---- Header row: title + status pill ----
        head = QHBoxLayout()
        head.setSpacing(10)

        title = QLabel(label.upper())
        title.setStyleSheet(
            "QLabel { color: #0f172a; font-size: 16px; font-weight: 700;"
            " letter-spacing: 1.2px; }"
        )
        head.addWidget(title)
        head.addStretch(1)

        self._status_pill = QLabel()
        self._status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_pill.setMinimumHeight(22)
        head.addWidget(self._status_pill)
        v.addLayout(head)

        # ---- Drop targets row ----
        # Fuse slots get two numbered, compact canvases linked by "+".
        # No-fuse slots (e.g. 2nd Ball) get a single, slightly larger canvas.
        drop_row = QHBoxLayout()
        drop_row.setSpacing(10)
        if requires_fuse:
            self._drop_a = _DropCanvas(hint="image  1")
            self._drop_a.setFixedSize(120, 88)
            self._drop_a.pathChanged.connect(self._maybe_fuse)
            self._drop_b = _DropCanvas(hint="image  2")
            self._drop_b.setFixedSize(120, 88)
            self._drop_b.pathChanged.connect(self._maybe_fuse)
            drop_row.addWidget(self._drop_a)

            # Subtle "+" between the two drops to visually link them
            plus = QLabel("+")
            plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
            plus.setStyleSheet(
                "QLabel { color: #cbd5e1; font-size: 22px; font-weight: 700;"
                " padding: 0 2px; }"
            )
            drop_row.addWidget(plus)
            drop_row.addWidget(self._drop_b)
        else:
            self._drop_a = _DropCanvas(hint="image")
            self._drop_a.setFixedSize(160, 88)
            self._drop_a.pathChanged.connect(self._maybe_fuse)
            self._drop_b = None  # type: ignore[assignment]
            drop_row.addWidget(self._drop_a)
        drop_row.addStretch(1)
        v.addLayout(drop_row)

        # ---- Hero fused preview ----
        self._fused_preview = QLabel()
        self._fused_preview.setMinimumHeight(220)
        self._fused_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Allow the preview to stretch to fill available vertical space.
        from PyQt6.QtWidgets import QSizePolicy
        self._fused_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        self._apply_fused_empty_style()
        v.addWidget(self._fused_preview, 1)

        self._set_status("empty")

    # ---- Status pill ----

    def _set_status(self, kind: str) -> None:
        # kind ∈ {empty, partial, fusing, ready, failed}
        text, fg, bg = {
            "empty":   ("●  Empty",         "#64748b", "#f1f5f9"),
            "partial": ("●  1 / 2 dropped", "#1d4ed8", "#dbeafe"),
            "fusing":  ("●  Fusing…",        "#b45309", "#fef3c7"),
            "ready":   ("✓  Ready",         "#15803d", "#dcfce7"),
            "failed":  ("✗  Failed",        "#b91c1c", "#fee2e2"),
        }[kind]
        self._status_pill.setText(text)
        self._status_pill.setStyleSheet(
            f"QLabel {{ color: {fg}; background: {bg};"
            " padding: 3px 10px; border-radius: 10px;"
            " font-size: 11px; font-weight: 700;"
            " letter-spacing: 0.4px; }}"
        )

    # ---- Empty / filled / failed styling for the fused canvas ----

    def _apply_fused_empty_style(self) -> None:
        if self._requires_fuse:
            hint = "Drop image 1 + image 2 above\nthe fused result will appear here"
        else:
            hint = "Drop a single image above\nit will be saved as-is (no fusing)"
        self._fused_preview.setText(hint)
        self._fused_preview.setStyleSheet(
            "QLabel { background: #f8fafc; border: 2px dashed #cbd5e1;"
            " border-radius: 10px; color: #94a3b8; font-size: 12px;"
            " padding: 24px; }"
        )

    def _apply_fused_filled_style(self) -> None:
        self._fused_preview.setStyleSheet(
            "QLabel { background: #0f172a; border: 1px solid #1e293b;"
            " border-radius: 10px; }"
        )

    def _apply_fused_failed_style(self) -> None:
        self._fused_preview.setStyleSheet(
            "QLabel { background: #fef2f2; border: 2px dashed #fca5a5;"
            " border-radius: 10px; color: #b91c1c; font-size: 12px;"
            " padding: 24px; }"
        )

    def _apply_fused_busy_style(self) -> None:
        self._fused_preview.setStyleSheet(
            "QLabel { background: #fef3c7; border: 2px dashed #f59e0b;"
            " border-radius: 10px; color: #92400e; font-size: 13px;"
            " font-weight: 600; padding: 24px; }"
        )

    def _tick_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(self._SPINNER_FRAMES)
        glyph = self._SPINNER_FRAMES[self._spinner_frame]
        self._fused_preview.setText(
            f"{glyph}\n\nFusing focus stack…\nrunning ECC alignment + Laplacian merge"
        )

    # ---- Fuse pipeline (async) ----

    def _stop_worker(self) -> None:
        """Detach + cancel any in-flight worker. Called on path changes so a
        rapid second drop supersedes a still-running fuse without us mixing
        up which result corresponds to which inputs."""
        if self._worker is None:
            return
        try:
            self._worker.finished_ok.disconnect()
            self._worker.finished_err.disconnect()
        except (TypeError, RuntimeError):
            pass
        # We can't safely interrupt a worker mid-OpenCV call — just let it
        # finish into a discarded sink. New worker takes over the UI.
        self._worker = None

    def _maybe_fuse(self, _path: object) -> None:
        a = self._drop_a.path()

        # Cancel any running fuse — its result is no longer wanted.
        self._stop_worker()
        self._spinner_timer.stop()

        # No-fuse slot: a single image. Load it directly and we're done.
        if not self._requires_fuse:
            if a is None:
                self._fused = None
                self._fused_preview.clear()
                self._apply_fused_empty_style()
                self._set_status("empty")
                return
            try:
                img = load_as_bgr(a)
            except Exception:
                self._fused = None
                self._fused_preview.setText("⚠  failed to read image")
                self._apply_fused_failed_style()
                self._set_status("failed")
                return
            self._fused = img
            self._set_fused_pixmap(img)
            self._set_status("ready")
            self.fusedReady.emit(self.slot_name)
            return

        b = self._drop_b.path()

        if a is None and b is None:
            self._fused = None
            self._fused_preview.clear()
            self._apply_fused_empty_style()
            self._set_status("empty")
            return
        if a is None or b is None:
            self._fused = None
            self._fused_preview.clear()
            self._apply_fused_empty_style()
            self._set_status("partial")
            return

        # Busy state — both paths set, kick off async fuse.
        self._fused = None
        self._fused_preview.clear()
        self._apply_fused_busy_style()
        self._set_status("fusing")
        self._spinner_frame = 0
        self._tick_spinner()
        self._spinner_timer.start()

        worker = _FuseWorker(a, b)
        worker.finished_ok.connect(self._on_fuse_done)
        worker.finished_err.connect(self._on_fuse_failed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    @pyqtSlot(object)
    def _on_fuse_done(self, fused: np.ndarray) -> None:
        self._spinner_timer.stop()
        self._worker = None
        self._fused = fused
        self._set_fused_pixmap(fused)
        self._set_status("ready")
        self.fusedReady.emit(self.slot_name)

    @pyqtSlot(str)
    def _on_fuse_failed(self, _msg: str) -> None:
        self._spinner_timer.stop()
        self._worker = None
        self._fused = None
        self._fused_preview.setText("⚠  fuse failed — try different images")
        self._apply_fused_failed_style()
        self._set_status("failed")

    def _set_fused_pixmap(self, bgr: np.ndarray) -> None:
        h, w = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        target_w = max(self._fused_preview.width(), 1)
        target_h = max(self._fused_preview.height(), 1)
        pix = QPixmap.fromImage(qimg).scaled(
            target_w, target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._fused_preview.setPixmap(pix)
        self._apply_fused_filled_style()

    def resizeEvent(self, e) -> None:  # type: ignore[override]
        super().resizeEvent(e)
        if self._fused is not None:
            self._set_fused_pixmap(self._fused)

    def fused(self) -> np.ndarray | None:
        return self._fused

    def has_fused(self) -> bool:
        return self._fused is not None

    def reset(self) -> None:
        self._stop_worker()
        self._spinner_timer.stop()
        self._drop_a.clear()
        if self._drop_b is not None:
            self._drop_b.clear()
        self._fused = None
        self._fused_preview.clear()
        self._apply_fused_empty_style()
        self._set_status("empty")


# ------------------------------------------------------------------ Main window


# (slot_name, label, requires_fuse). 1st Ball = ball bond → fuse 2 frames.
# 2nd Ball = weld/stitch bond → operator drops a single frame, no fuse.
_MODE_SLOTS: dict[str, list[tuple[str, str, bool]]] = {
    _ModeSelectDialog.MODE_SINGLE: [
        ("1st Ball", "1st Ball", True),
        ("2nd Ball", "2nd Ball", False),
    ],
    _ModeSelectDialog.MODE_TRIPLE: [
        ("1st Ball", "1st Ball", True),
        ("2nd Ball", "2nd Ball", False),
    ],
}


class MainWindow(QMainWindow):
    """Operator workflow: Sign in → choose mode → drop pairs → auto-fuse →
    Confirm & Save → loop back to sign-in."""

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
        self._db = CaptureDB(settings.mssql)
        self._watcher: FileWatcher | None = None

        self._current_lot: LotDetail | None = None
        self._operator_badge: str = ""
        self._mode: str = _ModeSelectDialog.MODE_SINGLE
        self._slot_panels: list[_FuseSlotPanel] = []

        self.setWindowIcon(make_app_icon())
        self._build_ui()
        self.setStyleSheet(_MODERN_QSS)
        self._processing_overlay = _ProcessingOverlay(self)
        self._file_ready_signal.connect(self._on_file_ready)
        self._gate_shown = False

    # ---------- UI construction ----------

    def _build_ui(self) -> None:
        self.setWindowTitle(f"High Scope Capture  v{APP_VERSION}")
        self.resize(1240, 860)

        # Menu bar
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self._open_settings_dialog)
        file_menu.addAction(settings_action)
        open_share_action = QAction("Open share folder", self)
        open_share_action.triggered.connect(self._open_shared_folder)
        file_menu.addAction(open_share_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(14)

        # ---- Header card: operator avatar + LOT chips + mode pill ----
        self._header_card = QFrame()
        self._header_card.setObjectName("header_card")
        self._header_card.setStyleSheet(
            "#header_card { background: #ffffff; border-radius: 14px;"
            " border: 1px solid #e2e8f0; }"
        )
        head_lay = QHBoxLayout(self._header_card)
        head_lay.setContentsMargins(18, 14, 18, 14)
        head_lay.setSpacing(16)

        self._avatar = QLabel("—")
        self._avatar.setFixedHeight(36)
        self._avatar.setMinimumWidth(48)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setStyleSheet(
            "QLabel { background: #eef2ff; color: #4338ca;"
            " border-radius: 18px; padding: 0 16px;"
            " font-size: 13px; font-weight: 700; letter-spacing: 0.5px;"
            " font-family: Consolas, 'Courier New', monospace; }"
        )
        head_lay.addWidget(self._avatar)

        head_text = QVBoxLayout()
        head_text.setSpacing(4)
        self._head_primary = QLabel("Sign in to begin")
        self._head_primary.setStyleSheet(
            "QLabel { color: #0f172a; font-size: 16px; font-weight: 700; }"
        )
        self._head_secondary = QLabel("")
        self._head_secondary.setStyleSheet(
            "QLabel { color: #64748b; font-size: 12px; }"
        )
        self._head_secondary.setTextFormat(Qt.TextFormat.RichText)
        head_text.addWidget(self._head_primary)
        head_text.addWidget(self._head_secondary)
        head_lay.addLayout(head_text, 1)

        self._mode_pill = QLabel("")
        self._mode_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode_pill.setStyleSheet(
            "QLabel { background: #fef3c7; color: #92400e;"
            " padding: 6px 14px; border-radius: 14px;"
            " font-size: 11px; font-weight: 700; letter-spacing: 1px; }"
        )
        self._mode_pill.setVisible(False)
        head_lay.addWidget(self._mode_pill)
        root.addWidget(self._header_card)

        # ---- Body: sidebar (recent captures) + slot grid ----
        body = QHBoxLayout()
        body.setSpacing(14)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar_card")
        sidebar.setStyleSheet(
            "#sidebar_card { background: #ffffff; border-radius: 14px;"
            " border: 1px solid #e2e8f0; }"
        )
        sidebar.setFixedWidth(232)
        side_lay = QVBoxLayout(sidebar)
        side_lay.setContentsMargins(14, 14, 14, 14)
        side_lay.setSpacing(8)

        list_head = QHBoxLayout()
        list_head.setSpacing(8)
        list_title = QLabel("RECENT")
        list_title.setStyleSheet(
            "QLabel { color: #4338ca; font-size: 10px; font-weight: 700;"
            " letter-spacing: 1.8px; }"
        )
        list_head.addWidget(list_title)
        list_head.addStretch(1)
        self._list_count = QLabel("0")
        self._list_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._list_count.setMinimumWidth(28)
        self._list_count.setStyleSheet(
            "QLabel { background: #eef2ff; color: #4338ca; border-radius: 9px;"
            " padding: 1px 8px; font-size: 10px; font-weight: 700; }"
        )
        list_head.addWidget(self._list_count)
        side_lay.addLayout(list_head)

        list_hint = QLabel("Drag a thumbnail into a slot")
        list_hint.setStyleSheet(
            "QLabel { color: #94a3b8; font-size: 11px; }"
        )
        side_lay.addWidget(list_hint)

        self._thumbnail_list = _DragThumbnailList()
        self._thumbnail_list.setIconSize(QSize(*THUMBNAIL_SIZE))
        self._thumbnail_list.setDragEnabled(True)
        self._thumbnail_list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        self._thumbnail_list.setStyleSheet(
            "QListWidget { background: #f8fafc; border: 1px solid #e2e8f0;"
            " border-radius: 8px; padding: 4px; }"
            "QListWidget::item { border-radius: 6px; padding: 4px; margin: 2px; }"
            "QListWidget::item:selected {"
            " background: #eef2ff; color: #1e293b;"
            " border: 1px solid #818cf8; }"
            "QListWidget::item:hover { background: #ffffff; }"
        )
        side_lay.addWidget(self._thumbnail_list, 1)
        body.addWidget(sidebar)

        # Right: slot grid (built by _rebuild_slot_grid based on mode)
        self._slots_host = QWidget()
        self._slots_layout = QHBoxLayout(self._slots_host)
        self._slots_layout.setContentsMargins(0, 0, 0, 0)
        self._slots_layout.setSpacing(14)
        self._slots_layout.addStretch(1)

        slots_scroll = QScrollArea()
        slots_scroll.setWidget(self._slots_host)
        slots_scroll.setWidgetResizable(True)
        slots_scroll.setFrameShape(QFrame.Shape.NoFrame)
        slots_scroll.setStyleSheet(
            "QScrollArea { background: transparent; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        body.addWidget(slots_scroll, 1)

        root.addLayout(body, 1)

        # ---- Action strip ----
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self._cancel_btn = QPushButton("Cancel session")
        self._cancel_btn.setObjectName("danger")
        self._cancel_btn.setMinimumHeight(42)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        actions.addWidget(self._cancel_btn)
        actions.addStretch(1)

        self._progress_pill = QLabel("0 / 1 fused")
        self._progress_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_pill.setMinimumHeight(30)
        self._progress_pill.setStyleSheet(
            "QLabel { background: #f1f5f9; color: #64748b;"
            " padding: 6px 16px; border-radius: 15px;"
            " font-size: 12px; font-weight: 700; letter-spacing: 0.4px; }"
        )
        actions.addWidget(self._progress_pill)
        actions.addStretch(1)

        self._confirm_btn = QPushButton("✓  Confirm & Save")
        self._confirm_btn.setObjectName("success")
        self._confirm_btn.setMinimumHeight(42)
        self._confirm_btn.setMinimumWidth(240)
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.clicked.connect(self._on_confirm_clicked)
        actions.addWidget(self._confirm_btn)
        root.addLayout(actions)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self._refresh_header()

    def _rebuild_slot_grid(self) -> None:
        # Clear existing slots
        while self._slots_layout.count():
            item = self._slots_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._slot_panels = []

        slots = _MODE_SLOTS[self._mode]
        # Mode 1: one slot — centre it with stretch on either side and cap
        # the card width so it doesn't sprawl across the whole pane.
        # Mode 2: three slots — equal stretch, no caps, cards expand together.
        single = len(slots) == 1
        if single:
            self._slots_layout.addStretch(1)
        for slot_name, label, requires_fuse in slots:
            panel = _FuseSlotPanel(
                slot_name, label,
                requires_fuse=requires_fuse,
                parent=self._slots_host,
            )
            panel.fusedReady.connect(self._on_slot_fused)
            if single:
                panel.setMaximumWidth(620)
                panel.setMinimumWidth(420)
            self._slot_panels.append(panel)
            self._slots_layout.addWidget(panel, 0 if single else 1)
        self._slots_layout.addStretch(1)
        self._refresh_confirm_state()

    def _refresh_header(self) -> None:
        if not self._operator_badge or self._current_lot is None:
            self._avatar.setText("—")
            self._head_primary.setText("Sign in to begin")
            self._head_secondary.setText("")
            self._mode_pill.setVisible(False)
            return
        d = self._current_lot
        b = (self._operator_badge or "").strip()
        self._avatar.setText(b or "—")

        self._head_primary.setText(
            f"LOT  {d.lot_id or '—'}"
        )
        chips = []
        for label, val in (
            ("Operator", self._operator_badge),
            ("Bonding", d.bonding_running or "—"),
            ("Machine", d.lot_location or "—"),
            ("MPC", d.mpc or "—"),
            ("Pkg", d.package or "—"),
        ):
            chips.append(
                f"<span style='color:#94a3b8'>{label}</span>"
                f"&nbsp;&nbsp;<b style='color:#334155'>{val}</b>"
            )
        sep = "<span style='color:#cbd5e1'>&nbsp;&nbsp;·&nbsp;&nbsp;</span>"
        self._head_secondary.setText(sep.join(chips))

        if self._mode == _ModeSelectDialog.MODE_SINGLE:
            self._mode_pill.setText("200X MONITORING  ·  1st + 2nd BALL")
            self._mode_pill.setStyleSheet(
                "QLabel { background: #eef2ff; color: #4338ca;"
                " padding: 6px 14px; border-radius: 14px;"
                " font-size: 11px; font-weight: 700; letter-spacing: 1px; }"
            )
        else:
            self._mode_pill.setText("ENGINEERING LOT  ·  1st + 2nd BALL")
            self._mode_pill.setStyleSheet(
                "QLabel { background: #fef3c7; color: #92400e;"
                " padding: 6px 14px; border-radius: 14px;"
                " font-size: 11px; font-weight: 700; letter-spacing: 1px; }"
            )
        self._mode_pill.setVisible(True)

    def _refresh_confirm_state(self) -> None:
        n_total = len(self._slot_panels)
        n_done = sum(1 for p in self._slot_panels if p.has_fused())
        ready = n_total > 0 and n_done == n_total
        self._confirm_btn.setEnabled(ready and self._current_lot is not None)
        # Progress pill — neutral while incomplete, green when all slots ready.
        if n_total == 0:
            self._progress_pill.setText("waiting")
            self._progress_pill.setStyleSheet(
                "QLabel { background: #f1f5f9; color: #94a3b8;"
                " padding: 6px 16px; border-radius: 15px;"
                " font-size: 12px; font-weight: 700; letter-spacing: 0.4px; }"
            )
        elif ready:
            self._progress_pill.setText(f"✓  {n_done} / {n_total} fused — ready to save")
            self._progress_pill.setStyleSheet(
                "QLabel { background: #dcfce7; color: #15803d;"
                " padding: 6px 16px; border-radius: 15px;"
                " font-size: 12px; font-weight: 700; letter-spacing: 0.4px; }"
            )
        else:
            self._progress_pill.setText(f"{n_done} / {n_total} fused")
            self._progress_pill.setStyleSheet(
                "QLabel { background: #f1f5f9; color: #64748b;"
                " padding: 6px 16px; border-radius: 15px;"
                " font-size: 12px; font-weight: 700; letter-spacing: 0.4px; }"
            )

    # ---------- File watcher ----------

    def _arm_watcher(self) -> None:
        if self._watcher is not None:
            return
        try:
            self._watcher = FileWatcher(
                self._settings.capture.watch_root,
                self._settings.capture.file_patterns,
                on_ready=self._watcher_callback,
                recursive=self._settings.capture.recursive,
                stable_poll_ms=self._settings.capture.stable_poll_ms,
                stable_required_checks=self._settings.capture.stable_required_checks,
            )
            self._watcher.start()
            self.statusBar().showMessage(
                f"Watching {self._settings.capture.watch_root}", 4000,
            )
        except Exception as e:
            log.exception("Could not start FileWatcher")
            self._watcher = None
            QMessageBox.warning(
                self, "Cannot watch capture folder",
                f"Could not start the file watcher on:\n"
                f"{self._settings.capture.watch_root}\n\n{e}",
            )

    def _watcher_callback(self, path: Path) -> None:
        # Watcher fires on a worker thread; bounce to GUI thread via signal.
        self._file_ready_signal.emit(str(path))

    @pyqtSlot(str)
    def _on_file_ready(self, path_str: str) -> None:
        path = Path(path_str)
        try:
            pix = make_thumbnail(path)
        except Exception:
            log.exception("Thumbnail generation failed for %s", path)
            return
        item = QListWidgetItem()
        item.setIcon(self._icon_from_pixmap(pix))
        item.setText(path.name)
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        item.setSizeHint(QSize(THUMBNAIL_SIZE[0] + 16, THUMBNAIL_SIZE[1] + 28))
        self._thumbnail_list.insertItem(0, item)
        # Keep at most 60 items so the list doesn't grow forever in long sessions.
        while self._thumbnail_list.count() > 60:
            self._thumbnail_list.takeItem(self._thumbnail_list.count() - 1)
        self._list_count.setText(str(self._thumbnail_list.count()))

    @staticmethod
    def _icon_from_pixmap(pix: QPixmap):
        from PyQt6.QtGui import QIcon
        return QIcon(pix)

    # ---------- Slot fuse callback ----------

    def _on_slot_fused(self, _slot: str) -> None:
        self._refresh_confirm_state()

    # ---------- Confirm flow ----------

    def _on_confirm_clicked(self) -> None:
        if self._current_lot is None:
            return
        if not all(p.has_fused() for p in self._slot_panels):
            return
        d = self._current_lot
        raw = d.raw or {}
        lot_info: dict[str, Any] = {
            "lot_id": d.lot_id,
            "lot_location": d.lot_location,
            "mpc": d.mpc,
            "package": d.package,
            "bonding_running": d.bonding_running,
            "qs": d.qs,
            "wire": raw.get("Wire"),
            "wire_type": raw.get("WireType"),
        }

        self._processing_overlay.show_with("Saving fused images …")

        files: list[dict[str, Any]] = []
        try:
            now = datetime.now().astimezone()
            for panel in self._slot_panels:
                fused = panel.fused()
                if fused is None:
                    continue
                self._processing_overlay.set_message(
                    f"Saving {panel.slot_name} fused image …"
                )
                record = self._store.save_fused(
                    fused,
                    lot_id=d.lot_id or "UNKNOWN",
                    badge=self._operator_badge,
                    lot_info=lot_info,
                    slot=panel.slot_name,
                    acquired_at=now,
                )
                files.append({
                    "slot": panel.slot_name,
                    "fused_path": str(record.stored_path),
                    "fused_name": record.stored_name,
                    "size_bytes": record.size_bytes,
                    "sha256": record.sha256,
                })

            self._processing_overlay.set_message("Recording captures to database …")
            capture_id = self._db.insert_capture(
                lot_id=d.lot_id or "UNKNOWN",
                bonding_number=d.bonding_running,
                operator_badge=self._operator_badge,
                mode=self._mode,
                files=files,
                lot_info=lot_info,
                app_version=APP_VERSION,
            )
            try:
                self._db.mirror_capture_to_share(
                    capture_id, self._settings.storage.shared_root,
                )
            except Exception:
                log.exception("Could not mirror capture record to share folder")
        except Exception as e:
            log.exception("Confirm & Save failed")
            self._processing_overlay.hide()
            QMessageBox.critical(
                self, "Save failed",
                f"Could not save the fused images:\n\n{e}",
            )
            return

        self._processing_overlay.hide()

        dlg = _SaveSuccessDialog(
            lot_id=d.lot_id or "UNKNOWN",
            files=files,
            parent=self,
        )
        dlg.exec()

        # Reset for next LOT
        self._reset_session()
        QTimer.singleShot(50, self._show_startup_gate)

    # ---------- Reset / Cancel ----------

    def _reset_session(self) -> None:
        for panel in self._slot_panels:
            panel.reset()
        self._current_lot = None
        self._operator_badge = ""
        self._refresh_header()
        self._refresh_confirm_state()
        # Drop the recent-captures list from prior LOT — next operator gets a clean slate.
        self._thumbnail_list.clear()
        self._list_count.setText("0")

    def _on_cancel_clicked(self) -> None:
        if not any(p.has_fused() for p in self._slot_panels):
            self._reset_session()
            QTimer.singleShot(50, self._show_startup_gate)
            return
        confirm = QMessageBox.question(
            self, "Cancel session?",
            "Discard all dropped images and fused previews?\n\n"
            "Nothing will be saved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._reset_session()
        QTimer.singleShot(50, self._show_startup_gate)

    # ---------- Settings ----------

    def _open_settings_dialog(self) -> None:
        dlg = _SettingsDialog(
            watch_root=self._settings.capture.watch_root,
            shared_root=self._settings.storage.shared_root,
            mssql=self._settings.mssql,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_watch = dlg.watch_root()
        new_share = dlg.shared_root()
        new_mssql = dlg.mssql()

        self._settings.capture.watch_root = new_watch
        self._settings.storage.shared_root = new_share
        self._settings.mssql = new_mssql

        if self._settings_path is not None:
            try:
                self._settings.to_yaml(self._settings_path)
                log.info("settings written to %s", self._settings_path)
            except Exception as e:
                log.exception("failed to save settings.yaml")
                QMessageBox.warning(
                    self, "Saved in memory only",
                    "Could not write settings.yaml:\n\n"
                    f"{e}\n\nChanges apply to this session but won't persist after restart.",
                )

        self._store = ImageStore(
            shared_root=new_share,
            compute_sha256=self._settings.storage.compute_sha256,
        )
        try:
            self._db = CaptureDB(new_mssql)
        except Exception as e:
            log.exception("could not connect to SQL Server %s", new_mssql.server)
            QMessageBox.warning(
                self, "Database not reachable",
                f"Couldn't connect to SQL Server:\n"
                f"{new_mssql.server}/{new_mssql.database}\n\n{e}\n\n"
                "Old connection will keep being used until the settings are fixed.",
            )

        was_armed = self._watcher is not None
        if was_armed:
            self._watcher.stop()
            self._watcher = None
            self._arm_watcher()
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

    # ---------- Lifecycle ----------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._watcher is not None:
            self._watcher.stop()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        ov = getattr(self, "_processing_overlay", None)
        if ov is not None and ov.isVisible():
            ov.setGeometry(self.rect())

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._gate_shown:
            self._gate_shown = True
            QTimer.singleShot(50, self._show_startup_gate)

    def _show_startup_gate(self, *, exit_on_cancel: bool = True) -> None:
        gate = _StartupGate(self._lot_client, parent=self)
        result = gate.exec()
        if result != QDialog.DialogCode.Accepted:
            if exit_on_cancel and self._current_lot is None:
                QTimer.singleShot(0, self.close)
            return

        self._operator_badge = gate.badge()
        self._current_lot = gate.lot_detail()

        if self._watcher is None:
            self._arm_watcher()

        QTimer.singleShot(50, self._show_mode_select)

    def _show_mode_select(self) -> None:
        dlg = _ModeSelectDialog(parent=self)
        dlg.exec()
        chosen = dlg.chosen_mode() or _ModeSelectDialog.MODE_SINGLE
        self._mode = chosen
        self._rebuild_slot_grid()
        self._refresh_header()
        self.statusBar().showMessage(
            "Engineering lot — drop pairs into 1st Ball and 2nd Ball; auto-fuses when both A+B are set"
            if self._mode == _ModeSelectDialog.MODE_TRIPLE else
            "200X Monitoring — drop pairs into 1st Ball and 2nd Ball; auto-fuses when both A+B are set",
            6000,
        )

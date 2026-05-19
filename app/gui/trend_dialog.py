"""Pop-up shown after Confirm & Save: trend charts for the bonding number
of the LOT that was just saved.

Two stacked subplots:
  • Ball d  (per location, last N LOTs)
  • GAP min (per location, last N LOTs)

The current LOT's points are highlighted with a larger marker so the
operator can spot drift relative to recent history at a glance.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from app.models.capture import LOCATION_ORDER


_LOC_COLORS = {
    "TL": "#4f46e5",  # indigo
    "TR": "#16a34a",  # green
    "BL": "#ea580c",  # orange
    "BR": "#a14ba1",  # purple
}


class TrendDialog(QDialog):
    """Display ball + gap trend lines for a bonding number.

    `rows` — list of dicts straight from `MeasurementDB.history_for_bonding`,
    sorted chronologically, oldest first. Each row has keys:
        confirmed_at, lot_id, bonding_number, location, pad_index,
        ball_d_um, gap_min_um, ...
    `current_lot_id` — highlight rows belonging to this LOT.
    """

    def __init__(
        self,
        bonding_number: str,
        rows: list[dict[str, Any]],
        current_lot_id: str,
        unit: str = "um",
        lot_location: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        machine_label = lot_location or "—"
        self.setWindowTitle(
            f"Trend — bonding {bonding_number} @ {machine_label}"
        )
        self.setModal(True)
        # Wider min size so the chart's right-edge UCL/LCL labels and the
        # title bar text never get clipped on common 1080p displays.
        self.setMinimumSize(1080, 700)
        self.resize(1180, 760)
        self.setStyleSheet("QDialog { background: #f1f5f9; }")

        scale = 1.0 / 25.4 if unit == "mil" else 1.0
        u = "mil" if unit == "mil" else "µm"

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        # Header — bonding × machine pair. Wraps to a second line if the
        # bonding number / machine name combination is long.
        title = QLabel(
            f"<span style='font-size:18px;color:#0f172a'>Trend</span>"
            f"<span style='color:#94a3b8'>  ·  </span>"
            f"<span style='font-size:18px;color:#0f172a'>bonding "
            f"<b>{bonding_number}</b></span>"
            f"<span style='color:#94a3b8'>  ·  </span>"
            f"<span style='font-size:18px'>machine "
            f"<b style='color:#4338ca'>{machine_label}</b></span>"
        )
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet("QLabel { padding: 2px 0; }")
        root.addWidget(title)

        n_lots = len({r["lot_id"] for r in rows})
        sub = QLabel(
            f"Last {n_lots} LOT(s) for this bonding × machine — "
            f"current LOT <b style='color:#16a34a'>{current_lot_id}</b> "
            f"highlighted."
        )
        sub.setStyleSheet("QLabel { color: #64748b; font-size: 12px; }")
        sub.setWordWrap(True)
        root.addWidget(sub)

        if not rows:
            empty = QLabel(
                "No prior measurements for this bonding number. "
                "Save more LOTs to start building history."
            )
            empty.setStyleSheet("QLabel { color: #94a3b8; padding: 40px; }")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(empty, 1)
        else:
            canvas = self._build_canvas(rows, current_lot_id, scale, u)
            root.addWidget(canvas, 1)

        # Footer buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.setMinimumHeight(34)
        close.clicked.connect(self.accept)
        btn_row.addWidget(close)
        root.addLayout(btn_row)

    def _build_canvas(
        self,
        rows: list[dict[str, Any]],
        current_lot_id: str,
        scale: float,
        unit_label: str,
    ) -> FigureCanvas:
        # Collect chronological list of distinct LOT ids.
        ordered_lots: list[str] = []
        seen: set[str] = set()
        for r in rows:
            lid = r["lot_id"]
            if lid not in seen:
                seen.add(lid)
                ordered_lots.append(lid)
        lot_idx = {lid: i for i, lid in enumerate(ordered_lots)}

        # Pool ALL detection rows for each LOT (across the 4 locations + any
        # multiple pads), then take the mean. One value per LOT per metric.
        ball_pool: dict[int, list[float]] = defaultdict(list)
        gap_pool: dict[int, list[float]] = defaultdict(list)
        for r in rows:
            i = lot_idx[r["lot_id"]]
            if r.get("ball_d_um") is not None:
                ball_pool[i].append(float(r["ball_d_um"]) * scale)
            if r.get("gap_min_um") is not None:
                gap_pool[i].append(float(r["gap_min_um"]) * scale)

        fig = Figure(figsize=(10.5, 7.0), dpi=120, facecolor="#f8fafc")
        # Slightly larger top margin for the per-axis stats banner.
        ax_ball = fig.add_subplot(2, 1, 1)
        ax_gap = fig.add_subplot(2, 1, 2)

        cur_idx = lot_idx.get(current_lot_id, -1)

        def _plot_series(
            ax,
            pool: dict[int, list[float]],
            ylabel: str,
            line_color: str,
            band_color: str,
        ) -> None:
            xs = sorted(pool.keys())
            ys = [sum(pool[i]) / len(pool[i]) for i in xs]
            if not ys:
                ax.text(
                    0.5, 0.5, "no data", ha="center", va="center",
                    transform=ax.transAxes, color="#94a3b8", fontsize=14,
                )
                return

            # ---- Statistical control limits (3σ) from history ----
            base = ys[:-1] if len(ys) > 3 else ys
            mean_v: float | None = None
            ucl: float | None = None
            lcl: float | None = None
            if len(base) >= 3:
                mean_v = sum(base) / len(base)
                var = sum((v - mean_v) ** 2 for v in base) / (len(base) - 1)
                sigma = var ** 0.5
                ucl = mean_v + 3 * sigma
                lcl = mean_v - 3 * sigma

                # Shaded ±3σ band — soft pastel matching the metric color.
                ax.axhspan(lcl, ucl, color=band_color, alpha=0.18, zorder=0)
                # Mean centerline (solid)
                ax.axhline(
                    mean_v, color="#0ea5e9", linewidth=1.6,
                    linestyle="-", alpha=0.85,
                )
                # UCL / LCL (dashed red)
                ax.axhline(
                    ucl, color="#dc2626", linewidth=1.5,
                    linestyle=(0, (6, 4)), alpha=0.9,
                )
                ax.axhline(
                    lcl, color="#dc2626", linewidth=1.5,
                    linestyle=(0, (6, 4)), alpha=0.9,
                )

            # Subtle fill below the trend line for visual weight.
            ax.fill_between(
                xs, ys, min(ys) - (max(ys) - min(ys)) * 0.05 if max(ys) > min(ys) else min(ys) - 1,
                color=line_color, alpha=0.08, zorder=1,
            )
            # Trend line.
            ax.plot(
                xs, ys, marker="o", markersize=7, linewidth=2.2,
                color=line_color, alpha=0.95, zorder=3,
                markerfacecolor="white", markeredgewidth=2,
                markeredgecolor=line_color,
            )

            # Out-of-control points: bigger red marker.
            if ucl is not None and lcl is not None:
                ooc_x = [i for i, v in zip(xs, ys) if v > ucl or v < lcl]
                ooc_y = [v for v in ys if v > ucl or v < lcl]
                if ooc_x:
                    ax.plot(
                        ooc_x, ooc_y, marker="o", markersize=12,
                        markerfacecolor="#dc2626", markeredgecolor="white",
                        markeredgewidth=2, linestyle="none", zorder=5,
                    )

            # Big highlight on the current LOT + value annotation.
            if cur_idx in pool:
                cur_y = sum(pool[cur_idx]) / len(pool[cur_idx])
                ax.plot(
                    cur_idx, cur_y, marker="o", markersize=15,
                    markerfacecolor=line_color, markeredgecolor="white",
                    markeredgewidth=2.5, zorder=6,
                )
                # Big bold value bubble next to the current marker.
                ax.annotate(
                    f"{cur_y:.2f}",
                    xy=(cur_idx, cur_y),
                    xytext=(8, 14),
                    textcoords="offset points",
                    fontsize=13, fontweight="bold",
                    color="#0f172a",
                    bbox=dict(
                        boxstyle="round,pad=0.45",
                        facecolor="white", edgecolor=line_color, linewidth=1.5,
                    ),
                    zorder=7,
                )

            # ---- Right-edge limit labels (UCL / mean / LCL) ----
            if mean_v is not None and ucl is not None and lcl is not None:
                xmax = max(xs) + 0.6
                for value, lbl, color in [
                    (ucl, f"UCL  {ucl:.2f}", "#dc2626"),
                    (mean_v, f"x̄  {mean_v:.2f}", "#0ea5e9"),
                    (lcl, f"LCL  {lcl:.2f}", "#dc2626"),
                ]:
                    ax.text(
                        xmax, value, lbl, fontsize=10, fontweight="bold",
                        color=color, va="center", ha="left",
                        bbox=dict(
                            boxstyle="round,pad=0.3",
                            facecolor="white", edgecolor=color, linewidth=1,
                        ),
                    )

            ax.set_ylabel(ylabel, color="#1e293b", fontsize=12, fontweight="bold")
            ax.grid(True, which="major", color="#e2e8f0", linewidth=0.7, alpha=0.9)
            ax.set_axisbelow(True)
            ax.set_facecolor("#ffffff")
            for spine in ax.spines.values():
                spine.set_color("#cbd5e1")
            ax.tick_params(colors="#334155", labelsize=11, length=0)

            # Pad x-range so the right-edge labels fit.
            ax.set_xlim(-0.5, max(xs) + 3.5)
            # Pad y-range slightly so annotations don't clip.
            if ys:
                ymin, ymax = min(ys), max(ys)
                if ucl is not None:
                    ymax = max(ymax, ucl)
                if lcl is not None:
                    ymin = min(ymin, lcl)
                pad_y = max(0.5, (ymax - ymin) * 0.18)
                ax.set_ylim(ymin - pad_y, ymax + pad_y)

        _plot_series(
            ax_ball, ball_pool,
            f"Ball d  avg  ({unit_label})",
            "#4f46e5", "#c7d2fe",
        )
        _plot_series(
            ax_gap, gap_pool,
            f"GAP min  avg  ({unit_label})",
            "#16a34a", "#bbf7d0",
        )

        ax_gap.set_xlabel(
            "LOT  (chronological)", color="#1e293b",
            fontsize=12, fontweight="bold", labelpad=8,
        )

        # X-axis labels — show key LOT IDs with rotation.
        max_show = 10
        if len(ordered_lots) > max_show:
            step = max(1, len(ordered_lots) // max_show)
            ticks = list(range(0, len(ordered_lots), step))
            if (len(ordered_lots) - 1) not in ticks:
                ticks.append(len(ordered_lots) - 1)
        else:
            ticks = list(range(len(ordered_lots)))
        labels = [ordered_lots[i][-10:] for i in ticks]
        ax_ball.set_xticks(ticks)
        ax_ball.set_xticklabels([])
        ax_gap.set_xticks(ticks)
        ax_gap.set_xticklabels(labels, rotation=22, ha="right", fontsize=10)

        # Highlight the current LOT's tick label in green.
        for tick_label, idx in zip(ax_gap.get_xticklabels(), ticks):
            if idx == cur_idx:
                tick_label.set_color("#16a34a")
                tick_label.set_fontweight("bold")

        fig.subplots_adjust(
            left=0.085, right=0.92, top=0.94, bottom=0.16, hspace=0.28,
        )
        return FigureCanvas(fig)

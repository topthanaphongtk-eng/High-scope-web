"""Build an overlay that shows, for each pad:
    red dashed   = current Hough circle (what software draws)
    yellow solid = actual dark-blob contour (polygon traced from gradient/Otsu)
    cyan         = convex hull of the dark blob

Helps decide whether to switch ball detection from "circle" to "polygon".

Usage:
    python -m tools.compare_circle_vs_polygon  <focus_pad.tif>  <focus_ball.tif>
    python -m tools.compare_circle_vs_polygon                   # uses 4 pad 2/1.tif
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from app.services.ball_measure import (
    detect_pads_multi, focus_stack, load_as_bgr, pixel_size_um_from_ome,
)
from app.services.omexml import parse_tiff


def trace_dark_blob(gray_full: np.ndarray, pad) -> np.ndarray | None:
    """Return the largest dark contour inside the pad polygon, in fused
    coords. None if no plausible blob."""
    px, py, pw, ph = pad.x_px, pad.y_px, pad.width_px, pad.height_px
    inset = max(6, int(min(pw, ph) * 0.06))
    rx0 = max(0, px + inset); ry0 = max(0, py + inset)
    rx1 = min(gray_full.shape[1], px + pw - inset)
    ry1 = min(gray_full.shape[0], py + ph - inset)
    roi = gray_full[ry0:ry1, rx0:rx1]
    rh, rw = roi.shape

    inverted = cv2.bitwise_not(roi)
    blurred = cv2.GaussianBlur(inverted, (5, 5), 0)
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    k_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_small)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    pad_poly = np.array(pad.corners_px, dtype=np.int32)
    best = None
    best_area = 0.0
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < 200:
            continue
        M = cv2.moments(c)
        if abs(M["m00"]) < 1e-6:
            continue
        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]
        cx_fused = cx + rx0
        cy_fused = cy + ry0
        if cv2.pointPolygonTest(pad_poly, (float(cx_fused), float(cy_fused)), False) < 0:
            continue
        if area > best_area:
            best = c
            best_area = area
    if best is None:
        return None

    # Shift to fused coords
    shifted = best.copy()
    shifted[:, 0, 0] += rx0
    shifted[:, 0, 1] += ry0
    return shifted


def draw_dashed_circle(img: np.ndarray, center, r: int, color, thickness=2, dash=8):
    cx, cy = center
    n = max(40, int(2 * np.pi * r / dash))
    for i in range(n):
        if i % 2 == 0:
            t1 = 2 * np.pi * i / n
            t2 = 2 * np.pi * (i + 1) / n
            p1 = (int(cx + r * np.cos(t1)), int(cy + r * np.sin(t1)))
            p2 = (int(cx + r * np.cos(t2)), int(cy + r * np.sin(t2)))
            cv2.line(img, p1, p2, color, thickness, cv2.LINE_AA)


def main() -> int:
    if len(sys.argv) >= 3:
        a = Path(sys.argv[1]); b = Path(sys.argv[2])
    else:
        a = Path("D:/python/High scope machine/Picture/4 pad 2.tif")
        b = Path("D:/python/High scope machine/Picture/4 pad1.tif")
    if not (a.exists() and b.exists()):
        print(f"Missing: {a} or {b}")
        return 1
    out_dir = Path("D:/python/High scope machine/logs/poly_compare")
    out_dir.mkdir(parents=True, exist_ok=True)

    ome = parse_tiff(a)
    px_um = pixel_size_um_from_ome(ome.physical_size_x, ome.physical_size_unit)
    img_a = load_as_bgr(a)
    img_b = load_as_bgr(b)
    fused = focus_stack(img_a, img_b)
    pads = detect_pads_multi(img_a, img_b, pixel_size_um=px_um, debug_dump=False)
    print(f"Detected {len(pads)} pad(s)")

    overlay = fused.copy()
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)
    for i, p in enumerate(pads, 1):
        # Pad outline (green)
        if p.corners_px and len(p.corners_px) == 4:
            pts = np.array(p.corners_px, dtype=np.int32)
            cv2.polylines(overlay, [pts], True, (0, 255, 0), 2)

        # Current Hough circle (red dashed) — what the software draws today
        if p.ball is not None:
            draw_dashed_circle(
                overlay,
                (p.ball.center_x_px, p.ball.center_y_px),
                int(round(p.ball.radius_px)),
                (40, 40, 255), 2, dash=10,
            )
            cv2.drawMarker(
                overlay,
                (p.ball.center_x_px, p.ball.center_y_px),
                (40, 40, 255), cv2.MARKER_CROSS, 14, 2,
            )

        # Actual dark-blob polygon (yellow solid)
        contour = trace_dark_blob(gray_b, p)
        if contour is not None:
            cv2.polylines(overlay, [contour], True, (0, 220, 220), 2, cv2.LINE_AA)

            # Convex hull (cyan thin)
            hull = cv2.convexHull(contour)
            cv2.polylines(overlay, [hull], True, (255, 200, 0), 1, cv2.LINE_AA)

            # Compare areas
            poly_area = float(cv2.contourArea(contour))
            hull_area = float(cv2.contourArea(hull))
            circle_area = float(np.pi * p.ball.radius_px ** 2) if p.ball else 0
            poly_d_um = 2.0 * np.sqrt(poly_area / np.pi) * px_um
            print(
                f"#{i}  pad {p.width_um:.1f}x{p.height_um:.1f}um  "
                f"circle d={p.ball.diameter_um if p.ball else 0:.1f}um (area {circle_area:.0f}px)  "
                f"polygon area={poly_area:.0f}px (eq d={poly_d_um:.1f}um)  "
                f"hull area={hull_area:.0f}px  "
                f"poly:hull={poly_area/max(1,hull_area):.2%}  "
                f"poly:circle={poly_area/max(1,circle_area):.2%}"
            )

        # Label
        x = p.x_px; y = p.y_px
        cv2.putText(overlay, f"#{i}", (x + 6, y + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)

    # Legend
    cv2.rectangle(overlay, (10, 10), (430, 100), (0, 0, 0), -1)
    cv2.putText(overlay, "RED dashed  = Hough circle (current detector)",
                (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 40, 255), 1, cv2.LINE_AA)
    cv2.putText(overlay, "YELLOW solid = actual dark blob (polygon)",
                (18, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 220), 1, cv2.LINE_AA)
    cv2.putText(overlay, "CYAN thin   = convex hull of polygon",
                (18, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1, cv2.LINE_AA)

    out_path = out_dir / "compare.png"
    cv2.imwrite(str(out_path), overlay)
    print(f"\nSaved {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

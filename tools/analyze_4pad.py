"""Diagnostic for the 4-pad ball-pick problem.

Loads `4 pad1.tif` + `4 pad 2.tif`, runs the multi-pad pipeline, and dumps
per-pad ball-mask diagnostics so we can see WHY a wrong dark blob is picked
on some pads. Output goes to logs/4pad_diag/.

Usage:  python -m tools.analyze_4pad
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from app.services.ball_measure import (
    detect_pads_multi,
    draw_multi_pad_overlay,
    focus_stack,
    load_as_bgr,
    pixel_size_um_from_ome,
)
from app.services.omexml import parse_tiff


def diag_one_pad(
    fused_for_ball: np.ndarray,
    pad,
    out_dir: Path,
    pad_idx: int,
) -> None:
    """Replicate detect_ball_in_pad() up to the contour stage and dump every
    candidate's geometry so we can see what's happening."""
    gray = cv2.cvtColor(fused_for_ball, cv2.COLOR_BGR2GRAY)
    px, py, pw, ph = pad.x_px, pad.y_px, pad.width_px, pad.height_px
    inset = max(6, int(min(pw, ph) * 0.06))
    rx0 = max(0, px + inset)
    ry0 = max(0, py + inset)
    rx1 = min(gray.shape[1], px + pw - inset)
    ry1 = min(gray.shape[0], py + ph - inset)

    roi = gray[ry0:ry1, rx0:rx1]
    rh, rw = roi.shape

    inverted = cv2.bitwise_not(roi)
    blurred = cv2.GaussianBlur(inverted, (5, 5), 0)
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    k_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_small)
    ext, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if ext:
        filled = np.zeros_like(mask)
        cv2.drawContours(filled, ext, -1, 255, thickness=cv2.FILLED)
        mask = filled

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Save the inverted ROI + mask for inspection
    cv2.imwrite(str(out_dir / f"pad{pad_idx}_roi_gray.png"), roi)
    cv2.imwrite(str(out_dir / f"pad{pad_idx}_inverted.png"), inverted)
    cv2.imwrite(str(out_dir / f"pad{pad_idx}_ball_mask.png"), mask)

    # Annotate every contour with its score components
    annotated = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
    pad_area_px = pad.pad_w_px * pad.pad_h_px
    cx_roi = rw / 2.0
    cy_roi = rh / 2.0
    roi_diag = float(np.hypot(rw, rh))
    pad_poly = np.array(pad.corners_px, dtype=np.int32)

    print(f"\n--- Pad #{pad_idx + 1}  bbox=({px},{py}, {pw}x{ph})  rotrect={pad.pad_w_px:.0f}x{pad.pad_h_px:.0f} ---")
    print(f"ROI {rw}x{rh} @ ({rx0}, {ry0})   contours={len(contours)}")

    for ci, c in enumerate(contours):
        area = float(cv2.contourArea(c))
        if area < 100.0:
            print(f"  c{ci}: area={area:.0f} px  → reject area<100")
            continue
        frac_of_pad = area / max(1.0, pad_area_px)
        perim = float(cv2.arcLength(c, True))
        if perim <= 0:
            continue
        circ = min(1.0, 4 * np.pi * area / (perim * perim))

        M = cv2.moments(c)
        if abs(M["m00"]) < 1e-6:
            continue
        cx_cnt = float(M["m10"] / M["m00"])
        cy_cnt = float(M["m01"] / M["m00"])

        # Inscribed-circle radius
        single_mask = np.zeros_like(mask)
        cv2.drawContours(single_mask, [c], -1, 255, thickness=cv2.FILLED)
        dt_local = cv2.distanceTransform(single_mask, cv2.DIST_L2, 5)
        _, r_inscribed_val, _, _ = cv2.minMaxLoc(dt_local)
        r_inscribed = float(r_inscribed_val)

        _, r_enc = cv2.minEnclosingCircle(c)
        fill = area / max(1.0, np.pi * r_enc * r_enc)
        r_area = float(np.sqrt(area / np.pi))

        # Centroid in fused coords
        cx_fused = cx_cnt + rx0
        cy_fused = cy_cnt + ry0
        in_pad = cv2.pointPolygonTest(
            pad_poly, (float(cx_fused), float(cy_fused)), False,
        ) >= 0

        dist_norm = float(np.hypot(cx_cnt - cx_roi, cy_cnt - cy_roi)) / max(1.0, roi_diag)
        score = circ * fill * (1.0 - min(1.0, dist_norm * 2.0))

        print(
            f"  c{ci}: area={area:6.0f} ({frac_of_pad:.2%} of pad)  "
            f"circ={circ:.2f}  fill={fill:.2f}  "
            f"r_inscribed={r_inscribed:.1f}  r_enclose={r_enc:.1f}  r_area={r_area:.1f}  "
            f"in_pad={in_pad}  score={score:.3f}"
        )

        # Draw on annotated ROI
        color = (0, 255, 0) if in_pad else (0, 100, 255)
        cv2.drawContours(annotated, [c], -1, color, 1)
        cv2.circle(annotated, (int(cx_cnt), int(cy_cnt)), int(round(r_inscribed)),
                   (255, 200, 0), 1, cv2.LINE_AA)
        cv2.putText(annotated, f"c{ci}", (int(cx_cnt) + 4, int(cy_cnt) - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)

    cv2.imwrite(str(out_dir / f"pad{pad_idx}_annotated.png"), annotated)


def main() -> int:
    a = Path("D:/python/High scope machine/Picture/4 pad 2.tif")
    b = Path("D:/python/High scope machine/Picture/4 pad1.tif")
    if not (a.exists() and b.exists()):
        print(f"Missing files. Need {a} AND {b}.")
        return 1

    out_dir = Path("D:/python/High scope machine/logs/4pad_diag")
    out_dir.mkdir(parents=True, exist_ok=True)

    ome = parse_tiff(a)
    px_um = pixel_size_um_from_ome(ome.physical_size_x, ome.physical_size_unit)
    print(f"pixel size : {px_um:.4f} µm/px")

    img_a = load_as_bgr(a)
    img_b = load_as_bgr(b)
    fused = focus_stack(img_a, img_b)
    cv2.imwrite(str(out_dir / "fused.png"), fused)

    # Treat img_a as Focus-Pad and img_b as Focus-Ball (matches GUI flow)
    pads = detect_pads_multi(
        img_a, img_b,
        pixel_size_um=px_um,
        source_a_name=a.name,
        source_b_name=b.name,
        debug_dump=False,
    )
    print(f"\nDetected {len(pads)} pad(s)")
    for i, p in enumerate(pads, 1):
        print(f"#{i}  pad {p.width_um:.1f}x{p.height_um:.1f} um  fill={p.fill_ratio:.3f}  conf={p.confidence}")
        if p.ball is not None:
            print(f"     ball d={p.ball.diameter_um:.1f} um  circ={p.ball.circularity:.2f}  fill={p.ball.fill_ratio:.2f}")
        else:
            print("     ball: NOT detected")

    overlay = draw_multi_pad_overlay(fused, pads, unit="um")
    cv2.imwrite(str(out_dir / "fused_overlay.png"), overlay)

    # Per-pad ball-mask diagnostics
    for i, p in enumerate(pads):
        diag_one_pad(img_b, p, out_dir, i)

    print(f"\nDiagnostics written to {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

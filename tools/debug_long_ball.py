"""Inspect ball detection on the merged long-pad."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from app.services.ball_measure import (
    detect_pads_multi, load_as_bgr, pixel_size_um_from_ome,
)
from app.services.omexml import parse_tiff


def main() -> int:
    a = Path("D:/python/High scope machine/Picture/long pad.tif")
    b = Path("D:/python/High scope machine/Picture/long pad ball.tif")
    out_dir = Path("D:/python/High scope machine/logs/long_ball_debug")
    out_dir.mkdir(parents=True, exist_ok=True)

    ome = parse_tiff(a)
    px_um = pixel_size_um_from_ome(ome.physical_size_x, ome.physical_size_unit)
    img_a = load_as_bgr(a)
    img_b = load_as_bgr(b)
    pads = detect_pads_multi(img_a, img_b, pixel_size_um=px_um, debug_dump=False)

    for i, p in enumerate(pads, 1):
        print(f"#{i}  pad rotrect={p.pad_w_px:.0f} x {p.pad_h_px:.0f} px  "
              f"= {p.width_um:.1f} x {p.height_um:.1f} um, fill={p.fill_ratio:.2f}")
        if p.ball is not None:
            print(f"     ball center=({p.ball.center_x_px}, {p.ball.center_y_px}) "
                  f"r={p.ball.radius_px:.1f}px d={p.ball.diameter_um:.1f}um "
                  f"method={p.ball.method}")
        else:
            print(f"     ball: NOT DETECTED")

    # Now run Hough manually with various params on the ball ROI of pad #1
    if not pads:
        return 1
    pad = pads[0]
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)
    px, py, pw, ph = pad.x_px, pad.y_px, pad.width_px, pad.height_px
    inset = max(6, int(min(pw, ph) * 0.06))
    rx0 = max(0, px + inset); ry0 = max(0, py + inset)
    rx1 = min(gray_b.shape[1], px + pw - inset); ry1 = min(gray_b.shape[0], py + ph - inset)
    roi = gray_b[ry0:ry1, rx0:rx1]
    rh, rw = roi.shape
    print(f"\nROI {rw} x {rh}  pad rotrect_min={min(pad.pad_w_px, pad.pad_h_px):.0f}")

    blurred = cv2.medianBlur(roi, 5)
    blurred = cv2.GaussianBlur(blurred, (5, 5), 1.5)
    pad_min = float(min(pad.pad_w_px, pad.pad_h_px))
    min_r = max(8, int(pad_min * 0.15))
    max_r = max(min_r + 5, int(pad_min * 0.48))
    print(f"Hough r range = [{min_r}, {max_r}] px")

    annotated = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
    for p1, p2 in [(80, 30), (60, 25), (50, 18), (40, 15)]:
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT, dp=1.2,
            minDist=int(pad_min * 0.5),
            param1=p1, param2=p2,
            minRadius=min_r, maxRadius=max_r,
        )
        if circles is None:
            print(f"  p1={p1} p2={p2}: nil")
            continue
        for cx, cy, r in circles[0]:
            print(f"  p1={p1} p2={p2}: ({cx:.0f},{cy:.0f}) r={r:.0f} "
                  f"({2*r*px_um:.1f}um)")
            cv2.circle(annotated, (int(cx), int(cy)), int(r), (0, 255, 255), 1)

    cv2.imwrite(str(out_dir / "ball_roi_annotated.png"), annotated)
    cv2.imwrite(str(out_dir / "ball_roi_gray.png"), roi)
    print(f"\nSaved to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

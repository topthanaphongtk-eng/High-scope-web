"""Inspect Hough/refine output for pad #1 (the one giving d=29.6 um)."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from app.services.ball_measure import (
    detect_pads_multi, load_as_bgr, pixel_size_um_from_ome,
    _refine_ball_radius_radial,
)
from app.services.omexml import parse_tiff


def main() -> int:
    a = Path("D:/python/High scope machine/Picture/4 pad 2.tif")  # Focus-Pad
    b = Path("D:/python/High scope machine/Picture/4 pad1.tif")   # Focus-Ball
    out_dir = Path("D:/python/High scope machine/logs/pad1_debug")
    out_dir.mkdir(parents=True, exist_ok=True)

    ome = parse_tiff(a)
    px_um = pixel_size_um_from_ome(ome.physical_size_x, ome.physical_size_unit)
    img_a = load_as_bgr(a)
    img_b = load_as_bgr(b)
    pads = detect_pads_multi(img_a, img_b, pixel_size_um=px_um, debug_dump=False)
    if not pads:
        print("no pads")
        return 1

    pad = pads[0]  # pad #1
    print(f"Pad #1 rotrect = {pad.pad_w_px:.0f} x {pad.pad_h_px:.0f} px")
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)

    px, py, pw, ph = pad.x_px, pad.y_px, pad.width_px, pad.height_px
    inset = max(6, int(min(pw, ph) * 0.06))
    rx0 = max(0, px + inset); ry0 = max(0, py + inset)
    rx1 = min(gray_b.shape[1], px + pw - inset); ry1 = min(gray_b.shape[0], py + ph - inset)
    roi = gray_b[ry0:ry1, rx0:rx1]
    rh, rw = roi.shape
    print(f"ROI {rw}x{rh}")

    blurred = cv2.medianBlur(roi, 5)
    blurred = cv2.GaussianBlur(blurred, (5, 5), 1.5)
    pad_min = float(min(pad.pad_w_px, pad.pad_h_px))
    min_r = max(8, int(pad_min * 0.15))
    max_r = max(min_r + 5, int(pad_min * 0.48))

    print(f"\nHough param sweep (r in [{min_r}, {max_r}]):")
    for p1, p2 in [(60, 25), (50, 18), (40, 15), (80, 30), (60, 12)]:
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=int(pad_min * 0.5),
            param1=p1, param2=p2, minRadius=min_r, maxRadius=max_r,
        )
        if circles is None:
            print(f"  p1={p1} p2={p2}: nil")
            continue
        for cx, cy, r in circles[0]:
            inner = roi[max(0, int(cy)-int(r*0.7)):int(cy)+int(r*0.7),
                        max(0, int(cx)-int(r*0.7)):int(cx)+int(r*0.7)]
            print(f"  p1={p1} p2={p2}: ({cx:.0f},{cy:.0f}) r={r:.0f} ({2*r*px_um:.1f}um)")

    # Save the radial profile from the chosen Hough circle's centre
    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=int(pad_min * 0.5),
        param1=60, param2=25, minRadius=min_r, maxRadius=max_r,
    )
    if circles is None:
        return 0
    cx, cy, r_h = circles[0][0]
    print(f"\nUsing Hough circle at ({cx:.0f},{cy:.0f}) r={r_h:.0f}")

    # Build radial profile
    yy, xx = np.indices(roi.shape, dtype=np.float32)
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2).astype(np.int32)
    max_possible_r = int(min(cx, rw - cx, cy, rh - cy)) - 2
    cap_r = min(max_possible_r, int(r_h * 2.5))
    valid = dist.ravel() <= cap_r
    counts = np.bincount(dist.ravel()[valid], minlength=cap_r + 1)[: cap_r + 1]
    sums = np.bincount(dist.ravel()[valid],
                       weights=roi.astype(np.float64).ravel()[valid],
                       minlength=cap_r + 1)[: cap_r + 1]
    profile = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)
    profile_s = np.convolve(profile, np.ones(7) / 7, mode="same")
    deriv = np.gradient(profile_s)

    print("\nRadial profile (smoothed) and derivative:")
    print(f"{'r':>4} {'I':>6} {'dI/dr':>8}")
    for r_i in range(0, len(profile_s), 4):
        print(f"{r_i:>4} {profile_s[r_i]:>6.1f} {deriv[r_i]:>+8.2f}")

    r_refined = _refine_ball_radius_radial(roi, float(cx), float(cy), float(r_h),
                                            search_window_frac=0.25)
    print(f"\nHough r = {r_h:.1f}  →  refined r = {r_refined:.1f}  (d = {2*r_refined*px_um:.1f} um)")

    # Visual: draw both Hough and refined on ROI
    out = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
    cv2.circle(out, (int(cx), int(cy)), int(round(r_h)), (0, 165, 255), 2)
    cv2.circle(out, (int(cx), int(cy)), int(round(r_refined)), (0, 255, 0), 2)
    cv2.putText(out, "orange=Hough  green=refined", (8, rh - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    cv2.imwrite(str(out_dir / "pad1_compare.png"), out)
    print(f"\nSaved {out_dir / 'pad1_compare.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

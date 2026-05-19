"""Test if HoughCircles can find the actual ball reliably on the 4-pad image
where Otsu mask fails (pad #2 surface is too dark, mask spans whole ROI)."""

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
    load_as_bgr,
    pixel_size_um_from_ome,
)
from app.services.omexml import parse_tiff


def hough_for_pad(gray_full: np.ndarray, pad, out_dir: Path, idx: int) -> None:
    px, py, pw, ph = pad.x_px, pad.y_px, pad.width_px, pad.height_px
    inset = max(6, int(min(pw, ph) * 0.06))
    rx0 = max(0, px + inset)
    ry0 = max(0, py + inset)
    rx1 = min(gray_full.shape[1], px + pw - inset)
    ry1 = min(gray_full.shape[0], py + ph - inset)
    roi = gray_full[ry0:ry1, rx0:rx1]
    rh, rw = roi.shape

    blurred = cv2.medianBlur(roi, 5)
    blurred = cv2.GaussianBlur(blurred, (5, 5), 1.5)

    pad_min = float(min(pad.pad_w_px, pad.pad_h_px))
    min_r = max(8, int(pad_min * 0.15))
    max_r = max(min_r + 5, int(pad_min * 0.45))
    min_dist = max(20, int(pad_min * 0.5))

    print(f"\n=== Pad #{idx + 1}  ROI {rw}x{rh}  pad_min={pad_min:.0f}px  "
          f"hough r∈[{min_r}, {max_r}]px ===")

    for p1, p2 in [(80, 30), (60, 25), (100, 15), (50, 18)]:
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT,
            dp=1.2, minDist=min_dist,
            param1=p1, param2=p2,
            minRadius=min_r, maxRadius=max_r,
        )
        if circles is None:
            print(f"  param1={p1} param2={p2}: no circles")
            continue
        circles = circles[0]  # (N, 3)
        # Filter by intensity inside vs outside (inside should be darker)
        annotated = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
        kept = []
        for cx, cy, r in circles:
            mask = np.zeros_like(roi)
            cv2.circle(mask, (int(cx), int(cy)), int(r * 0.7), 255, -1)
            inner_mean = float(roi[mask > 0].mean()) if (mask > 0).any() else 0
            outer_mask = np.zeros_like(roi)
            cv2.circle(outer_mask, (int(cx), int(cy)), int(r * 1.4), 255, -1)
            cv2.circle(outer_mask, (int(cx), int(cy)), int(r * 1.05), 0, -1)
            outer_mean = float(roi[outer_mask > 0].mean()) if (outer_mask > 0).any() else 0
            contrast = outer_mean - inner_mean
            kept.append((cx, cy, r, inner_mean, outer_mean, contrast))
            color = (0, 255, 0) if contrast > 20 else (0, 100, 255)
            cv2.circle(annotated, (int(cx), int(cy)), int(r), color, 2, cv2.LINE_AA)
            cv2.drawMarker(annotated, (int(cx), int(cy)), color,
                           cv2.MARKER_CROSS, 8, 1)
        kept.sort(key=lambda t: t[5], reverse=True)
        print(f"  param1={p1} param2={p2}: {len(circles)} circle(s)")
        for cx, cy, r, im, om, cn in kept[:5]:
            print(f"    @({cx:.0f},{cy:.0f}) r={r:.0f}  "
                  f"inner_mean={im:.0f} outer_mean={om:.0f}  contrast={cn:+.0f}")
        cv2.imwrite(
            str(out_dir / f"hough_pad{idx}_p1{p1}_p2{p2}.png"), annotated,
        )


def main() -> int:
    a = Path("D:/python/High scope machine/Picture/4 pad1.tif")
    b = Path("D:/python/High scope machine/Picture/4 pad 2.tif")
    if not (a.exists() and b.exists()):
        print(f"Missing: {a} or {b}")
        return 1
    out_dir = Path("D:/python/High scope machine/logs/hough_test")
    out_dir.mkdir(parents=True, exist_ok=True)

    ome = parse_tiff(a)
    px_um = pixel_size_um_from_ome(ome.physical_size_x, ome.physical_size_unit)
    img_a = load_as_bgr(a)
    img_b = load_as_bgr(b)

    pads = detect_pads_multi(
        img_a, img_b, pixel_size_um=px_um,
        source_a_name=a.name, source_b_name=b.name,
        debug_dump=False,
    )
    print(f"Detected {len(pads)} pad(s)")

    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)
    for i, p in enumerate(pads):
        hough_for_pad(gray_b, p, out_dir, i)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

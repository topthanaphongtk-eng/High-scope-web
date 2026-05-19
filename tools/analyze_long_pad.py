"""Inspect why a long rectangular pad is being detected as two halves.

Focus-Pad: D:/python/High scope machine/Picture/long pad.tif
Focus-Ball: D:/python/High scope machine/Picture/long pad ball.tif
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from app.services.ball_measure import (
    _TIERS, _pad_mask, detect_pads_multi, focus_stack,
    load_as_bgr, pixel_size_um_from_ome,
)
from app.services.omexml import parse_tiff


def main() -> int:
    a = Path("D:/python/High scope machine/Picture/long pad.tif")
    b = Path("D:/python/High scope machine/Picture/long pad ball.tif")
    out_dir = Path("D:/python/High scope machine/logs/long_pad_diag")
    out_dir.mkdir(parents=True, exist_ok=True)

    if not (a.exists() and b.exists()):
        print(f"Missing: {a} / {b}")
        return 1

    ome = parse_tiff(a)
    px_um = pixel_size_um_from_ome(ome.physical_size_x, ome.physical_size_unit)
    print(f"pixel size = {px_um:.4f} um/px")

    img_a = load_as_bgr(a)
    img_b = load_as_bgr(b)
    fused = focus_stack(img_a, img_b)
    cv2.imwrite(str(out_dir / "fused.png"), fused)
    cv2.imwrite(str(out_dir / "focus_pad.png"), img_a)
    cv2.imwrite(str(out_dir / "focus_ball.png"), img_b)

    # Run the current detection
    pads = detect_pads_multi(img_a, img_b, pixel_size_um=px_um, debug_dump=False)
    print(f"\nCurrent detector: {len(pads)} pads")
    for i, p in enumerate(pads, 1):
        print(f"  #{i} pad {p.width_um:.1f} x {p.height_um:.1f} um  "
              f"aspect={p.aspect_ratio:.2f} fill={p.fill_ratio:.3f} "
              f"angle={p.angle_deg:.1f} bbox=({p.x_px},{p.y_px}, {p.width_px}x{p.height_px})")

    # Dump the mask for each tier so we can see whether the pad mask is
    # broken (long pad split into two pieces).
    gray = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    for tier in _TIERS:
        m = _pad_mask(gray, tier=tier)
        cv2.imwrite(str(out_dir / f"mask_{tier.name}.png"), m)
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # Annotate every contour with its bbox + dimensions
        ann = img_a.copy()
        for c in contours:
            area = cv2.contourArea(c)
            if area < 200:
                continue
            x, y, w, h = cv2.boundingRect(c)
            rect = cv2.minAreaRect(c)
            (rcx, rcy), (rw, rh), _ang = rect
            aspect = max(rw, rh) / max(1.0, min(rw, rh))
            cv2.rectangle(ann, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(
                ann,
                f"{int(min(rw,rh))}x{int(max(rw,rh))} a={aspect:.1f}",
                (x, max(20, y - 6)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA,
            )
        cv2.imwrite(str(out_dir / f"contours_{tier.name}.png"), ann)
        print(f"  tier {tier.name}: {len(contours)} contour(s)")

    # Also raw threshold without the morphological close step — to see whether
    # the pad mask is naturally connected or broken.
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    p85 = float(np.percentile(blurred, 85))
    _, raw_mask = cv2.threshold(blurred, p85, 255, cv2.THRESH_BINARY)
    cv2.imwrite(str(out_dir / "raw_mask_p85_no_morph.png"), raw_mask)

    print(f"\nDiagnostics in {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

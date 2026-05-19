"""Test ball detection on Image_22389/22390. Expected ~1.6 mil = 40.6 um."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from app.services.ball_measure import (
    detect_pads_multi, draw_multi_pad_overlay, focus_stack,
    load_as_bgr, pixel_size_um_from_ome,
)
from app.services.omexml import parse_tiff


def main() -> int:
    pic_dir = Path("D:/python/High scope machine/Picture")
    a = pic_dir / "Image_22389.tif"
    b = pic_dir / "Image_22390.tif"
    out_dir = Path("D:/python/High scope machine/logs/test_22389")
    out_dir.mkdir(parents=True, exist_ok=True)

    if not (a.exists() and b.exists()):
        print(f"Missing: {a} or {b}")
        return 1

    ome = parse_tiff(a)
    px_um = pixel_size_um_from_ome(ome.physical_size_x, ome.physical_size_unit)
    print(f"pixel size = {px_um:.4f} um/px")

    # Try both orderings to see which is Focus-Pad / Focus-Ball.
    for label, focus_pad, focus_ball in [
        ("A=pad, B=ball", a, b),
        ("B=pad, A=ball", b, a),
    ]:
        print(f"\n--- {label} ---")
        img_pad = load_as_bgr(focus_pad)
        img_ball = load_as_bgr(focus_ball)
        pads = detect_pads_multi(img_pad, img_ball, pixel_size_um=px_um, debug_dump=False)
        print(f"Detected {len(pads)} pad(s)")
        for i, p in enumerate(pads, 1):
            print(f"  #{i} pad {p.width_um:.2f} x {p.height_um:.2f} um  fill={p.fill_ratio:.2f}")
            if p.ball is not None:
                d_um = p.ball.diameter_um
                d_mil = d_um / 25.4
                print(
                    f"     ball d={d_um:.2f} um = {d_mil:.3f} mil  "
                    f"(expected ~1.6 mil = 40.6 um)  delta={d_um - 40.6:+.2f} um  "
                    f"r_px={p.ball.radius_px:.1f} method={p.ball.method}"
                )
            else:
                print("     ball: NOT DETECTED")

        if pads:
            fused = focus_stack(img_pad, img_ball)
            overlay = draw_multi_pad_overlay(fused, pads, unit="um")
            tag = label.replace(",", "").replace("=", "").replace(" ", "_")
            cv2.imwrite(str(out_dir / f"overlay_{tag}.png"), overlay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Smoke test the pad detection pipeline against the sample TIFFs.

Run:  python -m tests.test_ball_measure
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from app.services.ball_measure import debug_pad_overlay, draw_pad_overlay, measure_pair  # noqa: E402
from app.services.omexml import parse_tiff  # noqa: E402


def main() -> int:
    a = Path("D:/python/High scope machine/Picture/Ball1.tif")
    b = Path("D:/python/High scope machine/Picture/Ball2.tif")
    if not (a.exists() and b.exists()):
        print(f"Missing samples: {a} / {b}")
        return 1

    ome = parse_tiff(a)
    from app.services.ball_measure import pixel_size_um_from_ome
    px_um = pixel_size_um_from_ome(ome.physical_size_x, ome.physical_size_unit)
    print(f"pixel size : {px_um:.4f} µm/px")

    fused, img_a, img_b, m = measure_pair(a, b, pixel_size_um=px_um)
    print()
    print("--- PadMeasurement ---")
    for k, v in m.to_dict().items():
        if isinstance(v, float):
            print(f"  {k:22s} {v:.4f}")
        else:
            print(f"  {k:22s} {v}")

    out = Path("D:/python/High scope machine/logs")
    out.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out / "pad_overlay.png"), draw_pad_overlay(fused, m))
    cv2.imwrite(str(out / "pad_debug.png"), debug_pad_overlay(fused))
    print()
    print(f"Wrote {out / 'pad_overlay.png'} and pad_debug.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

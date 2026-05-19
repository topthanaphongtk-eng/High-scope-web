"""Quick manual test of OME-XML parsing against real Olympus TIFF samples.

Run:  python -m tests.test_omexml
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

# Force UTF-8 stdout on Windows for safe printing of Unicode (µm etc.)
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.omexml import parse_tiff  # noqa: E402


def main() -> int:
    samples = [
        Path("D:/python/High scope machine/Picture/Ball1.tif"),
        Path("D:/python/High scope machine/Picture/Ball2.tif"),
    ]
    for p in samples:
        if not p.exists():
            print(f"SKIP (missing): {p}")
            continue
        meta = parse_tiff(p)
        print(f"=== {p.name} ===")
        for field, value in meta.model_dump().items():
            print(f"  {field:35s} {value}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

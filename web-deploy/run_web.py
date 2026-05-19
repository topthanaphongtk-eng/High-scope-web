"""Launch the High Scope monitor web app.

Usage:
    python run_web.py                      # 0.0.0.0:8080
    python run_web.py --port 5000          # custom port
    MEASUREMENT_DB=/path/to/measurements.db python run_web.py
    SHARE_ROOT=//server/share python run_web.py
"""

from __future__ import annotations

import logging

from web.server import main


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    main()

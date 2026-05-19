"""Entry point: load config → init SOAP client → launch Qt GUI."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox

from app.config import Settings
from app.gui.main_window import MainWindow
from app.services.lot_client import LotClient, ServerUnreachable
from app.utils.app_icon import make_app_icon
from app.utils.logging import setup_logging

log = logging.getLogger(__name__)


def _resolve_settings_path(cli_path: str | None) -> Path:
    if cli_path:
        return Path(cli_path)
    here = Path(__file__).resolve().parent
    for candidate in [
        here / "config" / "settings.yaml",
        here / "config" / "settings.example.yaml",
    ]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No settings.yaml or settings.example.yaml found under config/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="path to settings yaml")
    args = parser.parse_args(argv)

    settings_path = _resolve_settings_path(args.config)
    settings = Settings.from_yaml(settings_path)
    setup_logging(settings.app.log_dir, settings.app.log_level)
    log.info("Loaded settings from %s", settings_path)

    app = QApplication(sys.argv)
    # App-wide window icon (taskbar / Alt-Tab / title bar). Multi-resolution.
    app.setWindowIcon(make_app_icon())

    # Windows-only: tell the shell this process belongs to its own app
    # group so the taskbar uses our icon (not the Python interpreter's).
    try:
        import ctypes  # type: ignore
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore
            "anthropic.highscope.capture.1"
        )
    except Exception:
        pass

    try:
        lot_client = LotClient(
            wsdl_url=settings.mes.wsdl_url,
            timeout=settings.mes.timeout_seconds,
            cache_dir=settings.mes.wsdl_cache_dir,
            verify_ssl=settings.mes.verify_ssl,
        )
    except ServerUnreachable as e:
        QMessageBox.critical(
            None, "Cannot start",
            f"Failed to load MES WSDL:\n\n{e}\n\nCheck network and settings.yaml.",
        )
        return 2

    window = MainWindow(
        settings=settings, lot_client=lot_client, settings_path=settings_path,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

"""hydrafers.gui.__main__ — PySide6 desktop GUI entry point (CONTRACT.md §6)."""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Create the QApplication, load the stylesheet, show the main window."""
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv if argv is None else [sys.argv[0], *(argv or [])])
    app.setApplicationName("HydraFERS")
    app.setOrganizationName("CAEN")

    qss_path = Path(__file__).parent / "style.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    from hydrafers.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

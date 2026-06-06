"""hydrafers.gui.__main__ — PySide6 desktop GUI entry point (CONTRACT.md §6)."""

from __future__ import annotations

import sys
from pathlib import Path


def load_stylesheet() -> str:
    """Read style.qss and resolve the ``__IMGS__`` token to the absolute imgs path.

    QSS ``url()`` references need a concrete path (relative ones resolve against
    the CWD, which is unreliable), so we inject the bundled imgs directory here.
    Paths use forward slashes — valid for Qt ``url()`` on every platform.
    """
    here = Path(__file__).parent
    qss_path = here / "style.qss"
    if not qss_path.exists():
        return ""
    imgs = (here / "imgs").as_posix()
    return qss_path.read_text(encoding="utf-8").replace("__IMGS__", imgs)


def main(argv: list[str] | None = None) -> int:
    """Create the QApplication, load the stylesheet, show the main window."""
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv if argv is None else [sys.argv[0], *(argv or [])])
    app.setApplicationName("HydraFERS")
    app.setOrganizationName("CAEN")

    qss = load_stylesheet()
    if qss:
        app.setStyleSheet(qss)

    from hydrafers.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

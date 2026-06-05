"""Sidebar -- the left navigation rail (CONTRACT.md section 6).

Layer: ``hydrafers.gui`` (PySide6). Reproduces the CAEN Web Interface sidebar
(screenshots_gui/WI_device_tree.png): a brand label at the top and a vertical
list of exclusive nav buttons that select the central
:class:`~PySide6.QtWidgets.QStackedWidget` page. Emits :attr:`page_selected`
with the integer page index; the active button is highlighted via the
``active`` dynamic property hooked in ``style.qss``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


class Sidebar(QFrame):
    """Vertical navigation rail emitting :attr:`page_selected` on click."""

    #: Emitted with the page index of the newly selected nav item.
    page_selected = Signal(int)

    def __init__(
        self,
        brand: str = "FERS",
        logo_path: str | Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")

        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Brand area: logo + text side by side
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(12, 12, 12, 8)
        brand_row.setSpacing(10)

        if logo_path is not None:
            px = QPixmap(str(logo_path))
            if not px.isNull():
                logo_lbl = QLabel()
                logo_lbl.setPixmap(
                    px.scaledToHeight(30, Qt.TransformationMode.SmoothTransformation)
                )
                logo_lbl.setFixedHeight(34)
                brand_row.addWidget(logo_lbl)

        brand_label = QLabel(brand)
        brand_label.setObjectName("SidebarBrand")
        brand_row.addWidget(brand_label)
        brand_row.addStretch(1)
        layout.addLayout(brand_row)
        layout.addSpacing(4)

        self._nav_layout = QVBoxLayout()
        self._nav_layout.setContentsMargins(0, 0, 0, 0)
        self._nav_layout.setSpacing(0)
        layout.addLayout(self._nav_layout)

        layout.addStretch(1)

        self._footer = QLabel("Nuclear Instruments - CAEN")
        self._footer.setObjectName("SidebarFooter")
        self._footer.setWordWrap(True)
        layout.addWidget(self._footer)

    # ----------------------------------------------------------------- API
    def add_page(self, label: str) -> int:
        """Add a nav item labelled *label*; returns its 0-based page index."""
        index = len(self._buttons)
        btn = QPushButton(label)
        btn.setProperty("nav", True)
        btn.setCheckable(True)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.clicked.connect(lambda _checked=False, i=index: self._on_clicked(i))
        self._group.addButton(btn, index)
        self._buttons.append(btn)
        self._nav_layout.addWidget(btn)
        if index == 0:
            self.set_active(0)
        return index

    def set_active(self, index: int) -> None:
        """Programmatically mark *index* as the active nav item."""
        if not (0 <= index < len(self._buttons)):
            return
        for i, btn in enumerate(self._buttons):
            active = i == index
            btn.setChecked(active)
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_footer(self, text: str) -> None:
        """Set the small footer text under the nav list."""
        self._footer.setText(text)

    # ----------------------------------------------------------- internals
    def _on_clicked(self, index: int) -> None:
        self.set_active(index)
        self.page_selected.emit(index)

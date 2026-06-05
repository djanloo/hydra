"""StatusTable -- a key/value status list inside a titled card (CONTRACT.md s.6).

Layer: ``hydrafers.gui`` (PySide6). Reproduces the "Link Status" / "General
Information" / "Temperature Monitoring" cards of the CAEN Web Interface
(screenshots_gui/): a left-aligned label column and a right-aligned value column,
where a value may be plain text, a coloured :class:`~hydrafers.gui.widgets.led.Led`,
or an orange status badge.

The widget is a dumb view: :meth:`set_value`, :meth:`set_led` and
:meth:`set_badge` are called by :class:`hydrafers.gui.main_window.MainWindow`
from the Qt loop. It owns no engine reference.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from hydrafers.gui.widgets.led import Led


class StatusBadge(QLabel):
    """A pill-shaped status badge (e.g. orange ``Ready``, green ``Running``)."""

    def __init__(self, text: str = "", state: str = "disabled", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("StatusBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_state(state)

    def set_state(self, state: str, text: str | None = None) -> None:
        """Set the badge ``state`` (drives the QSS colour) and optional ``text``."""
        self.setProperty("state", state)
        if text is not None:
            self.setText(text)
        # Re-polish so the dynamic property selector in the QSS re-applies.
        self.style().unpolish(self)
        self.style().polish(self)


class StatusTable(QFrame):
    """A titled card holding a list of ``label : value`` status rows.

    Rows are added once at build time via :meth:`add_row` (text), :meth:`add_led`
    (LED indicator) or :meth:`add_badge` (status pill). Each row is keyed by a
    string so the values can be updated later by key.
    """

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        self._values: dict[str, QLabel] = {}
        self._leds: dict[str, Led] = {}
        self._badges: dict[str, StatusBadge] = {}
        self._row = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        if title:
            title_label = QLabel(title)
            title_label.setObjectName("CardTitle")
            outer.addWidget(title_label)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(14, 4, 14, 14)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(2)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        outer.addLayout(self._grid)
        outer.addStretch(1)

    # ----------------------------------------------------------- row builders
    def add_row(self, key: str, label: str, value: str = "-") -> QLabel:
        """Add a text value row; returns the value ``QLabel`` for direct styling."""
        lbl = QLabel(label)
        lbl.setObjectName("FieldLabel")
        val = QLabel(value)
        val.setObjectName("FieldValue")
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._grid.addWidget(lbl, self._row, 0)
        self._grid.addWidget(val, self._row, 1)
        self._values[key] = val
        self._row += 1
        return val

    def add_led(self, key: str, label: str, color: str = "grey") -> Led:
        """Add a row whose value is a coloured :class:`Led`."""
        lbl = QLabel(label)
        lbl.setObjectName("FieldLabel")
        led = Led(color=color, diameter=16)
        wrap = QWidget()
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addStretch(1)
        hl.addWidget(led)
        self._grid.addWidget(lbl, self._row, 0)
        self._grid.addWidget(wrap, self._row, 1)
        self._leds[key] = led
        self._row += 1
        return led

    def add_badge(self, key: str, label: str, text: str = "", state: str = "disabled") -> StatusBadge:
        """Add a row whose value is a status pill :class:`StatusBadge`."""
        lbl = QLabel(label)
        lbl.setObjectName("FieldLabel")
        badge = StatusBadge(text=text, state=state)
        wrap = QWidget()
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addStretch(1)
        hl.addWidget(badge)
        self._grid.addWidget(lbl, self._row, 0)
        self._grid.addWidget(wrap, self._row, 1)
        self._badges[key] = badge
        self._row += 1
        return badge

    # ----------------------------------------------------------- row updates
    def set_value(self, key: str, value: str) -> None:
        """Update the text value of row *key* (no-op if the key is unknown)."""
        widget = self._values.get(key)
        if widget is not None:
            widget.setText(value)

    def set_led(self, key: str, color: str) -> None:
        """Update the LED colour of row *key*."""
        led = self._leds.get(key)
        if led is not None:
            led.set_color(color)

    def set_badge(self, key: str, text: str, state: str) -> None:
        """Update the badge text + state of row *key*."""
        badge = self._badges.get(key)
        if badge is not None:
            badge.set_state(state, text)

    def has_row(self, key: str) -> bool:
        """Return True if a row with the given key exists."""
        return key in self._values or key in self._leds or key in self._badges

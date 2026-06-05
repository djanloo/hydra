"""Led -- a small circular status LED indicator (CONTRACT.md section 6).

Layer: ``hydrafers.gui`` (PySide6). A pure presentation widget that paints a
glossy coloured circle, mirroring the green / red / grey LEDs of the CAEN Web
Interface (screenshots_gui/). It replaces the old tkinter ``leds.Led``
(janus-5202/gui/leds.py) with a resolution-independent ``QWidget`` paint.

Colours are addressed by symbolic name so callers do not hard-code hex values:
``"green"``, ``"red"``, ``"yellow"``/``"orange"``, ``"grey"`` (off), ``"blue"``.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

# Symbolic LED colour -> (core RGB, rim RGB). The rim is a slightly darker shade
# used for the outer ring so the LED reads as a glossy dot rather than a flat
# circle.
_LED_COLORS: dict[str, tuple[str, str]] = {
    "green": ("#43d957", "#1b8a2c"),
    "red": ("#ef4d4d", "#a31515"),
    "yellow": ("#f5c518", "#b8860b"),
    "orange": ("#f5a623", "#b56b00"),
    "blue": ("#42a5f5", "#1565c0"),
    "grey": ("#9aa7ad", "#5f6b70"),
    "gray": ("#9aa7ad", "#5f6b70"),
    "off": ("#cfd8dc", "#90a4ae"),
}


class Led(QWidget):
    """A circular LED indicator.

    Parameters
    ----------
    color:
        Initial symbolic colour name (default ``"grey"``).
    diameter:
        Pixel diameter of the LED (default 16).
    """

    def __init__(
        self,
        color: str = "grey",
        diameter: int = 16,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._diameter = int(diameter)
        self._color = "grey"
        self.set_color(color)
        self.setFixedSize(self._diameter + 2, self._diameter + 2)

    # ----------------------------------------------------------------- API
    def set_color(self, color: str) -> None:
        """Set the LED colour by symbolic name; unknown names fall back to grey."""
        key = (color or "grey").lower()
        if key not in _LED_COLORS:
            key = "grey"
        if key != self._color:
            self._color = key
            self.update()

    def color(self) -> str:
        """Return the current symbolic colour name."""
        return self._color

    def set_diameter(self, diameter: int) -> None:
        """Resize the LED to *diameter* pixels."""
        self._diameter = int(diameter)
        self.setFixedSize(self._diameter + 2, self._diameter + 2)
        self.update()

    # ----------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        core_hex, rim_hex = _LED_COLORS[self._color]
        core = QColor(core_hex)
        rim = QColor(rim_hex)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        d = float(self._diameter)
        rect = QRectF(1.0, 1.0, d, d)

        # Glossy radial gradient: a bright highlight near the top-left fading
        # into the core colour, ringed by the darker rim.
        gradient = QRadialGradient(
            QPointF(rect.center().x() - d * 0.18, rect.center().y() - d * 0.18),
            d * 0.75,
        )
        highlight = QColor(core)
        highlight = highlight.lighter(150)
        gradient.setColorAt(0.0, highlight)
        gradient.setColorAt(0.45, core)
        gradient.setColorAt(1.0, core.darker(115))

        painter.setPen(rim)
        painter.setBrush(gradient)
        painter.drawEllipse(rect)
        painter.end()

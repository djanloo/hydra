"""hydrafers.gui.icons — themed icon helper (CONTRACT.md §6).

Thin wrapper over `qtawesome <https://github.com/spyder-ide/qtawesome>`_ using the
Material Design Icons (``mdi6``) set for a single coherent icon pack across the
GUI. Degrades gracefully to empty icons if qtawesome is unavailable, so the app
still runs without the optional dependency.
"""

from __future__ import annotations

from PySide6.QtGui import QIcon

try:
    import qtawesome as _qta
except Exception:  # pragma: no cover - optional dependency
    _qta = None

# Semantic colours matching style.qss.
NAV      = "#607d8b"   # sidebar nav items
NEUTRAL  = "#455a64"   # default buttons on light background
ON_COLOR = "#ffffff"   # icons on coloured (blue/green/red/orange) buttons


def icon(name: str, color: str = NEUTRAL) -> QIcon:
    """Return a themed :class:`QIcon` for the ``mdi6`` *name*, or an empty icon."""
    if _qta is None:
        return QIcon()
    try:
        return _qta.icon(name, color=color)
    except Exception:  # pragma: no cover - unknown icon name
        return QIcon()


def available() -> bool:
    """True if the qtawesome icon backend is importable."""
    return _qta is not None

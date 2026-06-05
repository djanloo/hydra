"""Exception types for the FERS SDK.

Role: surface ferslib failures as Python exceptions. ``FERSError`` is the one
concession to Python made already in the faithful binding (``pyferslib`` raises
it when a ferslib call returns a negative code); this module simply re-exports
it so SDK users have a single import site. ``ConfigError`` is added by this
(pythonic) layer for configuration/validation problems that never reach the C
library.

Layer: ``pyfers`` (CONTRACT.md section 1b). Imports ``pyferslib`` ONLY.
"""

from __future__ import annotations

import pyferslib

# Re-export the binding's FERSError so callers can do ``from pyfers import
# FERSError`` and catch the exact type pyferslib raises. If a (test) fake
# pyferslib does not expose one, fall back to a compatible local definition so
# the SDK remains importable and usable standalone.
_BindingFERSError = getattr(pyferslib, "FERSError", None)

if _BindingFERSError is not None:
    FERSError = _BindingFERSError
else:  # pragma: no cover - exercised only when the binding lacks FERSError

    class FERSError(RuntimeError):
        """Raised when a ferslib call returns a negative error code.

        Fallback definition used only if ``pyferslib`` does not provide its own
        (e.g. a minimal test double). Mirrors the binding's ``(code, message)``
        construction signature.
        """

        def __init__(self, code: int = -1, message: str = "") -> None:
            self.code = int(code)
            self.message = str(message)
            super().__init__(f"FERS error {self.code}: {self.message}")


class ConfigError(ValueError):
    """Raised for SDK-level configuration / validation problems.

    Distinct from :class:`FERSError`: a ``ConfigError`` never reaches the C
    library (e.g. an unknown enum option, a board referenced before open, an
    invalid path classification). It subclasses :class:`ValueError` so existing
    ``except ValueError`` handlers keep working.
    """


__all__ = ["FERSError", "ConfigError"]

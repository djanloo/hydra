"""Object-oriented single-board access for the FERS SDK.

Role: turn the handle-and-string C API exposed by ``pyferslib`` into an
ergonomic :class:`Board` object (open/close/configure/registers + a context
manager) plus an :class:`HV` sub-object whose Python *properties* translate to
the ``pyferslib.hv_*`` calls. Setting ``board.hv.vbias = 62.5`` calls
``pyferslib.hv_set_vbias(handle, 62.5)``; reading ``board.hv.vmon`` calls
``pyferslib.hv_get_vmon(handle)``.

Layer: ``pyfers`` (CONTRACT.md section 1b). Imports ``pyferslib`` ONLY (plus the
sibling ``pyfers`` enum/error modules).
"""

from __future__ import annotations

from typing import Any

import pyferslib

from .enums import BoardFamily, SortMode
from .errors import ConfigError

# Configuration-mode string -> pyferslib constant (CFG_HARD / CFG_SOFT).
_CFG_MODES = {
    "hard": pyferslib.CFG_HARD,
    "soft": pyferslib.CFG_SOFT,
}


class HV:
    """High-voltage bias control for a single :class:`Board`.

    Bound to its parent board; every property maps to a ``pyferslib.hv_*`` call
    using the parent's handle. The board must be open before any HV access
    (otherwise a :class:`~pyfers.errors.ConfigError` is raised).
    """

    def __init__(self, board: "Board") -> None:
        self._board = board

    def _handle(self) -> int:
        return self._board.handle

    def init(self) -> None:
        """Initialize the HV subsystem (``pyferslib.hv_init``)."""
        pyferslib.hv_init(self._handle())

    # ------------------------------------------------------------------ on/off
    @property
    def on(self) -> bool:
        """HV output enabled state (read via ``hv_get_status``)."""
        status_on, _ramp, _ovc, _ovv = pyferslib.hv_get_status(self._handle())
        return bool(status_on)

    @on.setter
    def on(self, value: bool) -> None:
        pyferslib.hv_set_onoff(self._handle(), bool(value))

    # ------------------------------------------------------------------ vbias
    @property
    def vbias(self) -> float:
        """Programmed bias voltage in volts (``hv_get_vbias`` / ``hv_set_vbias``)."""
        return float(pyferslib.hv_get_vbias(self._handle()))

    @vbias.setter
    def vbias(self, value: float) -> None:
        pyferslib.hv_set_vbias(self._handle(), float(value))

    # ------------------------------------------------------------------ imax
    @property
    def imax(self) -> float:
        """Current compliance limit in mA.

        ferslib exposes a setter only; the SDK caches the last value written so
        ``board.hv.imax`` round-trips for interactive use. Use :attr:`imon` for
        the live measured current.
        """
        return float(self._board._imax_cache)

    @imax.setter
    def imax(self, value: float) -> None:
        pyferslib.hv_set_imax(self._handle(), float(value))
        self._board._imax_cache = float(value)

    # ------------------------------------------------------------------ monitors
    @property
    def vmon(self) -> float:
        """Measured bias voltage in volts (read-only, ``hv_get_vmon``)."""
        return float(pyferslib.hv_get_vmon(self._handle()))

    @property
    def imon(self) -> float:
        """Measured current in mA (read-only, ``hv_get_imon``)."""
        return float(pyferslib.hv_get_imon(self._handle()))

    @property
    def status(self) -> dict[str, int]:
        """HV status flags as ``{on, ramping, ovc, ovv}`` (read-only).

        Wraps the ``(on, ramping, ovc, ovv)`` tuple returned by
        ``pyferslib.hv_get_status``.
        """
        status_on, ramping, ovc, ovv = pyferslib.hv_get_status(self._handle())
        return {
            "on": int(status_on),
            "ramping": int(ramping),
            "ovc": int(ovc),
            "ovv": int(ovv),
        }

    @property
    def int_temp(self) -> float:
        """Internal HV-module temperature in degC (read-only)."""
        return float(pyferslib.hv_get_int_temp(self._handle()))

    @property
    def detector_temp(self) -> float:
        """Detector temperature in degC (read-only, via the HV sensor)."""
        return float(pyferslib.hv_get_detector_temp(self._handle()))


class Board:
    """A single FERS board (or concentrator endpoint) accessed via ``pyferslib``.

    Construct with a connection ``path`` (e.g. ``"eth:192.168.50.3"``); the
    board is NOT opened until :meth:`open` (or entering it as a context manager)
    is called. After opening, :attr:`handle` is valid and :attr:`info` is cached.
    """

    def __init__(self, path: str) -> None:
        self.path = str(path)
        self._handle: int | None = None
        self._info: Any | None = None
        self._imax_cache: float = 0.0
        self.hv = HV(self)

    # ------------------------------------------------------------------ props
    @property
    def handle(self) -> int:
        """The open ferslib handle. Raises :class:`ConfigError` if not open."""
        if self._handle is None:
            raise ConfigError(f"board {self.path!r} is not open")
        return self._handle

    @property
    def is_open(self) -> bool:
        """``True`` once :meth:`open` has succeeded and before :meth:`close`."""
        return self._handle is not None

    @property
    def info(self) -> Any:
        """Cached :class:`pyferslib.BoardInfo` for this board (read after open).

        Raises :class:`ConfigError` if the board has not been opened.
        """
        if self._info is None:
            raise ConfigError(f"board {self.path!r} is not open; no info available")
        return self._info

    @property
    def fers_code(self) -> int:
        """The ferslib ``FERSCode`` (e.g. 5202/5203), or 0 if unknown.

        Read from the cached board info; concentrator-only endpoints (no info)
        and not-yet-opened boards report 0.
        """
        if self._info is None:
            return 0
        return int(getattr(self._info, "fers_code", getattr(self._info, "FERSCode", 0)))

    @property
    def family(self) -> "BoardFamily | None":
        """The :class:`~pyfers.enums.BoardFamily`, or ``None`` if undetermined.

        Resolved from :attr:`fers_code` when available, else inferred from the
        board model name (``"A5202"``/``"A5203"``). ``None`` for a board that is
        not open or is a concentrator-only endpoint with no recognizable info.
        """
        code = self.fers_code
        if code:
            try:
                return BoardFamily.from_code(code)
            except ValueError:
                pass
        if self._info is not None:
            return BoardFamily.from_model_name(getattr(self._info, "model_name", ""))
        return None

    @property
    def has_hv(self) -> bool:
        """Whether this board has an HV bias generator (A5202 only).

        The A5203 picoTDC has none (all ``FERS_HV_*`` calls return
        NOT_APPLICABLE). When the family cannot be determined we conservatively
        assume HV is present (the legacy/default 5202 behaviour).
        """
        fam = self.family
        return fam.has_hv if fam is not None else True

    # ------------------------------------------------------------------ lifecycle
    def open(self) -> "Board":
        """Open the device and cache its board info; returns ``self`` for chaining."""
        if self._handle is not None:
            return self
        self._handle = int(pyferslib.open_device(self.path))
        try:
            self._info = pyferslib.get_board_info(self._handle)
        except Exception:
            # A concentrator-only endpoint has no BoardInfo; tolerate it so the
            # board object is still usable for register/HV operations.
            self._info = None
        return self

    def close(self) -> None:
        """Close the device handle if open. Idempotent."""
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        self._info = None
        pyferslib.close_device(handle)

    # ------------------------------------------------------------------ readout
    def init_readout(self, sort: SortMode = SortMode.DISABLED) -> int:
        """Initialize this board's readout buffers; returns the allocated size.

        ``sort`` selects the event-building/sorting mode (``ROMODE_*``).
        """
        return int(pyferslib.init_readout(self.handle, sort.to_romode()))

    def close_readout(self) -> None:
        """Release this board's readout buffers."""
        pyferslib.close_readout(self.handle)

    def flush_data(self) -> None:
        """Discard stale data still buffered in the readout pipes."""
        pyferslib.flush_data(self.handle)

    # ------------------------------------------------------------------ config
    def configure(self, mode: str = "hard") -> None:
        """Apply staged parameters to hardware (``"hard"`` reset or ``"soft"``)."""
        key = str(mode).strip().lower()
        if key not in _CFG_MODES:
            raise ConfigError(
                f"configure mode {mode!r} must be 'hard' or 'soft'"
            )
        pyferslib.configure(self.handle, _CFG_MODES[key])

    def set_param(self, name: str, value: str) -> None:
        """Set one ferslib parameter (escape hatch to the verbatim string API)."""
        pyferslib.set_param(self.handle, str(name), str(value))

    def get_param(self, name: str) -> str:
        """Read back one ferslib parameter value as a string."""
        return str(pyferslib.get_param(self.handle, str(name)))

    # ------------------------------------------------------------------ registers
    def read_register(self, address: int) -> int:
        """Read a board register at ``address``."""
        return int(pyferslib.read_register(self.handle, int(address)))

    def write_register(self, address: int, value: int) -> None:
        """Write ``value`` to the board register at ``address``."""
        pyferslib.write_register(self.handle, int(address), int(value))

    def send_command(self, cmd: int) -> None:
        """Send a board command opcode (``pyferslib.send_command``)."""
        pyferslib.send_command(self.handle, int(cmd))

    # ------------------------------------------------------------------ context
    def __enter__(self) -> "Board":
        return self.open()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        state = f"handle=0x{self._handle:05X}" if self._handle is not None else "closed"
        return f"Board(path={self.path!r}, {state})"


__all__ = ["Board", "HV"]

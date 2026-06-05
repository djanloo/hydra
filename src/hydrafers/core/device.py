"""Control-plane board wrapper over a ``pyfers.Board`` (monitoring/HV/registers).

Layer: ``hydrafers.core`` (CONTRACT.md section 0). Depends on the ``pyfers`` SDK
(section 1b) ONLY -- this is strictly control-plane (low-frequency: HV, temperatures,
status, registers). The high-rate data-plane never comes through here; it talks to
``pyferslib`` directly (see :mod:`hydrafers.core.readout`).

A :class:`BoardMonitor` adapts one ``pyfers.Board`` to the engine's needs: it builds
:class:`~hydrafers.core.state.BoardStatus` snapshots and offers defensive HV/temperature
reads (a failing individual read degrades to ``0.0`` rather than aborting a whole
monitoring tick). Concurrency and the run state-machine live in
:mod:`hydrafers.core.engine`; there is NO threading here.

ferslib parameter names are passed VERBATIM as strings via the board's escape-hatch
string API (``set_param``/``get_param``) where needed.
"""

from __future__ import annotations

import logging
from typing import Any

from .state import BoardStatus

logger = logging.getLogger("hydrafers.core.device")


class BoardMonitor:
    """Adapter around one ``pyfers.Board`` for engine control/monitoring.

    The board is owned by the engine's ``pyfers.System``; this wrapper only adapts
    it. Construction does not open the board (the ``System`` does that). All reads
    are defensive: a per-attribute failure becomes a zero/empty value so a status
    snapshot is always well-formed.
    """

    def __init__(self, index: int, board: Any) -> None:
        self.index = int(index)
        self.board = board
        self._hv_available = True  # assume present until a read proves otherwise

    # ------------------------------------------------------------------ identity
    @property
    def handle(self) -> int:
        """The ferslib handle (valid after the System has opened the board)."""
        try:
            return int(self.board.handle)
        except Exception:
            return -1

    @property
    def is_open(self) -> bool:
        try:
            return bool(self.board.is_open)
        except Exception:
            return False

    @property
    def path(self) -> str:
        return str(getattr(self.board, "path", ""))

    @property
    def info(self) -> Any:
        """The cached ``pyferslib.BoardInfo`` (pythonic attrs) for this board."""
        return getattr(self.board, "info", None)

    @property
    def num_ch(self) -> int:
        info = self.info
        if info is None:
            return 0
        return int(getattr(info, "num_ch", 0))

    # ------------------------------------------------------------------ HV
    def hv_init(self) -> None:
        """Initialize the HV subsystem. Tolerates boards without HV (logs, no raise)."""
        try:
            self.board.hv.init()
            self._hv_available = True
        except Exception as exc:
            self._hv_available = False
            logger.info("HV not available on %s: %s", self.path, exc)

    def hv_set(
        self,
        on: bool,
        vbias: float | None = None,
        imax: float | None = None,
    ) -> None:
        """Set HV state: optional Imax/Vbias then ON/OFF (control-plane only)."""
        if imax is not None:
            self.board.hv.imax = float(imax)
        if vbias is not None:
            self.board.hv.vbias = float(vbias)
        self.board.hv.on = bool(on)

    def hv_status(self) -> dict:
        """Return ``{on, ramping, ovc, ovv, vmon, imon, vbias}`` for this board.

        Empty/zeroed where HV is unavailable. Reads via the ``pyfers.HV`` properties
        (which translate to the ``pyferslib.hv_*`` calls).
        """
        if not self._hv_available:
            return {}
        status: dict = {}
        try:
            status = dict(self.board.hv.status)
        except Exception:
            status = {}
        status["vmon"] = self._safe_float(lambda: self.board.hv.vmon)
        status["imon"] = self._safe_float(lambda: self.board.hv.imon)
        status["vbias"] = self._safe_float(lambda: self.board.hv.vbias)
        return status

    # ------------------------------------------------------------------ registers
    def read_register(self, address: int) -> int:
        return int(self.board.read_register(int(address)))

    def write_register(self, address: int, value: int) -> None:
        self.board.write_register(int(address), int(value))

    def set_param(self, name: str, value: str) -> None:
        """Escape hatch to the verbatim ferslib string parameter API."""
        self.board.set_param(name, str(value))

    def get_param(self, name: str) -> str:
        return str(self.board.get_param(name))

    # ------------------------------------------------------------------ monitoring
    @staticmethod
    def _safe_float(fn: Any) -> float:
        try:
            return float(fn())
        except Exception:
            return 0.0

    def read_temperatures(self) -> dict[str, float]:
        """Read FPGA/board/HV/detector temperatures defensively.

        FPGA/board temps come from the board; HV/detector temps come from the HV
        sub-object's ``int_temp``/``detector_temp`` when HV is available.
        """
        temps = {
            "fpga": self._safe_float(lambda: self.board.fpga_temp),
            "board": self._safe_float(lambda: self.board.board_temp),
            "hv": 0.0,
            "detector": 0.0,
        }
        if self._hv_available:
            temps["hv"] = self._safe_float(lambda: self.board.hv.int_temp)
            temps["detector"] = self._safe_float(lambda: self.board.hv.detector_temp)
        return temps

    def status(self) -> BoardStatus:
        """Build a :class:`BoardStatus` snapshot by polling pyfers monitors.

        This issues device I/O and must NOT be called from the readout loop. The
        engine calls it from its monitoring/stats path. Failures degrade to zeros
        so the snapshot is always well-formed.
        """
        connected = self.is_open
        temps = self.read_temperatures()
        hv = self.hv_status()
        info = self.info
        model_name = str(getattr(info, "model_name", "")) if info is not None else ""
        fpga_fw = ""
        pid = 0
        if info is not None:
            # BoardInfo exposes fpga_fwrev (CONTRACT.md 1a); render as a string.
            fpga_fw = str(getattr(info, "fpga_fwrev", getattr(info, "fpga_fw", "")))
            pid = int(getattr(info, "pid", 0))
        return BoardStatus(
            index=self.index,
            handle=self.handle,
            pid=pid,
            model_name=model_name,
            fpga_fw=fpga_fw,
            connected=connected,
            temp_fpga=temps["fpga"],
            temp_board=temps["board"],
            temp_hv=temps["hv"],
            temp_detector=temps["detector"],
            hv_on=bool(hv.get("on", 0)),
            hv_vmon=float(hv.get("vmon", 0.0)),
            hv_imon=float(hv.get("imon", 0.0)),
            status_reg=0,
        )

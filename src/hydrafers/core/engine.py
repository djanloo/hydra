"""AcquisitionEngine: orchestrates a ``pyfers.System`` and the worker threads.

Layer: ``hydrafers.core`` (CONTRACT.md section 0). This class is the heart of the
renewal and uses BOTH Python layers per their plane (CONTRACT.md section 4,
FEASIBILITY_STUDY.md section 5.4):

* **control-plane** -> ``pyfers.System`` (ergonomic, low-frequency): connect /
  configure / start / stop / HV / registers all go through the SDK;
* **data-plane** -> ``pyferslib.drain_events`` (the faithful binding, minimal
  per-event overhead): the :class:`ReadoutThread` tight loop.

It depends on ``pyfers`` (1b) + ``pyferslib`` (1a, only for data-plane constants) +
``hydrafers.config`` (2) + ``hydrafers.io`` (3). It contains ZERO presentation logic:
CLI and GUI are interchangeable frontends over this identical API.

Threading model:
  * one :class:`ReadoutThread` per run: ``pyferslib.drain_events`` -> ring buffer;
  * one :class:`WriterThread`: ring buffer -> extract -> ``hydrafers.io.EventWriter``
    (+ a stats tap);
  * one :class:`StatsThread`: stats tap -> ``RunStatistics`` + histograms at ~15 Hz;
  * one ServiceThread: periodic HV/temperature reads via ``pyfers`` when idle (folded
    here as a lightweight background poller; the stats thread also taps SERVICE
    events while running so no device I/O hits the hot path).

All shared state is guarded by locks; ``board_status()``/``statistics()``/``histograms()``
return immutable snapshot copies. There are NO ``Sleep()`` polling loops -- every wait
is a ``queue`` timeout or a ``threading.Event``. Observers (``on_state_change``,
``on_error``, ``on_log``) are plain callables invoked from engine threads; frontends
marshal them onto their own event loop.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Any, Callable

import pyfers
import pyferslib

from .device import BoardMonitor
from .events import (
    HistogramSet,
    map_acq_mode_family,
    map_event_building_mode,
    map_start_mode,
    map_stop_mode,
)
from .readout import ReadoutThread
from .ringbuffer import RingBuffer
from .state import AcqState, BoardStatus, RunStatistics
from .statistics import StatsThread
from .writer import WriterThread

logger = logging.getLogger("hydrafers.core.engine")

# Default ring-buffer capacities. The event ring is sized generously so rate spikes
# are absorbed in memory rather than stalling the readout (FEASIBILITY_STUDY 4.1).
_EVENT_RING_CAPACITY = 200_000
_STATS_TAP_CAPACITY = 200_000
_STATS_QUEUE_DEPTH = 64

# Idle-service cadence: when not running, poll HV/temps this often for the panel.
_SERVICE_PERIOD_S = 2.0

# Histogram bin-count lookup for the EHistoNbin/ToAHistoNbin/MCSHistoNbin combos.
_NBIN_OPTIONS: dict[str, int] = {
    "DISABLED": 1,
    "256": 256,
    "512": 512,
    "1K": 1024,
    "2K": 2048,
    "4K": 4096,
    "8K": 8192,
    "16K": 16384,
}


def _parse_nbins(value: str, default: int = 4096) -> int:
    """Resolve a histogram-nbin combo string (e.g. ``"4K"``) to an int."""
    return _NBIN_OPTIONS.get(str(value).strip().upper(), default)


class AcquisitionEngine:
    """Multithreaded FERS acquisition engine (CONTRACT.md section 4).

    Construct with an optional :class:`~hydrafers.config.HydraConfig`. Call
    :meth:`connect` to open and configure hardware, then :meth:`start_run` /
    :meth:`stop_run`. :meth:`close` performs a full, ``atexit``-safe shutdown.
    """

    def __init__(self, config: Any | None = None) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._hist_lock = threading.Lock()

        self._state = AcqState.DISCONNECTED

        # Control-plane: the pyfers System + per-board monitor adapters.
        self._system: Any | None = None
        self._monitors: list[BoardMonitor] = []
        self._handles: list[int] = []  # board handles for the data-plane

        # Run-scoped objects (created in start_run, torn down in stop_run).
        self._ring: RingBuffer | None = None
        self._stats_tap: RingBuffer | None = None
        self._readout: ReadoutThread | None = None
        self._writer_thread: WriterThread | None = None
        self._stats_thread: StatsThread | None = None
        self._event_writer: Any | None = None
        self._run_stop = threading.Event()
        self._supervisor: threading.Thread | None = None

        self._run_number = 0
        self._start_mode: "pyfers.StartMode" = pyfers.StartMode.ASYNC
        self._sort_mode: "pyfers.SortMode" = pyfers.SortMode.DISABLED
        self._stop_mode: "pyfers.StopMode" = pyfers.StopMode.MANUAL
        self._preset_time_s = 0.0
        self._preset_counts = 0
        self._run_t0 = 0.0

        # Idle service thread (HV/temps for the monitoring panel when not running).
        self._service_stop = threading.Event()
        self._service_thread: threading.Thread | None = None

        # Shared snapshots returned to frontends.
        self._histograms = HistogramSet(0)
        self._latest_stats = RunStatistics.empty(0)
        self._board_status_cache: list[BoardStatus] = []

        # Frontend-facing queue.
        self._stats_queue: "queue.Queue[RunStatistics]" = queue.Queue(
            maxsize=_STATS_QUEUE_DEPTH
        )

        # Observers (set by frontend).
        self.on_state_change: Callable[[AcqState], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self.on_log: Callable[[str, str], None] | None = None

    # ================================================================= observers
    def _log(self, level: str, message: str) -> None:
        logger.log(
            {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}.get(
                level, logging.INFO
            ),
            message,
        )
        cb = self.on_log
        if cb is not None:
            try:
                cb(level, message)
            except Exception:  # pragma: no cover - frontend bug must not kill engine
                logger.exception("on_log observer raised")

    def _emit_error(self, message: str) -> None:
        self._log("error", message)
        cb = self.on_error
        if cb is not None:
            try:
                cb(message)
            except Exception:  # pragma: no cover
                logger.exception("on_error observer raised")

    def _set_state(self, state: AcqState) -> None:
        with self._lock:
            if self._state is state:
                return
            self._state = state
        logger.debug("state -> %s", state.name)
        cb = self.on_state_change
        if cb is not None:
            try:
                cb(state)
            except Exception:  # pragma: no cover
                logger.exception("on_state_change observer raised")

    # ================================================================= properties
    @property
    def state(self) -> AcqState:
        with self._lock:
            return self._state

    @property
    def config(self) -> Any | None:
        return self._config

    @property
    def system(self) -> Any | None:
        """The underlying ``pyfers.System`` (control-plane), or ``None``."""
        return self._system

    # ================================================================= config helpers
    def _config_param(self, name: str, default: str = "") -> str:
        """Look up a flattened ferslib param value (global scope) from the config.

        Uses :meth:`HydraConfig.to_ferslib_params` so it sees the exact values that
        will be pushed to hardware, independent of the model's field layout.
        """
        if self._config is None:
            return default
        try:
            params = self._config.to_ferslib_params()
        except Exception:
            return default
        for _bidx, pname, value in params:
            if pname == name:
                return str(value)
        return default

    def _config_params(self) -> list[tuple[int, str, str]]:
        """Return the flattened ``(board_index, name, value)`` config tuples."""
        if self._config is None:
            return []
        try:
            return list(self._config.to_ferslib_params())
        except Exception as exc:
            raise RuntimeError(f"failed to flatten configuration: {exc}") from exc

    # ================================================================= lifecycle
    def connect(self) -> None:
        """Build the ``pyfers.System``, open, init readout, configure and init HV.

        Per CONTRACT.md section 4: ``pyfers.System.from_config(config)``; open;
        ``init_readout`` with the ``SortMode`` derived from ``EventBuildingMode``;
        configure via ``config.to_ferslib_params()`` + ``System.configure``; HV init.
        """
        with self._lock:
            if self._state not in (AcqState.DISCONNECTED, AcqState.ERROR):
                raise RuntimeError(f"cannot connect from state {self._state.name}")
            if self._config is None:
                raise RuntimeError("no configuration set; cannot connect")
        self._set_state(AcqState.CONNECTING)
        try:
            # Build and open the system from the config (control-plane SDK does the
            # device-open + concentrator/TDL orchestration).
            self._system = pyfers.System.from_config(self._config)
            self._handles = list(self._system.handles)
            self._monitors = [
                BoardMonitor(index, board)
                for index, board in enumerate(self._system.boards)
            ]
            self._log("info", f"opened {len(self._monitors)} board(s)")

            # Init readout buffers with the sort mode derived from the config.
            self._sort_mode = self._resolve_sort_mode()
            for board in self._system.boards:
                board.init_readout(self._sort_mode)
            logger.debug("init_readout(sort=%s) done", self._sort_mode.name)

            # Apply the configuration (hard) via the System.
            self._apply_config(soft=False)

            # Initialize HV on every board (tolerant of boards without HV).
            for mon in self._monitors:
                mon.hv_init()

            # Size the shared snapshot containers for the connected board count.
            self._reindex_snapshots()
            self._refresh_board_status()
            self._start_service_thread()
            self._set_state(AcqState.READY)
            self._log("info", f"connected {len(self._monitors)} board(s)")
        except Exception as exc:
            self._emit_error(f"connect failed: {exc}")
            self._set_state(AcqState.ERROR)
            raise

    def _resolve_sort_mode(self) -> "pyfers.SortMode":
        mode = self._config_param("EventBuildingMode", "DISABLED")
        try:
            return map_event_building_mode(mode)
        except ValueError:
            return pyfers.SortMode.DISABLED

    def _reindex_snapshots(self) -> None:
        nboards = len(self._monitors)
        e_nbins = _parse_nbins(self._config_param("EHistoNbin", "4K"))
        toa_nbins = _parse_nbins(self._config_param("ToAHistoNbin", "4K"))
        mcs_nbins = _parse_nbins(self._config_param("MCSHistoNbin", "4K"))
        with self._hist_lock:
            self._histograms = HistogramSet(
                nboards, e_nbins=e_nbins, toa_nbins=toa_nbins, mcs_nbins=mcs_nbins
            )
        with self._lock:
            self._latest_stats = RunStatistics.empty(nboards, self._run_number)

    def _apply_config(self, soft: bool) -> None:
        """Push ``to_ferslib_params`` to the System, then ``System.configure``."""
        if self._config is None or self._system is None:
            return
        params = self._config_params()
        mode = "soft" if soft else "hard"
        # System.configure applies each (board_index, name, value) via set_param then
        # calls pyferslib.configure with CFG_SOFT/CFG_HARD (CONTRACT.md 1b).
        self._system.configure(params, mode=mode)
        self._log("info", f"configuration applied ({mode})")

    def configure(self, config: Any, soft: bool = False) -> None:
        """Replace the active config and (re)apply it to connected hardware."""
        with self._lock:
            self._config = config
            if self._state == AcqState.RUNNING and not soft:
                raise RuntimeError("hard reconfigure not allowed while running")
        if self._system is not None:
            self._apply_config(soft=soft)
            if not soft:
                self._reindex_snapshots()
            self._refresh_board_status()

    def disconnect(self) -> None:
        """Stop any run, then close the ``pyfers.System`` (closes readout + handles)."""
        if self.state == AcqState.RUNNING:
            self.stop_run()
        self._stop_service_thread()
        if self._system is not None:
            try:
                self._system.close()
            except Exception as exc:  # pragma: no cover - best-effort close
                self._log("warning", f"closing system failed: {exc}")
        self._system = None
        self._monitors = []
        self._handles = []
        self._set_state(AcqState.DISCONNECTED)
        self._log("info", "disconnected")

    def close(self) -> None:
        """Full shutdown; safe to call from ``atexit`` and idempotent."""
        try:
            if self.state == AcqState.RUNNING:
                self.stop_run()
        except Exception:  # pragma: no cover - best-effort shutdown
            logger.exception("stop_run during close failed")
        try:
            self.disconnect()
        except Exception:  # pragma: no cover
            logger.exception("disconnect during close failed")

    # ================================================================= run control
    def start_run(self, run_number: int | None = None) -> None:
        """Start acquisition and spin up the readout/writer/stats threads."""
        with self._lock:
            if self._state != AcqState.READY:
                raise RuntimeError(f"cannot start run from state {self._state.name}")
            if self._system is None or not self._handles:
                raise RuntimeError("no boards connected")
            if run_number is not None:
                self._run_number = int(run_number)
        self._set_state(AcqState.STARTING)
        try:
            self._start_mode = map_start_mode(self._config_param("StartRunMode", "ASYNC"))
            self._resolve_stop_policy()

            counting = (
                map_acq_mode_family(self._config_param("AcquisitionMode", "SPECTROSCOPY"))
                == pyferslib.DTQ_COUNT
            )

            # Pause the idle-service poller while running (stats taps SERVICE events).
            self._stop_service_thread()

            # Fresh run-scoped buffers and counters.
            self._ring = RingBuffer(_EVENT_RING_CAPACITY)
            self._stats_tap = RingBuffer(_STATS_TAP_CAPACITY)
            self._run_stop = threading.Event()
            with self._hist_lock:
                self._histograms.reset()
            self._drain_queue(self._stats_queue)

            # Flush stale pipe data via the System, then open the output writer.
            self._system.flush()
            self._event_writer = self._open_writer()

            # Build threads.
            self._writer_thread = WriterThread(
                self._ring,
                self._event_writer,
                self._run_stop,
                stats_tap=self._stats_tap,
                on_error=self._emit_error,
            )
            self._stats_thread = StatsThread(
                self._stats_tap,
                nboards=len(self._monitors),
                run_number=self._run_number,
                stats_queue=self._stats_queue,
                histograms=self._histograms,
                hist_lock=self._hist_lock,
                stop_event=self._run_stop,
                counting_mode=counting,
                on_snapshot=self._on_stats_snapshot,
            )
            self._readout = ReadoutThread(
                self._handles,
                self._ring,
                self._run_stop,
                on_reprocess_finished=self._on_reprocess_finished,
                on_error=self._emit_error,
            )

            # Start consumers before the producer so nothing accumulates unread.
            self._stats_thread.start()
            self._writer_thread.start()

            # Control-plane start via the SDK (StartMode enum, run number).
            self._system.start_run(self._start_mode, self._run_number)
            self._run_t0 = time.monotonic()
            self._readout.start()

            # Supervisor enforces preset-time / preset-counts stop policy.
            self._supervisor = threading.Thread(
                target=self._supervise_run, name="hydrafers-supervisor", daemon=True
            )
            self._supervisor.start()

            self._set_state(AcqState.RUNNING)
            self._log("info", f"run {self._run_number} started")
        except Exception as exc:
            self._emit_error(f"start_run failed: {exc}")
            self._teardown_run_threads()
            self._set_state(AcqState.ERROR)
            raise

    def _resolve_stop_policy(self) -> None:
        self._stop_mode = map_stop_mode(self._config_param("StopRunMode", "MANUAL"))
        self._preset_time_s = _parse_seconds(self._config_param("PresetTime", "0"))
        try:
            self._preset_counts = int(float(self._config_param("PresetCounts", "0")))
        except ValueError:
            self._preset_counts = 0

    def _open_writer(self) -> Any | None:
        """Create a ``hydrafers.io.EventWriter`` if an output path is configured.

        Returns ``None`` when no output file is requested (e.g. benchmark mode), in
        which case the writer thread simply discards events while still feeding the
        stats tap.
        """
        data_path = self._config_param("DataFilePath", "").strip()
        # Any of the list-file toggles enables persistence.
        want_output = any(
            self._config_param(flag, "0").strip() not in ("0", "", "false", "False")
            for flag in ("OF_ListBin", "OF_ListAscii", "OF_ListCSV", "OF_RawData")
        )
        if not data_path or not want_output:
            self._log("info", "no output file configured; running without disk writes")
            return None
        try:
            from hydrafers.io import EventWriter, FileHeader
        except Exception as exc:  # pragma: no cover - io layer optional at runtime
            self._log("warning", f"hydrafers.io unavailable, skipping writer: {exc}")
            return None

        model = ""
        if self._monitors:
            info = self._monitors[0].info
            model = str(getattr(info, "model_name", "")) if info is not None else ""
        header = FileHeader(
            format_version=1,
            acquisition_mode=self._config_param("AcquisitionMode", "SPECTROSCOPY"),
            energy_nbins=_parse_nbins(self._config_param("EHistoNbin", "4K")),
            toa_lsb_ns=0.5,
            start_time=int(time.time() * 1000),
            board_model=str(model),
            run_number=self._run_number,
        )
        os.makedirs(data_path, exist_ok=True)
        out_path = os.path.join(data_path, f"Run{self._run_number}_list.dat")
        self._log("info", f"writing events to {out_path}")
        return EventWriter(out_path, header)

    def _supervise_run(self) -> None:
        """Background watchdog implementing PRESET_TIME / PRESET_COUNTS stop."""
        while not self._run_stop.is_set():
            # Interruptible 50 ms tick (no busy spin; returns early on stop).
            if self._run_stop.wait(0.05):
                break
            if self._stop_mode == pyfers.StopMode.PRESET_TIME and self._preset_time_s > 0:
                if (time.monotonic() - self._run_t0) >= self._preset_time_s:
                    self._log("info", "preset time reached; stopping run")
                    threading.Thread(target=self.stop_run, daemon=True).start()
                    break
            elif (
                self._stop_mode == pyfers.StopMode.PRESET_COUNTS
                and self._preset_counts > 0
            ):
                if self._latest_stats.total_events >= self._preset_counts:
                    self._log("info", "preset counts reached; stopping run")
                    threading.Thread(target=self.stop_run, daemon=True).start()
                    break

    def _on_reprocess_finished(self) -> None:
        self._log("info", "raw-data reprocessing finished; stopping run")
        threading.Thread(target=self.stop_run, daemon=True).start()

    def stop_run(self) -> None:
        """Stop acquisition, drain the pipeline and return to READY."""
        with self._lock:
            if self._state not in (AcqState.RUNNING, AcqState.STARTING):
                return
        self._set_state(AcqState.STOPPING)
        try:
            # Stop hardware first so no new events are produced (control-plane SDK).
            try:
                self._system.stop_run(self._start_mode, self._run_number)
            except Exception as exc:
                self._log("warning", f"stop_run reported: {exc}")

            # Signal threads and let the readout exit, then enter EMPTYING so the
            # writer/stats drain whatever is still buffered.
            self._run_stop.set()
            if self._readout is not None:
                self._readout.join(timeout=5.0)
            self._set_state(AcqState.EMPTYING)
            if self._writer_thread is not None:
                self._writer_thread.join(timeout=10.0)
            if self._stats_thread is not None:
                self._stats_thread.join(timeout=5.0)

            if self._event_writer is not None:
                try:
                    self._event_writer.close()
                except Exception as exc:  # pragma: no cover
                    self._log("warning", f"closing writer failed: {exc}")

            dropped = self._ring.dropped() if self._ring is not None else 0
            if dropped:
                self._log("warning", f"run dropped {dropped} events under backpressure")
            self._log("info", f"run {self._run_number} stopped")
        except Exception as exc:
            self._emit_error(f"stop_run failed: {exc}")
            self._set_state(AcqState.ERROR)
            self._teardown_run_threads()
            return
        finally:
            self._teardown_run_threads()
        self._refresh_board_status()
        self._start_service_thread()
        self._set_state(AcqState.READY)

    def _teardown_run_threads(self) -> None:
        self._readout = None
        self._writer_thread = None
        self._stats_thread = None
        self._supervisor = None
        self._event_writer = None
        self._ring = None
        self._stats_tap = None

    # ================================================================= service thread
    def _start_service_thread(self) -> None:
        """Spin up the idle HV/temperature poller for the monitoring panel."""
        if self._service_thread is not None and self._service_thread.is_alive():
            return
        self._service_stop = threading.Event()
        self._service_thread = threading.Thread(
            target=self._service_loop, name="hydrafers-service", daemon=True
        )
        self._service_thread.start()

    def _stop_service_thread(self) -> None:
        self._service_stop.set()
        thread = self._service_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._service_thread = None

    def _service_loop(self) -> None:
        """Periodically refresh board status from the SDK while not acquiring.

        Uses an interruptible ``Event.wait`` cadence -- no ``Sleep()`` busy-poll.
        While running, the stats thread taps SERVICE events instead, so this poller
        never issues device I/O on the hot path.
        """
        while not self._service_stop.wait(_SERVICE_PERIOD_S):
            if self.state in (AcqState.READY, AcqState.CONNECTING):
                try:
                    self._refresh_board_status()
                except Exception:  # pragma: no cover - monitoring must not crash
                    logger.exception("service-thread status refresh failed")

    # ================================================================= snapshots
    def _on_stats_snapshot(self, snapshot: RunStatistics) -> None:
        with self._lock:
            self._latest_stats = snapshot
        # Merge the latest service-event monitoring into the board-status cache.
        self._refresh_board_status_from_service()

    def _refresh_board_status(self) -> None:
        """Poll every monitor for a fresh status snapshot (control-path only)."""
        statuses = [mon.status() for mon in self._monitors]
        with self._lock:
            self._board_status_cache = statuses

    def _refresh_board_status_from_service(self) -> None:
        """Update cached board status from service events seen by the stats thread.

        Used while running so we never issue blocking device reads on the hot path.
        """
        if self._stats_thread is None:
            return
        service = self._stats_thread.latest_service()
        if not service:
            return
        with self._lock:
            updated: list[BoardStatus] = []
            for status in self._board_status_cache:
                svc = service.get(status.index)
                if svc is None:
                    updated.append(status)
                    continue
                updated.append(
                    BoardStatus(
                        index=status.index,
                        handle=status.handle,
                        pid=status.pid,
                        model_name=status.model_name,
                        fpga_fw=status.fpga_fw,
                        connected=status.connected,
                        temp_fpga=float(svc.get("temp_fpga", status.temp_fpga)),
                        temp_board=float(svc.get("temp_board", status.temp_board)),
                        temp_hv=float(svc.get("temp_hv", status.temp_hv)),
                        temp_detector=float(
                            svc.get("temp_detector", status.temp_detector)
                        ),
                        hv_on=bool(svc.get("hv_on", status.hv_on)),
                        hv_vmon=float(svc.get("hv_vmon", status.hv_vmon)),
                        hv_imon=float(svc.get("hv_imon", status.hv_imon)),
                        status_reg=int(svc.get("status", status.status_reg)),
                    )
                )
            self._board_status_cache = updated

    def board_status(self) -> list[BoardStatus]:
        """Return an immutable list of per-board status snapshots."""
        if self.state != AcqState.RUNNING:
            # Safe to poll hardware when not in the hot path.
            self._refresh_board_status()
        with self._lock:
            return list(self._board_status_cache)

    def statistics(self) -> RunStatistics:
        """Return the latest immutable :class:`RunStatistics` snapshot."""
        with self._lock:
            return self._latest_stats.copy()

    def histograms(self) -> dict:
        """Return independent copies of the live histograms."""
        with self._hist_lock:
            return self._histograms.snapshot()

    def stats_queue(self) -> "queue.Queue[RunStatistics]":
        """Queue onto which ~15 Hz statistics snapshots are pushed."""
        return self._stats_queue

    @staticmethod
    def _drain_queue(q: "queue.Queue[Any]") -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break

    # ================================================================= HV control
    def _monitor_by_index(self, board_index: int) -> BoardMonitor:
        for mon in self._monitors:
            if mon.index == board_index:
                return mon
        raise IndexError(f"no board with index {board_index}")

    def hv_set(
        self,
        board_index: int,
        on: bool,
        vbias: float | None = None,
        imax: float | None = None,
    ) -> None:
        """Set HV state for one board: optional Vbias/Imax then ON/OFF."""
        mon = self._monitor_by_index(board_index)
        mon.hv_set(on, vbias=vbias, imax=imax)
        self._log(
            "info",
            f"HV board {board_index}: {'ON' if on else 'OFF'}"
            + (f" Vbias={vbias}" if vbias is not None else "")
            + (f" Imax={imax}" if imax is not None else ""),
        )

    def hv_status(self, board_index: int) -> dict:
        """Return ``{on, ramping, ovc, ovv, vmon, imon, vbias}`` for one board."""
        return self._monitor_by_index(board_index).hv_status()

    # ================================================================= registers
    def read_register(self, board_index: int, address: int) -> int:
        """Read a board register (advanced tab)."""
        return self._monitor_by_index(board_index).read_register(int(address))

    def write_register(self, board_index: int, address: int, value: int) -> None:
        """Write a board register (advanced tab)."""
        self._monitor_by_index(board_index).write_register(int(address), int(value))


def _parse_seconds(value: str) -> float:
    """Parse a PresetTime value (e.g. ``"1 m"``, ``"30 s"``, ``"500 ms"``) to seconds.

    Accepts a bare number (seconds) or ``<number> <unit>`` with unit in
    {ms, s, m, h}. Unknown/empty input yields 0.0.
    """
    text = str(value).strip()
    if not text:
        return 0.0
    parts = text.split()
    try:
        num = float(parts[0])
    except ValueError:
        return 0.0
    if len(parts) == 1:
        return num
    unit = parts[1].strip().lower()
    factors = {"ms": 1e-3, "s": 1.0, "m": 60.0, "min": 60.0, "h": 3600.0}
    return num * factors.get(unit, 1.0)

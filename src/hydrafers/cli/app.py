"""hydrafers.cli.app — Textual TUI dashboard for HydraFERS.

Layer (CONTRACT.md §0): depends only on ``hydrafers.core`` and
``hydrafers.config``. No ``pyfers``, no Qt.

The dashboard (CONTRACT.md §5) renders a live view of an
:class:`hydrafers.core.AcquisitionEngine`:

    * a board tree (one node per configured board, with model / handle / temps),
    * a live statistics table (rates, totals, data volume),
    * sparklines of event rate and data rate history,
    * the engine state and key bindings to start / stop a run and quit.

The app subscribes to ``engine.stats_queue()``. Because the engine pushes
snapshots from its own threads, the TUI never reads that queue from a thread:
instead a Textual interval timer drains the queue inside the app's event loop
(the simple, robust pattern — mirrors the GUI's QTimer poll in §6). Engine
observers (``on_state_change`` / ``on_error`` / ``on_log``) fire on engine
threads, so they are marshalled back into the Textual loop via
``App.call_from_thread``.
"""

from __future__ import annotations

import collections
import logging
from pathlib import Path
from queue import Empty
from typing import TYPE_CHECKING

from hydrafers.config import HydraConfig, default_config, load_config
from hydrafers.core import AcqState, AcquisitionEngine, BoardStatus, RunStatistics

if TYPE_CHECKING:  # pragma: no cover - typing only
    from queue import Queue

logger = logging.getLogger("hydrafers.cli.app")

# Number of points retained for the sparkline history.
_SPARK_HISTORY = 60
# How often (seconds) the app polls the stats queue / refreshes the board tree.
_POLL_INTERVAL = 0.1


def _import_textual():
    """Import Textual lazily so the rest of hydrafers.cli works without it.

    Returns a namespace of the Textual symbols used by this module. Raising a
    clear error here (rather than at module import) keeps ``hydrafers-cli run``
    and ``benchmark`` usable on hosts that did not install the ``[cli]`` extra's
    Textual dependency.
    """
    try:
        from textual import work  # noqa: F401  (kept for parity / future use)
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Container, Horizontal, Vertical
        from textual.reactive import reactive
        from textual.widgets import (
            DataTable,
            Footer,
            Header,
            Label,
            Sparkline,
            Static,
            Tree,
        )
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "The Textual TUI requires the 'textual' package. Install it with "
            "`pip install textual` or install hydrafers with the [cli] extra."
        ) from exc

    return {
        "App": App,
        "ComposeResult": ComposeResult,
        "Binding": Binding,
        "Container": Container,
        "Horizontal": Horizontal,
        "Vertical": Vertical,
        "reactive": reactive,
        "DataTable": DataTable,
        "Footer": Footer,
        "Header": Header,
        "Label": Label,
        "Sparkline": Sparkline,
        "Static": Static,
        "Tree": Tree,
    }


# State -> human label / colour used in the status bar.
_STATE_STYLE: dict[AcqState, str] = {
    AcqState.DISCONNECTED: "dim",
    AcqState.CONNECTING: "yellow",
    AcqState.READY: "green",
    AcqState.STARTING: "yellow",
    AcqState.RUNNING: "bold green",
    AcqState.STOPPING: "yellow",
    AcqState.EMPTYING: "yellow",
    AcqState.ERROR: "bold red",
    AcqState.UPGRADING_FW: "magenta",
}


def _human_bytes(n: int | float) -> str:
    """Render a byte count as a human-readable string."""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:,.2f} {unit}"
        value /= 1024.0
    return f"{value:,.2f} TB"


def build_app(engine: AcquisitionEngine, config: HydraConfig):
    """Construct (but do not run) the Textual dashboard ``App`` instance.

    The ``App`` subclass is defined inside this factory so that Textual is only
    imported when a TUI is actually requested (see :func:`_import_textual`).
    """
    tx = _import_textual()
    App = tx["App"]
    Binding = tx["Binding"]
    Horizontal = tx["Horizontal"]
    Vertical = tx["Vertical"]
    reactive = tx["reactive"]
    DataTable = tx["DataTable"]
    Footer = tx["Footer"]
    Header = tx["Header"]
    Label = tx["Label"]
    Sparkline = tx["Sparkline"]
    Static = tx["Static"]
    Tree = tx["Tree"]

    class HydraFersTUI(App):
        """Live acquisition dashboard."""

        CSS = """
        Screen {
            layout: vertical;
        }
        #status_bar {
            height: 1;
            dock: top;
            background: $panel;
            color: $text;
            padding: 0 1;
        }
        #body {
            height: 1fr;
        }
        #left_pane {
            width: 36;
            border: round $primary;
        }
        #right_pane {
            width: 1fr;
        }
        #stats_table {
            height: 1fr;
            border: round $primary;
        }
        #spark_pane {
            height: auto;
            border: round $primary;
            padding: 0 1;
        }
        .spark_label {
            height: 1;
            color: $text-muted;
        }
        Sparkline {
            height: 3;
            margin-bottom: 1;
        }
        #board_tree {
            height: 1fr;
        }
        """

        BINDINGS = [
            Binding("s", "start_run", "Start"),
            Binding("x", "stop_run", "Stop"),
            Binding("r", "refresh_now", "Refresh"),
            Binding("q", "quit_app", "Quit"),
            Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
        ]

        # Reactive mirror of the engine state, used to keep the status bar live.
        engine_state: "reactive[AcqState]" = reactive(AcqState.DISCONNECTED)

        def __init__(self) -> None:
            super().__init__()
            self._engine = engine
            self._config = config
            self._stats_q: "Queue[RunStatistics]" = engine.stats_queue()
            self._latest: RunStatistics | None = None
            self._rate_hist: collections.deque[float] = collections.deque(
                maxlen=_SPARK_HISTORY
            )
            self._mbps_hist: collections.deque[float] = collections.deque(
                maxlen=_SPARK_HISTORY
            )
            self._run_counter = 0
            self._last_log: str = ""

        # -- layout -----------------------------------------------------------
        def compose(self):
            yield Header(show_clock=True)
            yield Static("", id="status_bar")
            with Horizontal(id="body"):
                with Vertical(id="left_pane"):
                    yield Tree("Boards", id="board_tree")
                with Vertical(id="right_pane"):
                    yield DataTable(id="stats_table", zebra_stripes=True)
                    with Vertical(id="spark_pane"):
                        yield Label("Event rate (Hz)", classes="spark_label")
                        yield Sparkline([0.0], id="spark_rate", summary_function=max)
                        yield Label("Data rate (MB/s)", classes="spark_label")
                        yield Sparkline([0.0], id="spark_mbps", summary_function=max)
            yield Footer()

        def on_mount(self) -> None:
            # Stats table columns.
            table = self.query_one("#stats_table", DataTable)
            table.add_column("Metric", key="metric")
            table.add_column("Value", key="value")
            for metric in (
                "Run number",
                "Elapsed",
                "Total events",
                "Built events",
                "Event rate",
                "Data volume",
                "Data rate",
            ):
                table.add_row(metric, "—", key=metric)

            # Wire engine observers (called from engine threads -> marshal back).
            self._engine.on_state_change = self._on_state_change
            self._engine.on_error = self._on_error
            self._engine.on_log = self._on_log

            self.engine_state = self._engine.state
            self._populate_board_tree()
            self._update_status_bar()

            # Single interval timer drives both the stats drain and the slower
            # board/monitoring refresh.
            self.set_interval(_POLL_INTERVAL, self._tick)
            self._monitor_div = 0

        # -- periodic update --------------------------------------------------
        def _tick(self) -> None:
            """Drain stats queue, update tables and sparklines.

            Runs inside the Textual event loop (timer callback), so all widget
            access here is safe.
            """
            drained = self._drain_stats()
            if drained is not None:
                self._latest = drained
                self._rate_hist.append(float(drained.event_rate_hz))
                self._mbps_hist.append(float(drained.data_rate_mbps))
                self._refresh_stats_table()
                self._refresh_sparklines()

            # Refresh the board tree (temps / HV) at a slower cadence so the
            # monitoring snapshot does not dominate the loop.
            self._monitor_div = (self._monitor_div + 1) % 10
            if self._monitor_div == 0:
                self._refresh_board_tree()

            # Keep the reactive state in sync even without an explicit callback
            # (the engine may transition internally, e.g. preset-time stop).
            cur = self._engine.state
            if cur is not self.engine_state:
                self.engine_state = cur

        def _drain_stats(self) -> RunStatistics | None:
            """Pull the freshest snapshot from the stats queue (non-blocking)."""
            latest: RunStatistics | None = None
            while True:
                try:
                    latest = self._stats_q.get_nowait()
                except Empty:
                    break
            return latest

        # -- table / sparkline rendering -------------------------------------
        def _refresh_stats_table(self) -> None:
            stats = self._latest
            if stats is None:
                return
            table = self.query_one("#stats_table", DataTable)
            rows = {
                "Run number": str(stats.run_number),
                "Elapsed": f"{stats.elapsed_s:,.1f} s",
                "Total events": f"{stats.total_events:,}",
                "Built events": f"{stats.built_events:,}",
                "Event rate": f"{stats.event_rate_hz:,.1f} Hz",
                "Data volume": _human_bytes(stats.byte_count),
                "Data rate": f"{stats.data_rate_mbps:,.2f} MB/s",
            }
            for key, value in rows.items():
                try:
                    table.update_cell(key, "value", value)
                except Exception:  # pragma: no cover - row missing, ignore
                    pass

        def _refresh_sparklines(self) -> None:
            rate = self.query_one("#spark_rate", Sparkline)
            mbps = self.query_one("#spark_mbps", Sparkline)
            rate.data = list(self._rate_hist) or [0.0]
            mbps.data = list(self._mbps_hist) or [0.0]

        # -- board tree -------------------------------------------------------
        def _populate_board_tree(self) -> None:
            """Build the board tree from the config (before connection)."""
            tree = self.query_one("#board_tree", Tree)
            tree.clear()
            root = tree.root
            root.expand()
            boards = getattr(self._config, "boards", []) or []
            if not boards:
                root.add_leaf("(no boards configured)")
                return
            for idx, board in enumerate(boards):
                conn = self._board_connection_str(board)
                node = root.add(f"Board {idx} — {conn}", expand=True)
                node.add_leaf("status: not connected")

        def _refresh_board_tree(self) -> None:
            """Repopulate the board tree from live :class:`BoardStatus`."""
            try:
                statuses = self._engine.board_status()
            except Exception as exc:  # pragma: no cover - engine may be busy
                logger.debug("board_status() failed: %s", exc)
                return
            if not statuses:
                return

            tree = self.query_one("#board_tree", Tree)
            tree.clear()
            root = tree.root
            root.expand()
            for st in statuses:
                self._add_board_node(root, st)

        def _add_board_node(self, root, st: BoardStatus) -> None:
            led = "[green]●[/]" if st.connected else "[red]●[/]"
            label = f"{led} Board {st.index} — {st.model_name or '?'}"
            node = root.add(label, expand=True)
            node.add_leaf(f"handle: {st.handle}")
            node.add_leaf(f"pid: {st.pid}")
            node.add_leaf(f"fw: {st.fpga_fw or '?'}")
            node.add_leaf(
                "temp: "
                f"fpga {st.temp_fpga:.1f}°C · board {st.temp_board:.1f}°C"
            )
            hv_led = "[green]ON[/]" if st.hv_on else "[dim]off[/]"
            node.add_leaf(
                f"HV {hv_led}: {st.hv_vmon:.1f} V / {st.hv_imon:.2f} mA"
            )
            node.add_leaf(f"status reg: 0x{st.status_reg:08X}")

        @staticmethod
        def _board_connection_str(board: object) -> str:
            """Best-effort connection string for a config board entry."""
            for attr in ("Open", "open", "path", "connection", "address"):
                val = getattr(board, attr, None)
                if isinstance(val, str) and val:
                    return val
            return str(board)

        # -- status bar -------------------------------------------------------
        def _update_status_bar(self) -> None:
            state = self.engine_state
            style = _STATE_STYLE.get(state, "white")
            status = self.query_one("#status_bar", Static)
            log_part = f"  |  {self._last_log}" if self._last_log else ""
            status.update(
                f"State: [{style}]{state.name}[/]"
                f"  |  [s] start  [x] stop  [q] quit{log_part}"
            )

        def watch_engine_state(self, _old: AcqState, _new: AcqState) -> None:
            # Reactive hook: refresh the status bar whenever the state changes.
            try:
                self._update_status_bar()
            except Exception:  # pragma: no cover - during teardown
                pass

        # -- engine observers (called on engine threads) ---------------------
        def _on_state_change(self, state: AcqState) -> None:
            self.call_from_thread(self._set_state, state)

        def _set_state(self, state: AcqState) -> None:
            self.engine_state = state

        def _on_error(self, message: str) -> None:
            self.call_from_thread(self._record_log, "error", message)

        def _on_log(self, level: str, message: str) -> None:
            self.call_from_thread(self._record_log, level, message)

        def _record_log(self, level: str, message: str) -> None:
            self._last_log = f"[{level}] {message}"
            self._update_status_bar()
            logger.log(
                {
                    "info": logging.INFO,
                    "warning": logging.WARNING,
                    "error": logging.ERROR,
                }.get(level.lower(), logging.INFO),
                message,
            )

        # -- actions ----------------------------------------------------------
        def action_start_run(self) -> None:
            """Connect / configure (if needed) and start a run in a worker."""
            self.run_worker(
                self._start_run_worker, thread=True, exclusive=False, group="run"
            )

        def _start_run_worker(self) -> None:
            try:
                if self._engine.state in (
                    AcqState.DISCONNECTED,
                    AcqState.ERROR,
                ):
                    self._engine.connect()
                    self._engine.configure(self._config)
                self._run_counter += 1
                self._engine.start_run(self._run_counter)
            except Exception as exc:
                self.call_from_thread(self._record_log, "error", f"start failed: {exc}")
                logger.exception("start_run worker failed")

        def action_stop_run(self) -> None:
            self.run_worker(
                self._stop_run_worker, thread=True, exclusive=False, group="run"
            )

        def _stop_run_worker(self) -> None:
            try:
                self._engine.stop_run()
            except Exception as exc:
                self.call_from_thread(self._record_log, "error", f"stop failed: {exc}")
                logger.exception("stop_run worker failed")

        def action_refresh_now(self) -> None:
            self._refresh_board_tree()

        def action_quit_app(self) -> None:
            """Stop the run and close the engine, then exit cleanly."""
            self.run_worker(
                self._quit_worker, thread=True, exclusive=True, group="quit"
            )

        def _quit_worker(self) -> None:
            try:
                if self._engine.state in (
                    AcqState.RUNNING,
                    AcqState.STARTING,
                    AcqState.STOPPING,
                    AcqState.EMPTYING,
                ):
                    self._engine.stop_run()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("stop_run during quit failed: %s", exc)
            try:
                self._engine.close()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("engine.close() during quit failed: %s", exc)
            self.call_from_thread(self.exit)

    return HydraFersTUI()


def run_tui(
    config_path: str | Path | None = None,
    engine: AcquisitionEngine | None = None,
) -> int:
    """Launch the Textual dashboard (``hydrafers-cli tui``).

    Loads *config_path* (or the bundled default) into a fresh engine unless an
    *engine* is supplied. Always closes the engine on exit. Returns a process
    exit code.
    """
    if engine is None:
        if config_path is None:
            config = default_config()
        else:
            path = Path(config_path)
            if not path.is_file():
                raise FileNotFoundError(f"configuration file not found: {path}")
            config = load_config(path)
        engine = AcquisitionEngine(config)
        owns_engine = True
    else:
        config = getattr(engine, "config", None) or default_config()
        owns_engine = False

    app = build_app(engine, config)
    try:
        app.run()
    finally:
        # The quit action already closes the engine; this is a backstop for an
        # abnormal exit (exception bubbling out of the Textual loop).
        if owns_engine:
            try:
                engine.close()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("engine.close() after TUI exit failed: %s", exc)
    return 0

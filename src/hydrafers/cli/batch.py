"""hydrafers.cli.batch — headless (non-interactive) command-line runners.

Layer (CONTRACT.md §0): depends only on ``hydrafers.core`` and
``hydrafers.config``. No ``pyfers``, no Qt.

This module implements the three non-interactive subcommands described in
CONTRACT.md §5:

    * :func:`run_acquisition`  -> ``hydrafers-cli run ...``
    * :func:`benchmark`        -> ``hydrafers-cli benchmark ...``
    * :func:`convert_config`   -> ``hydrafers-cli convert-config old.txt new.yaml``

All three drive a :class:`hydrafers.core.AcquisitionEngine` purely through its
public API and present progress / results with `rich`. Ctrl-C is handled so the
engine is always stopped and closed cleanly.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path
from queue import Empty
from typing import TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.table import Table

from hydrafers.config import (
    HydraConfig,
    convert_janus_txt,
    default_config,
    load_config,
)
from hydrafers.core import AcqState, AcquisitionEngine, RunStatistics

if TYPE_CHECKING:  # pragma: no cover - typing only
    from queue import Queue

logger = logging.getLogger("hydrafers.cli.batch")

# Poll period for the stats queue when waiting for a stop condition (seconds).
_STATS_POLL_TIMEOUT = 0.25


# ---------------------------------------------------------------------------
# Configuration loading helper
# ---------------------------------------------------------------------------
def load_or_default(config_path: str | Path | None) -> HydraConfig:
    """Load a YAML config from *config_path*, or fall back to the bundled default.

    Returns a validated :class:`hydrafers.config.HydraConfig`. Raises whatever
    :func:`hydrafers.config.load_config` raises on an invalid file so the caller
    can surface a clear error message.
    """
    if config_path is None:
        logger.info("no config given; using bundled default configuration")
        return default_config()
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"configuration file not found: {path}")
    logger.info("loading configuration from %s", path)
    return load_config(path)


# ---------------------------------------------------------------------------
# Stop-condition controller
# ---------------------------------------------------------------------------
class _StopController:
    """Tracks the reason a headless run should terminate.

    A run stops on the first of: duration elapsed, target event count reached,
    the engine leaving the RUNNING/STOPPING states (e.g. a preset stop fired in
    the engine itself), or an interrupt (Ctrl-C / SIGTERM).
    """

    def __init__(
        self,
        duration_s: float | None,
        target_counts: int | None,
    ) -> None:
        self.duration_s = duration_s
        self.target_counts = target_counts
        self._interrupted = threading.Event()
        self.reason: str = "unknown"

    def interrupt(self, reason: str = "interrupted") -> None:
        if not self._interrupted.is_set():
            self.reason = reason
            self._interrupted.set()

    @property
    def interrupted(self) -> bool:
        return self._interrupted.is_set()

    def should_stop(self, elapsed_s: float, total_events: int) -> bool:
        """Return True if any stop condition is met; sets :attr:`reason`."""
        if self._interrupted.is_set():
            return True
        if self.duration_s is not None and elapsed_s >= self.duration_s:
            self.reason = "duration reached"
            return True
        if self.target_counts is not None and total_events >= self.target_counts:
            self.reason = "target counts reached"
            return True
        return False


# ---------------------------------------------------------------------------
# Engine wiring helpers
# ---------------------------------------------------------------------------
def _attach_logging_observers(engine: AcquisitionEngine, console: Console) -> None:
    """Route engine ``on_log`` / ``on_error`` callbacks to the rich console.

    The engine invokes these from its internal threads (CONTRACT.md §4); we only
    print, which is thread-safe enough for a console frontend.
    """

    level_style = {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
    }

    def _on_log(level: str, message: str) -> None:
        style = level_style.get(level.lower(), "white")
        console.print(f"[{style}]\\[{level}][/] {message}")

    def _on_error(message: str) -> None:
        console.print(f"[bold red]\\[engine error][/] {message}")

    engine.on_log = _on_log
    engine.on_error = _on_error


def _drain_latest(stats_q: "Queue[RunStatistics]") -> RunStatistics | None:
    """Return the most recent snapshot in *stats_q*, discarding older ones.

    Blocks up to ``_STATS_POLL_TIMEOUT`` for the first item so the caller does
    not busy-spin; returns ``None`` if no snapshot arrived in that window.
    """
    try:
        latest = stats_q.get(timeout=_STATS_POLL_TIMEOUT)
    except Empty:
        return None
    # Coalesce any further queued snapshots so we always render the freshest.
    while True:
        try:
            latest = stats_q.get_nowait()
        except Empty:
            break
    return latest


def _install_signal_handlers(stop: _StopController) -> "list[tuple[int, object]]":
    """Install SIGINT/SIGTERM handlers that flip the stop controller.

    Returns the list of (signal, previous_handler) pairs so the caller can
    restore them. Falls back gracefully when signals cannot be set (e.g. not on
    the main thread).
    """
    previous: list[tuple[int, object]] = []

    def _handler(signum, _frame):  # noqa: ANN001 - signal handler signature
        name = signal.Signals(signum).name
        stop.interrupt(f"received {name}")

    for sig in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            previous.append((sig, signal.getsignal(sig)))
            signal.signal(sig, _handler)
        except (ValueError, OSError, RuntimeError):
            # Not on the main thread or signal unsupported on this platform.
            logger.debug("could not install handler for signal %s", sig)
    return previous


def _restore_signal_handlers(previous: "list[tuple[int, object]]") -> None:
    for sig, handler in previous:
        try:
            signal.signal(sig, handler)  # type: ignore[arg-type]
        except (ValueError, OSError, RuntimeError):
            pass


# ---------------------------------------------------------------------------
# Live stats table rendering (shared with run + benchmark)
# ---------------------------------------------------------------------------
def _stats_table(stats: RunStatistics | None, *, title: str, state: AcqState) -> Table:
    """Build a compact rich table summarizing a :class:`RunStatistics` snapshot."""
    table = Table(title=title, expand=False)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", justify="right")

    table.add_row("State", str(state.name))
    if stats is None:
        table.add_row("(waiting for first snapshot…)", "")
        return table

    table.add_row("Run number", str(stats.run_number))
    table.add_row("Elapsed", f"{stats.elapsed_s:,.1f} s")
    table.add_row("Total events", f"{stats.total_events:,}")
    table.add_row("Built events", f"{stats.built_events:,}")
    table.add_row("Event rate", f"{stats.event_rate_hz:,.1f} Hz")
    table.add_row("Data volume", f"{_human_bytes(stats.byte_count)}")
    table.add_row("Data rate", f"{stats.data_rate_mbps:,.2f} MB/s")

    if stats.per_board:
        for bidx in sorted(stats.per_board):
            bstats = stats.per_board[bidx]
            table.add_row(f"  board {bidx}", _format_board_stats(bstats))
    return table


def _format_board_stats(bstats: object) -> str:
    """One-line rendering of a per-board :class:`hydrafers.core.BoardStats`.

    Renders the fields defined by ``hydrafers.core.BoardStats`` (CONTRACT.md §4
    per-board rates): event rate, data rate, event count and the lost-event
    counter. Missing attributes are skipped so an evolving stats shape never
    crashes the frontend.
    """
    parts: list[str] = []
    for attr, label, fmt in (
        ("event_rate_hz", "rate", "{:,.1f} Hz"),
        ("data_rate_mbps", "", "{:,.2f} MB/s"),
        ("event_count", "ev", "{:,}"),
        ("lost_events", "lost", "{:,}"),
    ):
        val = getattr(bstats, attr, None)
        if val is None:
            continue
        rendered = fmt.format(val)
        parts.append(f"{label} {rendered}".strip())
    return " · ".join(parts) if parts else str(bstats)


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


# ---------------------------------------------------------------------------
# Core engine run loop (shared by run + benchmark)
# ---------------------------------------------------------------------------
def _run_engine_session(
    *,
    engine: AcquisitionEngine,
    config: HydraConfig,
    run_number: int | None,
    duration_s: float | None,
    target_counts: int | None,
    console: Console,
    live_title: str,
) -> RunStatistics | None:
    """Connect, configure, start, monitor, and stop a run on *engine*.

    Returns the last :class:`RunStatistics` snapshot observed (may be ``None``
    if the engine never emitted one). Always stops and disconnects the engine,
    even on error or interrupt.
    """
    stop = _StopController(duration_s, target_counts)
    previous_handlers = _install_signal_handlers(stop)
    stats_q = engine.stats_queue()
    last_stats: RunStatistics | None = None

    try:
        console.print("[cyan]Connecting to boards…[/]")
        engine.connect()
        console.print("[cyan]Configuring boards…[/]")
        engine.configure(config)

        console.print("[green]Starting acquisition…[/]")
        engine.start_run(run_number)

        start_t = time.monotonic()
        with Live(
            _stats_table(None, title=live_title, state=engine.state),
            console=console,
            refresh_per_second=8,
            transient=False,
        ) as live:
            while True:
                snapshot = _drain_latest(stats_q)
                if snapshot is not None:
                    last_stats = snapshot

                elapsed = (
                    last_stats.elapsed_s
                    if last_stats is not None
                    else time.monotonic() - start_t
                )
                total = last_stats.total_events if last_stats is not None else 0

                live.update(
                    _stats_table(last_stats, title=live_title, state=engine.state)
                )

                if stop.should_stop(elapsed, total):
                    break

                # If the engine itself left the running family (preset stop,
                # error), terminate the loop too.
                cur_state = engine.state
                if cur_state in (AcqState.READY, AcqState.ERROR, AcqState.DISCONNECTED):
                    stop.reason = f"engine state -> {cur_state.name}"
                    break

        console.print(f"[yellow]Stopping run ({stop.reason})…[/]")
        engine.stop_run()
    except KeyboardInterrupt:
        # Belt-and-braces: if a SIGINT slips past the installed handler.
        stop.interrupt("KeyboardInterrupt")
        console.print("[yellow]Interrupted; stopping run…[/]")
        try:
            engine.stop_run()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("stop_run after interrupt failed: %s", exc)
    finally:
        _restore_signal_handlers(previous_handlers)

    return last_stats


# ---------------------------------------------------------------------------
# Subcommand: run
# ---------------------------------------------------------------------------
def run_acquisition(
    config_path: str | Path | None,
    *,
    duration: float | None = None,
    counts: int | None = None,
    output: str | Path | None = None,
    run_number: int | None = None,
    console: Console | None = None,
) -> int:
    """Headless data-taking run (``hydrafers-cli run``).

    Exactly one stop condition is normally given (``duration`` xor ``counts``);
    if neither is given the run continues until Ctrl-C. *output* overrides the
    configured data-file directory when provided.

    Returns a process exit code (0 on success, non-zero on error).
    """
    console = console or Console()
    try:
        config = load_or_default(config_path)
    except Exception as exc:
        console.print(f"[bold red]Failed to load configuration:[/] {exc}")
        return 2

    if output is not None:
        _apply_output_override(config, Path(output), console)

    engine = AcquisitionEngine(config)
    _attach_logging_observers(engine, console)

    title = (
        f"HydraFERS run"
        + (f" #{run_number}" if run_number is not None else "")
    )
    try:
        last = _run_engine_session(
            engine=engine,
            config=config,
            run_number=run_number,
            duration_s=duration,
            target_counts=counts,
            console=console,
            live_title=title,
        )
    except Exception as exc:
        console.print(f"[bold red]Acquisition failed:[/] {exc}")
        logger.exception("run_acquisition failed")
        _safe_close(engine, console)
        return 1

    _print_final_summary(console, last, header="Run complete")
    _safe_close(engine, console)
    return 0


def _apply_output_override(
    config: HydraConfig, output: Path, console: Console
) -> None:
    """Point the configured output directory at *output*.

    The ferslib parameter governing the destination folder is ``DataFilePath``
    (see docs/param_defs_reference.txt). We set it on the config model in the
    most compatible way available, without assuming the internal field name.
    """
    output.mkdir(parents=True, exist_ok=True)
    out_str = str(output)
    applied = False

    # Preferred: a dedicated output-files sub-model with a data_file_path field.
    out_files = getattr(config, "output_files", None)
    if out_files is not None:
        for field in ("DataFilePath", "data_file_path", "path"):
            if hasattr(out_files, field):
                try:
                    setattr(out_files, field, out_str)
                    applied = True
                    break
                except Exception:  # pragma: no cover - pydantic frozen, etc.
                    continue

    # Fallback: a top-level attribute on the config model.
    if not applied:
        for field in ("DataFilePath", "data_file_path"):
            if hasattr(config, field):
                try:
                    setattr(config, field, out_str)
                    applied = True
                    break
                except Exception:  # pragma: no cover
                    continue

    if applied:
        console.print(f"[cyan]Output directory:[/] {out_str}")
    else:
        console.print(
            "[yellow]Warning:[/] could not apply --output override to the "
            "configuration model; using the configured DataFilePath instead."
        )


# ---------------------------------------------------------------------------
# Subcommand: benchmark
# ---------------------------------------------------------------------------
def benchmark(
    config_path: str | Path | None,
    *,
    duration: float = 30.0,
    console: Console | None = None,
) -> int:
    """Throughput benchmark (``hydrafers-cli benchmark``).

    Runs the engine for *duration* seconds and reports events/s, MB/s, and the
    drop counter taken from the engine's :class:`RunStatistics`. The interactive
    table is suppressed in favour of a concise final report so timing output is
    not polluted by frequent redraws.

    Returns a process exit code.
    """
    console = console or Console()
    try:
        config = load_or_default(config_path)
    except Exception as exc:
        console.print(f"[bold red]Failed to load configuration:[/] {exc}")
        return 2

    engine = AcquisitionEngine(config)
    _attach_logging_observers(engine, console)

    stop = _StopController(duration_s=duration, target_counts=None)
    previous_handlers = _install_signal_handlers(stop)
    stats_q = engine.stats_queue()
    last_stats: RunStatistics | None = None
    wall_start = 0.0
    wall_elapsed = 0.0

    try:
        console.print("[cyan]Connecting to boards…[/]")
        engine.connect()
        console.print("[cyan]Configuring boards…[/]")
        engine.configure(config)

        console.print(
            f"[green]Benchmark: acquiring for {duration:g} s "
            "(no live rendering)…[/]"
        )
        engine.start_run(None)
        wall_start = time.monotonic()

        while True:
            snapshot = _drain_latest(stats_q)
            if snapshot is not None:
                last_stats = snapshot
            wall_elapsed = time.monotonic() - wall_start
            elapsed = (
                last_stats.elapsed_s if last_stats is not None else wall_elapsed
            )
            total = last_stats.total_events if last_stats is not None else 0
            if stop.should_stop(elapsed, total):
                break
            cur_state = engine.state
            if cur_state in (AcqState.READY, AcqState.ERROR, AcqState.DISCONNECTED):
                stop.reason = f"engine state -> {cur_state.name}"
                break

        wall_elapsed = time.monotonic() - wall_start
        console.print(f"[yellow]Stopping run ({stop.reason})…[/]")
        engine.stop_run()
        # Drain one last snapshot post-stop for the most complete totals.
        final = _drain_latest(stats_q)
        if final is not None:
            last_stats = final
    except KeyboardInterrupt:
        stop.interrupt("KeyboardInterrupt")
        if wall_start:
            wall_elapsed = time.monotonic() - wall_start
        try:
            engine.stop_run()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("stop_run after interrupt failed: %s", exc)
    except Exception as exc:
        console.print(f"[bold red]Benchmark failed:[/] {exc}")
        logger.exception("benchmark failed")
        _restore_signal_handlers(previous_handlers)
        _safe_close(engine, console)
        return 1
    finally:
        _restore_signal_handlers(previous_handlers)

    _print_benchmark_report(console, last_stats, wall_elapsed, engine)
    _safe_close(engine, console)
    return 0


def _print_benchmark_report(
    console: Console,
    stats: RunStatistics | None,
    wall_elapsed: float,
    engine: AcquisitionEngine,
) -> None:
    """Print the final throughput report for a benchmark."""
    table = Table(title="Benchmark results", expand=False)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", justify="right")

    if stats is None:
        table.add_row("(no statistics were produced)", "")
        console.print(table)
        return

    elapsed = stats.elapsed_s if stats.elapsed_s > 0 else wall_elapsed
    elapsed = max(elapsed, 1e-9)

    avg_event_rate = stats.total_events / elapsed
    avg_mbps = (stats.byte_count / (1024.0 * 1024.0)) / elapsed
    drops = _extract_drops(stats)

    table.add_row("Wall elapsed", f"{wall_elapsed:,.2f} s")
    table.add_row("Engine elapsed", f"{stats.elapsed_s:,.2f} s")
    table.add_row("Total events", f"{stats.total_events:,}")
    table.add_row("Built events", f"{stats.built_events:,}")
    table.add_row("Average events/s", f"{avg_event_rate:,.1f}")
    table.add_row("Instant events/s", f"{stats.event_rate_hz:,.1f}")
    table.add_row("Total data", _human_bytes(stats.byte_count))
    table.add_row("Average MB/s", f"{avg_mbps:,.2f}")
    table.add_row("Instant MB/s", f"{stats.data_rate_mbps:,.2f}")
    table.add_row(
        "Dropped / busy",
        f"{drops:,}" if drops is not None else "n/a",
    )
    console.print(table)


def _extract_drops(stats: RunStatistics) -> int | None:
    """Find the readout drop / lost-event counter on a stats snapshot.

    ``hydrafers.core.RunStatistics`` exposes lost events per board via
    ``per_board[i].lost_events`` (each a :class:`hydrafers.core.BoardStats`);
    the benchmark reports their sum. A top-level scalar counter
    (``dropped_events`` etc.) is probed first for forward-compatibility should
    the engine expose an aggregate directly. Returns ``None`` only if no drop
    information is available at all.
    """
    for attr in ("dropped_events", "dropped", "drops", "busy", "busy_count"):
        val = getattr(stats, attr, None)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return int(val)

    per_board = getattr(stats, "per_board", None)
    if per_board:
        total = 0
        found = False
        for bstats in per_board.values():
            lost = getattr(bstats, "lost_events", None)
            if isinstance(lost, (int, float)) and not isinstance(lost, bool):
                total += int(lost)
                found = True
        if found:
            return total
    return None


# ---------------------------------------------------------------------------
# Subcommand: convert-config
# ---------------------------------------------------------------------------
def convert_config(
    txt_path: str | Path,
    yaml_path: str | Path,
    *,
    console: Console | None = None,
) -> int:
    """Convert a legacy Janus ``.txt`` config to HydraFERS YAML.

    Thin wrapper over :func:`hydrafers.config.convert_janus_txt` (CONTRACT.md §2)
    with friendly console output. Returns a process exit code.
    """
    console = console or Console()
    src = Path(txt_path)
    dst = Path(yaml_path)

    if not src.is_file():
        console.print(f"[bold red]Source file not found:[/] {src}")
        return 2

    try:
        cfg = convert_janus_txt(src, dst)
    except Exception as exc:
        console.print(f"[bold red]Conversion failed:[/] {exc}")
        logger.exception("convert_config failed")
        return 1

    n_boards = len(getattr(cfg, "boards", []) or [])
    console.print(
        f"[green]Converted[/] [cyan]{src}[/] -> [cyan]{dst}[/] "
        f"({n_boards} board(s))."
    )
    return 0


# ---------------------------------------------------------------------------
# Shared output / cleanup helpers
# ---------------------------------------------------------------------------
def _print_final_summary(
    console: Console, stats: RunStatistics | None, *, header: str
) -> None:
    """Print a final run summary table."""
    console.print(_stats_table(stats, title=header, state=AcqState.READY))


def _safe_close(engine: AcquisitionEngine, console: Console) -> None:
    """Close the engine, swallowing and logging any shutdown error.

    Safe to call from an ``atexit`` or error path (CONTRACT.md §4: ``close``
    is the full shutdown and must be safe to call repeatedly).
    """
    try:
        engine.close()
    except Exception as exc:  # pragma: no cover - defensive
        console.print(f"[yellow]Warning during engine shutdown:[/] {exc}")
        logger.warning("engine.close() raised: %s", exc)

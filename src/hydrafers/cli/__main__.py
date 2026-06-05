"""hydrafers.cli.__main__ — command-line entry point and subcommand dispatcher.

Layer (CONTRACT.md §0): depends only on ``hydrafers.core`` / ``hydrafers.config``
(transitively, via :mod:`hydrafers.cli.batch` and :mod:`hydrafers.cli.app`). No
``pyfers``, no Qt.

Run as ``python -m hydrafers.cli`` or via the ``hydrafers-cli`` console script.

Subcommands (CONTRACT.md §5):

    run             headless data-taking run
        --config PATH  --duration SECONDS | --counts N
        --output DIR   --run-number N
    benchmark       throughput test (events/s, MB/s, drops)
        --config PATH  --duration SECONDS
    convert-config  legacy Janus .txt -> HydraFERS YAML
        OLD.txt NEW.yaml
    tui             launch the Textual dashboard
        --config PATH
"""

from __future__ import annotations

import argparse
import logging
import sys

from rich.console import Console

_PROG = "hydrafers-cli"
_DESCRIPTION = (
    "HydraFERS headless / TUI frontend — drive the acquisition engine without "
    "the desktop GUI."
)


def _add_common_logging_args(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``-v/--verbose`` and ``--quiet`` flags to a subparser."""
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="increase log verbosity (repeat for more: -v INFO, -vv DEBUG)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress informational logging (errors still shown)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(prog=_PROG, description=_DESCRIPTION)
    parser.set_defaults(func=None)
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # --- run -------------------------------------------------------------
    p_run = sub.add_parser(
        "run",
        help="headless data-taking run",
        description="Connect, configure, and acquire data until a stop "
        "condition is met (duration, counts, or Ctrl-C).",
    )
    p_run.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="YAML configuration file (default: bundled default config)",
    )
    stop_grp = p_run.add_mutually_exclusive_group()
    stop_grp.add_argument(
        "--duration",
        type=float,
        metavar="SECONDS",
        default=None,
        help="stop after this many seconds",
    )
    stop_grp.add_argument(
        "--counts",
        type=int,
        metavar="N",
        default=None,
        help="stop after acquiring N events",
    )
    p_run.add_argument(
        "--output",
        metavar="DIR",
        default=None,
        help="output directory for data files (overrides DataFilePath)",
    )
    p_run.add_argument(
        "--run-number",
        type=int,
        metavar="N",
        default=None,
        help="run number to tag the acquisition (default: engine-assigned)",
    )
    _add_common_logging_args(p_run)
    p_run.set_defaults(func=_cmd_run)

    # --- benchmark -------------------------------------------------------
    p_bench = sub.add_parser(
        "benchmark",
        help="throughput benchmark (events/s, MB/s, drops)",
        description="Acquire for a fixed duration and report sustained "
        "throughput taken from the engine statistics.",
    )
    p_bench.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="YAML configuration file (default: bundled default config)",
    )
    p_bench.add_argument(
        "--duration",
        type=float,
        metavar="SECONDS",
        default=30.0,
        help="benchmark duration in seconds (default: 30)",
    )
    _add_common_logging_args(p_bench)
    p_bench.set_defaults(func=_cmd_benchmark)

    # --- convert-config --------------------------------------------------
    p_conv = sub.add_parser(
        "convert-config",
        help="convert a legacy Janus .txt config to HydraFERS YAML",
        description="One-shot migration of an old Janus_Config.txt to the new "
        "YAML format.",
    )
    p_conv.add_argument("input", metavar="old.txt", help="legacy Janus .txt config")
    p_conv.add_argument("output", metavar="new.yaml", help="destination YAML file")
    _add_common_logging_args(p_conv)
    p_conv.set_defaults(func=_cmd_convert)

    # --- tui -------------------------------------------------------------
    p_tui = sub.add_parser(
        "tui",
        help="launch the interactive Textual dashboard",
        description="Full-screen terminal dashboard with a board tree, live "
        "stats table, sparklines, and start/stop controls.",
    )
    p_tui.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="YAML configuration file (default: bundled default config)",
    )
    _add_common_logging_args(p_tui)
    p_tui.set_defaults(func=_cmd_tui)

    return parser


def _configure_logging(args: argparse.Namespace) -> None:
    """Set up stdlib logging for the ``hydrafers`` logger hierarchy.

    CONTRACT.md §8: logging via stdlib ``logging``; no ``print`` in library
    code. The CLI is an edge, so it configures the root handler here and lets
    rich own the user-facing console output.
    """
    if getattr(args, "quiet", False):
        level = logging.ERROR
    else:
        verbose = getattr(args, "verbose", 0)
        level = {0: logging.WARNING, 1: logging.INFO}.get(verbose, logging.DEBUG)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("hydrafers").setLevel(level)


# ---------------------------------------------------------------------------
# Subcommand handlers (thin adapters over hydrafers.cli.batch / .app)
# ---------------------------------------------------------------------------
def _cmd_run(args: argparse.Namespace, console: Console) -> int:
    from hydrafers.cli.batch import run_acquisition

    return run_acquisition(
        args.config,
        duration=args.duration,
        counts=args.counts,
        output=args.output,
        run_number=args.run_number,
        console=console,
    )


def _cmd_benchmark(args: argparse.Namespace, console: Console) -> int:
    from hydrafers.cli.batch import benchmark

    return benchmark(args.config, duration=args.duration, console=console)


def _cmd_convert(args: argparse.Namespace, console: Console) -> int:
    from hydrafers.cli.batch import convert_config

    return convert_config(args.input, args.output, console=console)


def _cmd_tui(args: argparse.Namespace, console: Console) -> int:
    from hydrafers.cli.app import run_tui

    try:
        return run_tui(args.config)
    except RuntimeError as exc:
        # e.g. Textual not installed.
        console.print(f"[bold red]Cannot launch TUI:[/] {exc}")
        return 2
    except FileNotFoundError as exc:
        console.print(f"[bold red]{exc}[/]")
        return 2


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def tui_main(argv: list[str] | None = None) -> int:
    """Direct entry point for the ``hydrafers-tui`` console script."""
    return main(["tui", *(argv or [])])


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected subcommand.

    Returns a process exit code. Suitable as the ``hydrafers-cli`` console
    script target and invoked by ``python -m hydrafers.cli``.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.func is None:
        parser.print_help()
        return 1

    _configure_logging(args)
    console = Console()
    try:
        return args.func(args, console)
    except KeyboardInterrupt:
        # Handlers stop/close the engine themselves; this is the outer net so
        # an interrupt during setup still yields a clean, conventional exit.
        console.print("\n[yellow]Interrupted.[/]")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

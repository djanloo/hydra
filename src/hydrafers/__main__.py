"""hydrafers.__main__ — top-level dispatcher for ``python -m hydrafers``.

Layer: top-level package glue (CONTRACT.md §0). Imports only from
``hydrafers.cli`` or ``hydrafers.gui`` (never both) based on the chosen mode.
Emits no ``print`` outside its own ``if __name__ == '__main__'`` guard; all
logging is via stdlib ``logging``.

Usage::

    python -m hydrafers              # default: launches the GUI (same as --gui)
    python -m hydrafers --gui        # launch PySide6 desktop GUI
    python -m hydrafers --cli [args] # delegate to hydrafers.cli (headless / TUI)
    python -m hydrafers --version    # print version and exit
    python -m hydrafers --help       # print this help and exit

The ``--cli`` flag accepts any additional arguments that are forwarded verbatim
to ``hydrafers.cli.__main__.main``.  Example::

    python -m hydrafers --cli run --config run.yaml --duration 3600
    python -m hydrafers --cli tui --config run.yaml
    python -m hydrafers --cli convert-config old.txt new.yaml
"""

from __future__ import annotations

import argparse
import sys

from hydrafers import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser for ``python -m hydrafers``."""
    parser = argparse.ArgumentParser(
        prog="hydrafers",
        description=(
            "HydraFERS — CAEN FERS / Janus DAQ software renewal.\n\n"
            "  python -m hydrafers          # launch GUI (default)\n"
            "  python -m hydrafers --gui    # launch GUI explicitly\n"
            "  python -m hydrafers --cli … # headless / TUI mode (see --cli --help)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=True,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"hydrafers {__version__}",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--gui",
        action="store_true",
        default=False,
        help="launch the PySide6 desktop GUI (default when no mode flag is given)",
    )
    mode_group.add_argument(
        "--cli",
        nargs=argparse.REMAINDER,
        metavar="args",
        default=None,
        help=(
            "delegate to hydrafers.cli; all following arguments are forwarded "
            "verbatim (e.g. --cli run --config run.yaml --duration 3600)"
        ),
    )
    return parser


def _launch_gui() -> int:
    """Import and run the PySide6 GUI frontend.

    Returns a process exit code. Separated into its own function so that
    import errors (e.g. PySide6 not installed) are reported cleanly.
    """
    try:
        from hydrafers.gui.__main__ import main as gui_main  # type: ignore[import]
    except ImportError as exc:
        print(
            f"[hydrafers] Cannot import hydrafers.gui: {exc}\n"
            "Install the GUI extras:  pip install hydrafers[gui]\n"
            "Or run the CLI instead:  python -m hydrafers --cli --help",
            file=sys.stderr,
        )
        return 2
    return gui_main()


def _launch_cli(cli_args: list[str]) -> int:
    """Import and run the CLI / TUI frontend with the given argument list.

    Returns a process exit code. Separated so that import errors are reported
    cleanly and the caller keeps ownership of sys.exit.
    """
    try:
        from hydrafers.cli.__main__ import main as cli_main
    except ImportError as exc:
        print(
            f"[hydrafers] Cannot import hydrafers.cli: {exc}\n"
            "Install the CLI extras:  pip install hydrafers[cli]",
            file=sys.stderr,
        )
        return 2
    return cli_main(cli_args)


def main(argv: list[str] | None = None) -> int:
    """Parse the top-level arguments and dispatch to the selected frontend.

    Parameters
    ----------
    argv:
        Argument list (defaults to ``sys.argv[1:]`` when ``None``).

    Returns
    -------
    int
        Process exit code (0 = success, non-zero = error).
    """
    # ``parse_known_args`` lets trailing ``--cli`` arguments pass through without
    # raising an error — they are forwarded verbatim to ``hydrafers.cli``.
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cli is not None:
        # ``--cli`` flag present; delegate to the CLI dispatcher.
        return _launch_cli(list(args.cli))

    # Default (no flag, or --gui): launch the desktop GUI.
    return _launch_gui()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""hydrafers.__main__ — top-level entry point for ``python -m hydrafers`` / ``hydrafers``.

Usage::

    hydrafers              # launch the Qt desktop GUI (default)
    hydrafers gui          # same
    hydrafers tui          # Textual TUI dashboard
    hydrafers run …        # headless acquisition
    hydrafers benchmark …  # throughput test
    hydrafers convert-config old.txt new.yaml
    hydrafers --version
"""

from __future__ import annotations

import sys

from hydrafers import __version__


def _launch_gui() -> int:
    try:
        from hydrafers.gui.__main__ import main as gui_main
    except ImportError as exc:
        print(
            f"Cannot import hydrafers.gui: {exc}\n"
            "Install GUI extras:  pip install 'hydrafers[gui]'",
            file=sys.stderr,
        )
        return 2
    return gui_main()


def _launch_cli(argv: list[str]) -> int:
    try:
        from hydrafers.cli.__main__ import main as cli_main
    except ImportError as exc:
        print(
            f"Cannot import hydrafers.cli: {exc}\n"
            "Install CLI extras:  pip install 'hydrafers[cli]'",
            file=sys.stderr,
        )
        return 2
    return cli_main(argv)


_CLI_SUBCOMMANDS = {"tui", "run", "benchmark", "convert-config"}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in ("--version", "-V"):
        print(f"hydrafers {__version__}")
        return 0

    if not args or args[0] in ("gui", "--gui"):
        return _launch_gui()

    if args[0] in _CLI_SUBCOMMANDS:
        return _launch_cli(args)

    # Unknown first arg — let the CLI parser produce a proper error / help.
    return _launch_cli(args)


if __name__ == "__main__":
    sys.exit(main())

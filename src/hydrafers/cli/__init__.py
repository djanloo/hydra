"""hydrafers.cli — headless / TUI frontend for HydraFERS.

Layer (CONTRACT.md §0): this package depends ONLY on ``hydrafers.core`` and
``hydrafers.config``. It MUST NOT import ``pyfers`` directly, nor any Qt module.
It is one of two interchangeable frontends (the other being ``hydrafers.gui``)
over the identical :class:`hydrafers.core.AcquisitionEngine` API.

Public surface:
    * :func:`hydrafers.cli.batch.run_acquisition` — headless data-taking runner.
    * :func:`hydrafers.cli.batch.benchmark` — throughput benchmark.
    * :func:`hydrafers.cli.batch.convert_config` — legacy ``.txt`` -> YAML.
    * :func:`hydrafers.cli.app.run_tui` — launch the Textual dashboard.
    * :func:`hydrafers.cli.__main__.main` — argparse subcommand dispatcher and
      the ``hydrafers-cli`` console-script entry point.

See CONTRACT.md §5 for the binding command-line interface.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``hydrafers-cli`` console script.

    Thin re-export of :func:`hydrafers.cli.__main__.main` so that
    ``hydrafers.cli:main`` is a valid console-script target.
    """
    from hydrafers.cli.__main__ import main as _main

    return _main(argv)

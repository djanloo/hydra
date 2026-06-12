"""Multi-board orchestration for the FERS SDK.

Role: coordinate a set of :class:`~pyfers.board.Board` objects (and the
concentrator they may hang off) as one logical acquisition system. ``System``
owns the control-plane ergonomics (open all / configure all / start / stop /
flush / close) and exposes :attr:`handles` so a high-rate consumer (the
hydrafers engine) can drive the data-plane directly via
``pyferslib.drain_events``. ``System.events()`` is the SDK-friendly data path:
it drains batches and yields typed :mod:`pyfers.events` dataclasses.

Layer: ``pyfers`` (CONTRACT.md section 1b). Imports ``pyferslib`` ONLY (plus the
sibling ``pyfers`` modules). Usable standalone:

    with pyfers.System.open("eth:192.168.50.3") as s:
        s.boards[0].hv.vbias = 62.5
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

import pyferslib

from . import events as _events
from .board import Board
from .enums import BoardFamily, SortMode, StartMode
from .errors import ConfigError

# Valid configure-mode strings accepted by :meth:`System.configure`.
_CFG_MODES = ("hard", "soft")


class System:
    """A collection of boards driven as one acquisition system.

    Construct directly from :class:`Board` objects, or use the :meth:`open` /
    :meth:`from_config` classmethods. The boards may be in any open/closed state
    at construction; :meth:`open` opens any that are still closed.
    """

    def __init__(self, boards: list[Board]) -> None:
        if not boards:
            raise ConfigError("System requires at least one board")
        self._boards: list[Board] = list(boards)

    # ------------------------------------------------------------------ factories
    @classmethod
    def open(cls, *paths: str) -> "System":
        """Build a :class:`System` from connection ``paths`` and open every board.

        On any failure all already-opened boards are closed before re-raising,
        so a partially-opened system never leaks handles.
        """
        if not paths:
            raise ConfigError("System.open requires at least one board path")
        boards = [Board(path) for path in paths]
        system = cls(boards)
        opened: list[Board] = []
        try:
            for board in boards:
                board.open()
                opened.append(board)
            # Enforce a homogeneous fleet: ferslib forbids mixing 5202 and 5203
            # in one running system (see docs/A5203_INTEGRATION_STUDY.md §3).
            system._check_homogeneous(opened)
        except Exception:
            for board in opened:
                try:
                    board.close()
                except Exception:  # pragma: no cover - best-effort cleanup
                    pass
            raise
        return system

    @classmethod
    def from_config(cls, cfg: Any) -> "System":
        """Build a :class:`System` from a config object (duck-typed).

        Accepts anything exposing connection paths. In order of preference:
          * ``cfg.board_paths()`` -> ``list[str]`` (``HydraConfig`` API);
          * ``cfg.boards`` whose items carry ``.open`` / ``.path`` / ``.Open``
            (or dict keys of the same names).

        Boards are opened immediately, matching :meth:`open`.
        """
        paths = cls._extract_paths(cfg)
        if not paths:
            raise ConfigError("config provided no board connection paths")
        return cls.open(*paths)

    @staticmethod
    def _extract_paths(cfg: Any) -> list[str]:
        """Pull a list of connection paths out of a duck-typed config object."""
        getter = getattr(cfg, "board_paths", None)
        if callable(getter):
            return [str(p) for p in getter() if p]

        boards = getattr(cfg, "boards", None)
        if not boards:
            return []
        paths: list[str] = []
        for board in boards:
            if isinstance(board, dict):
                path = board.get("open") or board.get("path") or board.get("Open")
            else:
                path = (
                    getattr(board, "open", None)
                    or getattr(board, "path", None)
                    or getattr(board, "Open", None)
                )
            if path:
                paths.append(str(path))
        return paths

    # ------------------------------------------------------------------ props
    @property
    def boards(self) -> list[Board]:
        """The boards in this system (a copy of the internal list)."""
        return list(self._boards)

    @property
    def handles(self) -> list[int]:
        """Raw ferslib handles of every open board, for the data-plane.

        Passed verbatim to ``pyferslib.drain_events`` / ``start_acquisition`` /
        ``stop_acquisition``. Closed boards are skipped.
        """
        return [b.handle for b in self._boards if b.is_open]

    @property
    def family(self) -> "BoardFamily | None":
        """The board family of this (homogeneous) system, or ``None`` if unknown.

        Returns the family shared by all boards that report one. Raises
        :class:`ConfigError` if open boards report conflicting families (which
        :meth:`open` already prevents, but a re-check here keeps callers honest).
        """
        return self._check_homogeneous(
            [b for b in self._boards if b.is_open]
        )

    @staticmethod
    def _check_homogeneous(boards: list[Board]) -> "BoardFamily | None":
        """Return the single family shared by *boards*, or raise on a mix.

        Boards that cannot report a family (e.g. concentrator endpoints) are
        ignored. ``None`` is returned only when no board reports a family.
        """
        families: dict[BoardFamily, list[str]] = {}
        for board in boards:
            fam = board.family
            if fam is None:
                continue
            families.setdefault(fam, []).append(board.path)
        if len(families) > 1:
            detail = "; ".join(
                f"{fam.name} ({fam.value}): {paths}" for fam, paths in families.items()
            )
            raise ConfigError(
                "mixed FERS board families in one system are not supported "
                f"(ferslib forbids it): {detail}. Open one homogeneous system "
                "per family instead."
            )
        return next(iter(families), None)

    # ------------------------------------------------------------------ config
    def configure(
        self,
        params: Iterable[tuple[int, str, str]],
        mode: str = "hard",
    ) -> None:
        """Apply ``(board_index, name, value)`` params then configure each board.

        ``params`` is typically ``HydraConfig.to_ferslib_params()``. Convention
        (CONTRACT.md section 1b / 4): a ``board_index`` of 0 applies to *all*
        boards (global params), any other index targets that single board. The
        special ``"Open"`` pseudo-param is a connection path consumed at open
        time and is never forwarded to ``set_param``.
        """
        key = str(mode).strip().lower()
        if key not in _CFG_MODES:
            raise ConfigError(f"configure mode {mode!r} must be 'hard' or 'soft'")

        nboards = len(self._boards)
        for board_index, name, value in params:
            if name == "Open":
                continue
            if board_index == 0:
                targets = self._boards
            else:
                if board_index < 0 or board_index >= nboards:
                    raise ConfigError(
                        f"param {name!r} targets board {board_index} but the "
                        f"system has {nboards} board(s)"
                    )
                targets = [self._boards[board_index]]
            for board in targets:
                board.set_param(str(name), str(value))

        for board in self._boards:
            board.configure(key)

    def init_readout(self, sort: SortMode = SortMode.DISABLED) -> None:
        """Initialize readout buffers on every board with the given sort mode."""
        for board in self._boards:
            board.init_readout(sort)

    # ------------------------------------------------------------------ run control
    def start_run(
        self,
        start_mode: StartMode = StartMode.ASYNC,
        run_number: int = 0,
    ) -> None:
        """Start acquisition on all boards (``pyferslib.start_acquisition``)."""
        pyferslib.start_acquisition(
            self.handles, start_mode.to_ferslib_int(), int(run_number)
        )

    def stop_run(
        self,
        start_mode: StartMode = StartMode.ASYNC,
        run_number: int = 0,
    ) -> None:
        """Stop acquisition on all boards (``pyferslib.stop_acquisition``)."""
        pyferslib.stop_acquisition(
            self.handles, start_mode.to_ferslib_int(), int(run_number)
        )

    # ------------------------------------------------------------------ data plane
    def events(self, max_batch: int = 256) -> Iterator[Any]:
        """Yield typed events drained from all boards.

        Pulls up to ``max_batch`` raw ``(board, dtq, event)`` tuples per call to
        ``pyferslib.drain_events`` and decodes each into a
        :mod:`pyfers.events` dataclass. The generator runs until a drain returns
        an empty batch, at which point it stops (call again to resume).

        The end-of-offline-reprocessing sentinel
        (``board == -1`` / ``dtq == RAWDATA_REPROCESS_FINISHED``) is treated as a
        clean end-of-stream and terminates the generator without yielding.
        """
        batch = max(1, int(max_batch))
        handles = self.handles
        while True:
            raw_batch = pyferslib.drain_events(handles, batch)
            if not raw_batch:
                return
            for board, dtq, raw in raw_batch:
                if board == -1 and dtq == pyferslib.RAWDATA_REPROCESS_FINISHED:
                    return
                if raw is None:
                    continue
                yield _events.decode(board, dtq, raw)
            # A short batch means the boards are drained for now: stop so the
            # caller controls polling cadence rather than busy-looping here.
            if len(raw_batch) < batch:
                return

    def flush(self) -> None:
        """Discard stale buffered data on every board (``flush_data``)."""
        for board in self._boards:
            if board.is_open:
                board.flush_data()

    # ------------------------------------------------------------------ teardown
    def close(self) -> None:
        """Close every board handle. Best-effort and idempotent."""
        for board in self._boards:
            try:
                board.close()
            except Exception:  # pragma: no cover - best-effort shutdown
                pass

    # ------------------------------------------------------------------ context
    def __enter__(self) -> "System":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def __len__(self) -> int:  # pragma: no cover - convenience
        return len(self._boards)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"System(boards={[b.path for b in self._boards]!r})"


__all__ = ["System"]

"""Legacy Janus_Config.txt <-> HydraConfig conversion (CONTRACT.md §2).

Layer: ``hydrafers.config`` -- pure Python. NO pyfers/Qt import.

Two directions, both **board-family aware** (A5202 vs A5203 -- see
``docs/A5203_INTEGRATION_STUDY.md`` §2.2):
    * :func:`render_legacy_txt` -- serialize a :class:`BaseHydraConfig` to the
      legacy text format (used by :meth:`BaseHydraConfig.to_legacy_txt`).
    * :func:`convert_janus_txt` -- parse a legacy ``Janus_Config.txt`` into a
      validated config (family auto-detected from the parameter names present)
      and optionally write it as YAML.

Legacy line grammar (per ``paramparser.c``):
    ``Name[brd][ch] value   # optional comment``
  where the ``[brd]`` and ``[ch]`` index suffixes are optional. ``Open`` always
  carries a board index (``Open[0]``). Section banners are comment lines and are
  advisory only -- params are keyed by NAME, so parsing is order-independent.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pydantic import ValidationError

from hydrafers.config.schema import (
    FAMILY_5202,
    FAMILY_5203,
    NUM_CHANNELS,
    AcqModeConfig,
    BaseHydraConfig,
    BoardConfig,
    DiscrConfig,
    HVBiasConfig,
    HydraConfig,
    OutputFilesConfig,
    RunCtrlConfig,
    SpectroscopyConfig,
    TestProbeConfig,
    _scalar_to_str,
)
from hydrafers.config.schema_5203 import (
    NUM_CHANNELS_5203,
    AcqMode5203Config,
    Adapters5203Config,
    Board5203Config,
    DataAnalysis5203Config,
    HydraConfig5203,
    OutputFiles5203Config,
    RunCtrl5203Config,
    TDCConfig,
)

logger = logging.getLogger("hydrafers.config.converter")

# Width of the name column in the emitted legacy file (matches the example).
_NAME_COL = 35


def _build_lenient(model, kwargs: dict, *, what: str):
    """Build a pydantic *model* from *kwargs*, dropping fields that fail to validate.

    Legacy ``Janus_Config.txt`` files (especially the A5203 GUI output) can carry
    firmware-specific combo tokens (e.g. ``DigitalProbe0=ACQCTRL_6``) that are not
    in the documented option list, or otherwise out-of-range values. On import we
    must not abort the whole conversion for one stray value: invalid fields are
    dropped (the field falls back to its schema default) and logged. Hand-authored
    YAML stays strictly validated -- this leniency applies to legacy import only.
    """
    attempt = dict(kwargs)
    for _ in range(len(kwargs) + 1):
        try:
            return model(**attempt)
        except ValidationError as exc:
            bad = {str(e["loc"][0]) for e in exc.errors() if e.get("loc")}
            bad &= set(attempt)
            if not bad:
                raise
            logger.warning(
                "legacy import: %s field(s) %s invalid; dropped (using defaults)",
                what, sorted(bad),
            )
            for name in bad:
                attempt.pop(name, None)
    return model()  # pragma: no cover - all fields dropped

# Per-family global section models, mapped to their legacy banner name. The
# banner order here is the emission order in the legacy file.
_GLOBAL_SECTIONS_5202: tuple[tuple[str, str], ...] = (
    ("HV_bias", "hv_bias"),
    ("RunCtrl", "run_ctrl"),
    ("OutputFiles", "output_files"),
    ("AcqMode", "acq_mode"),
    ("Discr", "discr"),
    ("Spectroscopy", "spectroscopy"),
    ("Test-Probe", "test_probe"),
)
_GLOBAL_SECTIONS_5203: tuple[tuple[str, str], ...] = (
    ("RunCtrl", "run_ctrl"),
    ("OutputFiles", "output_files"),
    ("AcqMode", "acq_mode"),
    ("TDC", "tdc"),
    ("DataAnalysis", "data_analysis"),
    ("Adapters", "adapters"),
)

# Per-family (global section model class, config attr) pairs, for parse routing.
_SECTION_MODELS_5202 = (
    (HVBiasConfig, "hv_bias"),
    (RunCtrlConfig, "run_ctrl"),
    (OutputFilesConfig, "output_files"),
    (AcqModeConfig, "acq_mode"),
    (DiscrConfig, "discr"),
    (SpectroscopyConfig, "spectroscopy"),
    (TestProbeConfig, "test_probe"),
)
_SECTION_MODELS_5203 = (
    (RunCtrl5203Config, "run_ctrl"),
    (OutputFiles5203Config, "output_files"),
    (AcqMode5203Config, "acq_mode"),
    (TDCConfig, "tdc"),
    (DataAnalysis5203Config, "data_analysis"),
    (Adapters5203Config, "adapters"),
)

# Short per-parameter trailing comments for the emitted legacy file (a hint only).
_COMMENTS: dict[str, str] = {
    "HV_Vbias": "Bias voltage (common to all channels)",
    "HV_Imax": "Max current provided by the HV.",
    "HV_Adjust_Range": "DAC range for the individual HV adjust. Options: 4.5, 2.5, DISABLED",
    "TempSensType": "Temperature Sensor Type. Options: TMP37, LM94021_G11, LM94021_G00",
    "AcquisitionMode": "Acquisition mode",
    "MeasMode": "Time measurement mode (5203)",
    "DataFilePath": "Destination folder to save the output files",
    "OF_MaxSize": "Max size of List files",
}


# Legacy parameter-name aliases -> canonical schema field name (5202 legacy file
# uses Trg_HoldOff for what param_defs now calls Hit_HoldOff).
_LEGACY_NAME_ALIASES: dict[str, str] = {
    "Trg_HoldOff": "Hit_HoldOff",
}


def _fmt_line(name: str, value: str, comment: str | None = None) -> str:
    """Format a single ``Name  value  # comment`` legacy line."""
    base = f"{name:<{_NAME_COL}}{value}"
    if comment:
        return f"{base:<{_NAME_COL + 24}}# {comment}"
    return base


def _banner(title: str) -> str:
    rule = "# " + "-" * 88
    return f"{rule}\n# {title}\n{rule}"


def _global_sections_for(cfg: BaseHydraConfig) -> tuple[tuple[str, str], ...]:
    return (
        _GLOBAL_SECTIONS_5203
        if int(getattr(cfg, "board_family", FAMILY_5202)) == FAMILY_5203
        else _GLOBAL_SECTIONS_5202
    )


def render_legacy_txt(cfg: BaseHydraConfig) -> str:
    """Render *cfg* to the legacy Janus_Config.txt text format (any family).

    The set of global sections and per-board fields is taken from the config's
    family, so this works uniformly for A5202 and A5203 configs.
    """
    lines: list[str] = []
    lines.append("# " + "*" * 88)
    lines.append("# params File generated by HydraFERS (hydrafers.config)")
    lines.append(f"# board_family {int(getattr(cfg, 'board_family', FAMILY_5202))}")
    lines.append("# " + "*" * 88)

    # --- Connect block (per-board Open[i]) ---
    lines.append(_banner("Connect"))
    for i, board in enumerate(cfg.boards):
        lines.append(_fmt_line(f"Open[{i}]", board.Open))
    lines.append("")

    # --- Common and default settings (global params) ---
    lines.append("")
    lines.append("# " + "*" * 88)
    lines.append("# Common and Default settings")
    lines.append("# " + "*" * 88)

    for banner_name, attr in _global_sections_for(cfg):
        section = getattr(cfg, attr)
        lines.append(_banner(banner_name))
        for name, value in section.__dict__.items():
            lines.append(_fmt_line(name, _scalar_to_str(value), _COMMENTS.get(name)))
        lines.append("")

    # --- Board and Channel settings (overwrite default settings) ---
    lines.append("")
    lines.append("# " + "*" * 88)
    lines.append("# Board and Channel settings (overwrite default settings)")
    lines.append("# " + "*" * 88)
    for b_idx, board in enumerate(cfg.boards):
        board_cls = type(board)
        for name in getattr(board_cls, "_UNIT_FIELDS", ()):
            lines.append(_fmt_line(f"{name}[{b_idx}]", getattr(board, name)))
        for name in getattr(board_cls, "_HEX_FIELDS", ()):
            lines.append(_fmt_line(f"{name}[{b_idx}]", "0x" + getattr(board, name)))
        for name in getattr(board_cls, "_INT_FIELDS", ()):
            lines.append(_fmt_line(f"{name}[{b_idx}]", str(getattr(board, name))))
        for name in getattr(board_cls, "_CHANNEL_FIELDS", ()):
            values = getattr(board, name)
            for ch, val in enumerate(values):
                lines.append(_fmt_line(f"{name}[{b_idx}][{ch}]", _scalar_to_str(val)))

    return "\n".join(lines) + "\n"


# Regex for a legacy parameter line: NAME with optional [brd] and [ch] suffixes.
_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\[(?P<brd>\d+)\])?"
    r"(?:\[(?P<ch>\d+)\])?"
    r"\s+(?P<value>.*?)\s*$"
)


def _build_owner_map(section_models) -> dict[str, str]:
    """Map each global field NAME to its owning config attr, for one family."""
    owner: dict[str, str] = {}
    for model, attr in section_models:
        for fname in model.model_fields:
            owner[fname] = attr
    return owner


_OWNER_5202 = _build_owner_map(_SECTION_MODELS_5202)
_OWNER_5203 = _build_owner_map(_SECTION_MODELS_5203)

_BOARD_FIELDS_5202 = frozenset(
    ("Open",)
    + BoardConfig._UNIT_FIELDS
    + BoardConfig._HEX_FIELDS
    + BoardConfig._INT_FIELDS
)
_CHANNEL_FIELDS_5202 = frozenset(BoardConfig._CHANNEL_FIELDS)
_BOARD_FIELDS_5203 = frozenset(
    ("Open",) + Board5203Config._HEX_FIELDS + Board5203Config._INT_FIELDS
)
_CHANNEL_FIELDS_5203 = frozenset(Board5203Config._CHANNEL_FIELDS)

# Names that appear in exactly ONE family -> a strong family signal on parse.
_ALL_5202_NAMES = set(_OWNER_5202) | _BOARD_FIELDS_5202 | _CHANNEL_FIELDS_5202
_ALL_5203_NAMES = set(_OWNER_5203) | _BOARD_FIELDS_5203 | _CHANNEL_FIELDS_5203
_EXCLUSIVE_5203 = _ALL_5203_NAMES - _ALL_5202_NAMES
_EXCLUSIVE_5202 = _ALL_5202_NAMES - _ALL_5203_NAMES


def _strip_comment(value: str) -> str:
    """Drop a trailing ``# ...`` comment from a value token."""
    hashpos = value.find("#")
    if hashpos != -1:
        value = value[:hashpos]
    return value.strip()


def _iter_param_lines(text: str):
    """Yield ``(name, brd, ch, value)`` for each non-comment legacy param line."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        name = _LEGACY_NAME_ALIASES.get(name, name)
        value = _strip_comment(m.group("value"))
        if value == "":
            continue
        yield name, m.group("brd"), m.group("ch"), value


def detect_family(text: str) -> int:
    """Detect the board family of a legacy config from the parameter names.

    Looks for names that exist in exactly one family. An explicit
    ``# board_family N`` banner (emitted by :func:`render_legacy_txt`) wins.
    Falls back to 5202 (the historical default) when ambiguous.
    """
    m = re.search(r"^#\s*board_family\s+(\d+)\s*$", text, re.MULTILINE)
    if m:
        return int(m.group(1))
    names = {name for name, _b, _c, _v in _iter_param_lines(text)}
    score_5203 = len(names & _EXCLUSIVE_5203)
    score_5202 = len(names & _EXCLUSIVE_5202)
    return FAMILY_5203 if score_5203 > score_5202 else FAMILY_5202


def parse_legacy_txt(text: str) -> BaseHydraConfig:
    """Parse legacy Janus_Config.txt *text* into a validated config.

    The board family is auto-detected (:func:`detect_family`); the matching
    section/board/channel routing tables are then used to build the right model.
    """
    family = detect_family(text)
    if family == FAMILY_5203:
        return _parse_family(
            text,
            num_ch=NUM_CHANNELS_5203,
            owner=_OWNER_5203,
            board_fields=_BOARD_FIELDS_5203,
            channel_fields=_CHANNEL_FIELDS_5203,
            board_cls=Board5203Config,
            section_models=_SECTION_MODELS_5203,
            config_cls=HydraConfig5203,
        )
    return _parse_family(
        text,
        num_ch=NUM_CHANNELS,
        owner=_OWNER_5202,
        board_fields=_BOARD_FIELDS_5202,
        channel_fields=_CHANNEL_FIELDS_5202,
        board_cls=BoardConfig,
        section_models=_SECTION_MODELS_5202,
        config_cls=HydraConfig,
    )


def _parse_family(
    text: str,
    *,
    num_ch: int,
    owner: dict[str, str],
    board_fields: frozenset,
    channel_fields: frozenset,
    board_cls,
    section_models,
    config_cls,
) -> BaseHydraConfig:
    """Generic legacy parser parameterized by a family's routing tables."""
    global_params: dict[str, str] = {}
    board_scalar: dict[int, dict[str, str]] = {}
    board_channel: dict[int, dict[str, list]] = {}

    def ensure_board(idx: int) -> None:
        board_scalar.setdefault(idx, {})
        board_channel.setdefault(idx, {})

    for name, brd, ch, value in _iter_param_lines(text):
        b_idx = int(brd) if brd is not None else 0
        if name in channel_fields:
            ensure_board(b_idx)
            arr = board_channel[b_idx].setdefault(name, [None] * num_ch)
            if ch is not None:
                ci = int(ch)
                if 0 <= ci < num_ch:
                    arr[ci] = value
            else:
                board_channel[b_idx][name] = [value] * num_ch
        elif name in board_fields:
            ensure_board(b_idx)
            board_scalar[b_idx][name] = value
        elif name in owner:
            global_params[name] = value
        # unknown names (monitor params, GUI-only tabs, other family) are ignored

    if not board_scalar and not board_channel:
        ensure_board(0)

    board_indices = sorted(set(board_scalar) | set(board_channel))
    boards = []
    for idx in board_indices:
        kwargs: dict[str, object] = {}
        for name, val in board_scalar.get(idx, {}).items():
            kwargs[name] = val
        for name, arr in board_channel.get(idx, {}).items():
            defaults = getattr(board_cls(), name)
            filled = [defaults[i] if arr[i] is None else arr[i] for i in range(num_ch)]
            kwargs[name] = filled
        boards.append(_build_lenient(board_cls, kwargs, what=f"board[{idx}]"))

    section_kwargs: dict[str, dict[str, str]] = {attr: {} for _m, attr in section_models}
    for name, val in global_params.items():
        section_kwargs[owner[name]][name] = val

    sections = {
        attr: _build_lenient(model, section_kwargs[attr], what=attr)
        for model, attr in section_models
    }
    return config_cls(boards=boards, **sections)


def convert_janus_txt(
    txt_path: str | Path, yaml_path: str | Path | None = None
) -> BaseHydraConfig:
    """Parse a legacy Janus_Config.txt and optionally save it as YAML.

    Parameters
    ----------
    txt_path:
        Path to the legacy ``Janus_Config.txt`` file.
    yaml_path:
        If given, the resulting config is written there as YAML.

    Returns
    -------
    BaseHydraConfig
        The validated configuration parsed from the legacy file (the concrete
        subclass matches the detected board family).
    """
    text = Path(txt_path).read_text(encoding="utf-8")
    cfg = parse_legacy_txt(text)
    if yaml_path is not None:
        # local import to avoid import cycle (loader imports nothing from here)
        from hydrafers.config.loader import save_config

        save_config(cfg, yaml_path)
    return cfg

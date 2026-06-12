"""YAML load/save and default-config entry points (CONTRACT.md §2).

Layer: ``hydrafers.config`` -- pure Python (pydantic v2 + pyyaml). NO pyfers/Qt
import.

YAML is the on-disk format; a single file is fully shareable. Loading parses and
validates through :class:`HydraConfig` (pydantic v2), so out-of-range values and
unknown combo options raise a clear :class:`pydantic.ValidationError`.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

from hydrafers.config.schema import (
    FAMILY_5202,
    FAMILY_5203,
    BaseHydraConfig,
    HydraConfig,
)
from hydrafers.config.schema_5203 import HydraConfig5203

# Bundled defaults: 5202 from param_defs_reference.txt, 5203 from janus-5203.
_DEFAULT_YAML = Path(__file__).with_name("default.yaml")
_DEFAULT_YAML_5203 = Path(__file__).with_name("default_5203.yaml")

# Map each board-family code to its concrete config model.
_FAMILY_MODELS: dict[int, type[BaseHydraConfig]] = {
    FAMILY_5202: HydraConfig,
    FAMILY_5203: HydraConfig5203,
}


def _model_for_family(family: int) -> type[BaseHydraConfig]:
    """Return the config model class for a ``board_family`` code (default 5202)."""
    try:
        return _FAMILY_MODELS[int(family)]
    except (KeyError, TypeError, ValueError):
        raise ValueError(
            f"unknown board_family {family!r}; expected one of "
            f"{sorted(_FAMILY_MODELS)}"
        ) from None


class _FlowMap(dict):
    """A dict the YAML dumper renders inline (flow style) — keeps the compact
    ``overrides`` map on one line, e.g. ``{5: 3, 6: 3}``."""


def _flow_map_representer(dumper, data):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data, flow_style=True)


yaml.SafeDumper.add_representer(_FlowMap, _flow_map_representer)


def _compact_channel_arrays(data: dict, channel_fields: tuple[str, ...]) -> None:
    """Rewrite each board's per-channel arrays in place into the compact on-disk
    form: a scalar when uniform, else ``{default, overrides}`` where ``default``
    is the most common value and ``overrides`` is an inline ``{channel: value}``
    map of only the channels that differ. ``channel_fields`` is the per-family
    set of channel-scoped field names (the families differ)."""
    for board in data.get("boards", []):
        for field in channel_fields:
            vals = board.get(field)
            if not isinstance(vals, list) or not vals:
                continue
            if len(set(vals)) == 1:
                board[field] = vals[0]
                continue
            default = Counter(vals).most_common(1)[0][0]
            overrides = _FlowMap((i, v) for i, v in enumerate(vals) if v != default)
            board[field] = {"default": default, "overrides": overrides}


def load_config(path: str | Path) -> BaseHydraConfig:
    """Load a YAML file and return a validated config for its board family.

    The top-level ``board_family`` key selects the model (5202 -> ``HydraConfig``,
    5203 -> ``HydraConfig5203``); when absent it defaults to 5202 for backward
    compatibility with the existing single-family files.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If the top level is not a mapping or ``board_family`` is unknown.
    pydantic.ValidationError
        If the YAML contents fail schema validation (bad combo option, out of
        range value, wrong channel-array length, unknown parameter, ...).
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(
            f"config file {p} must contain a YAML mapping at the top level, "
            f"got {type(data).__name__}"
        )
    model = _model_for_family(data.get("board_family", FAMILY_5202))
    return model.model_validate(data)


def save_config(cfg: BaseHydraConfig, path: str | Path) -> None:
    """Serialize *cfg* to YAML at *path* (round-trippable through load_config).

    Per-channel arrays are written compactly (scalar when uniform, otherwise a
    ``{default, overrides}`` map) so files don't carry redundant values for
    channels that are not individually configured. The channel-field set is
    taken from the board class of *cfg* (it differs between families).
    """
    p = Path(path)
    data = cfg.model_dump(mode="json")
    channel_fields: tuple[str, ...] = ()
    if cfg.boards:
        channel_fields = getattr(type(cfg.boards[0]), "_CHANNEL_FIELDS", ())
    _compact_channel_arrays(data, channel_fields)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=120,
    )
    p.write_text(text, encoding="utf-8")


def default_config(family: int = FAMILY_5202) -> BaseHydraConfig:
    """Return the bundled default configuration for a board *family*.

    ``family=5202`` loads ``default.yaml`` (the A5202 default); ``family=5203``
    loads ``default_5203.yaml`` (the A5203 default).
    """
    fam = int(family)
    if fam == FAMILY_5203:
        return load_config(_DEFAULT_YAML_5203)
    if fam == FAMILY_5202:
        return load_config(_DEFAULT_YAML)
    raise ValueError(f"unknown board_family {family!r}; expected 5202 or 5203")

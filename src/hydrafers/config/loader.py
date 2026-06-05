"""YAML load/save and default-config entry points (CONTRACT.md §2).

Layer: ``hydrafers.config`` -- pure Python (pydantic v2 + pyyaml). NO pyfers/Qt
import.

YAML is the on-disk format; a single file is fully shareable. Loading parses and
validates through :class:`HydraConfig` (pydantic v2), so out-of-range values and
unknown combo options raise a clear :class:`pydantic.ValidationError`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from hydrafers.config.schema import HydraConfig

# Bundled defaults derived from docs/param_defs_reference.txt.
_DEFAULT_YAML = Path(__file__).with_name("default.yaml")


def load_config(path: str | Path) -> HydraConfig:
    """Load a YAML file and return a validated :class:`HydraConfig`.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
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
    return HydraConfig.model_validate(data)


def save_config(cfg: HydraConfig, path: str | Path) -> None:
    """Serialize *cfg* to YAML at *path* (round-trippable through load_config)."""
    p = Path(path)
    data = cfg.model_dump(mode="json")
    p.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=120,
    )
    p.write_text(text, encoding="utf-8")


def default_config() -> HydraConfig:
    """Return the configuration loaded from the bundled ``default.yaml``."""
    return load_config(_DEFAULT_YAML)

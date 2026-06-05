"""HydraFERS configuration layer (CONTRACT.md §2).

Layer: pure Python (pydantic v2 + pyyaml). This package MUST NOT import ``pyfers``
or any Qt/GUI symbol (CONTRACT.md §0).

YAML is the on-disk format. A single file is fully shareable. Validation is done
with pydantic v2 via :class:`HydraConfig`, which mirrors every parameter in
``docs/param_defs_reference.txt`` (parameter names kept verbatim so they can be
passed straight to :func:`pyfers.set_param`).

Public API:
    * :class:`HydraConfig`         -- the validated configuration model.
    * :func:`load_config`          -- YAML -> validated model.
    * :func:`save_config`          -- model -> YAML.
    * :func:`convert_janus_txt`    -- legacy Janus_Config.txt -> model (+ optional YAML).
    * :func:`default_config`       -- model from the bundled ``default.yaml``.
"""

from __future__ import annotations

from hydrafers.config.converter import convert_janus_txt
from hydrafers.config.loader import default_config, load_config, save_config
from hydrafers.config.schema import (
    NUM_CHANNELS,
    AcqModeConfig,
    BoardConfig,
    DiscrConfig,
    HVBiasConfig,
    HydraConfig,
    OutputFilesConfig,
    RunCtrlConfig,
    SpectroscopyConfig,
    TestProbeConfig,
)

__all__ = [
    "HydraConfig",
    "load_config",
    "save_config",
    "convert_janus_txt",
    "default_config",
    # sub-models (useful for the GUI auto-generated config editor)
    "BoardConfig",
    "HVBiasConfig",
    "RunCtrlConfig",
    "OutputFilesConfig",
    "AcqModeConfig",
    "DiscrConfig",
    "SpectroscopyConfig",
    "TestProbeConfig",
    "NUM_CHANNELS",
]

"""HydraFERS configuration layer (CONTRACT.md §2).

Layer: pure Python (pydantic v2 + pyyaml). This package MUST NOT import ``pyfers``
or any Qt/GUI symbol (CONTRACT.md §0).

YAML is the on-disk format. A single file is fully shareable. Validation is done
with pydantic v2 via :class:`HydraConfig`, which mirrors every parameter in
``docs/param_defs_reference.txt`` (parameter names kept verbatim so they can be
passed straight to :func:`pyfers.set_param`).

HydraFERS supports two board families from one binary (never mixed in a single
run; see ``docs/A5203_INTEGRATION_STUDY.md``). A config file declares its family
via the top-level ``board_family`` key (5202 -> :class:`HydraConfig`, 5203 ->
:class:`HydraConfig5203`); both share the :class:`BaseHydraConfig` interface.

Public API:
    * :class:`BaseHydraConfig`     -- the family-agnostic interface (annotations).
    * :class:`HydraConfig`         -- the A5202 configuration model.
    * :class:`HydraConfig5203`     -- the A5203 (picoTDC) configuration model.
    * :func:`load_config`          -- YAML -> validated model (family auto-detected).
    * :func:`save_config`          -- model -> YAML.
    * :func:`convert_janus_txt`    -- legacy Janus_Config.txt -> model (+ optional YAML).
    * :func:`default_config`       -- bundled default for a board family.
"""

from __future__ import annotations

from hydrafers.config.converter import convert_janus_txt
from hydrafers.config.loader import default_config, load_config, save_config
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

__all__ = [
    "BaseHydraConfig",
    "HydraConfig",
    "HydraConfig5203",
    "load_config",
    "save_config",
    "convert_janus_txt",
    "default_config",
    "FAMILY_5202",
    "FAMILY_5203",
    # 5202 sub-models (useful for the GUI auto-generated config editor)
    "BoardConfig",
    "HVBiasConfig",
    "RunCtrlConfig",
    "OutputFilesConfig",
    "AcqModeConfig",
    "DiscrConfig",
    "SpectroscopyConfig",
    "TestProbeConfig",
    "NUM_CHANNELS",
    # 5203 sub-models
    "Board5203Config",
    "RunCtrl5203Config",
    "OutputFiles5203Config",
    "AcqMode5203Config",
    "TDCConfig",
    "DataAnalysis5203Config",
    "Adapters5203Config",
    "NUM_CHANNELS_5203",
]

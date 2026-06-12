"""Dual-family configuration: schema, loader dispatch, and legacy conversion.

Covers the A5202/A5203 config split (docs/A5203_INTEGRATION_STUDY.md §2.2):
the loader picks the model from ``board_family``; both families round-trip
through YAML and the legacy text format; strict validation still rejects bad
combos on hand-authored input, while legacy import tolerates stray firmware
tokens.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydrafers.config import (
    BaseHydraConfig,
    HydraConfig,
    HydraConfig5203,
    default_config,
    load_config,
    save_config,
)
from hydrafers.config.converter import (
    convert_janus_txt,
    detect_family,
    parse_legacy_txt,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------- defaults / family
def test_defaults_select_family():
    c2 = default_config(5202)
    c3 = default_config(5203)
    assert isinstance(c2, HydraConfig) and c2.board_family == 5202
    assert isinstance(c3, HydraConfig5203) and c3.board_family == 5203
    assert isinstance(c2, BaseHydraConfig) and isinstance(c3, BaseHydraConfig)


def test_default_config_unknown_family_rejected():
    with pytest.raises(ValueError):
        default_config(9999)


def test_5203_has_no_hv_or_spectroscopy_fields():
    c3 = default_config(5203)
    # 5203 must NOT carry 5202-only sections (HV / spectroscopy / test-probe).
    for absent in ("hv_bias", "spectroscopy", "test_probe", "discr"):
        assert not hasattr(c3, absent), f"5203 config unexpectedly has {absent}"
    # ...and MUST carry its own.
    for present in ("tdc", "data_analysis", "adapters"):
        assert hasattr(c3, present)
    assert c3.acq_mode.MeasMode == "LEAD_ONLY"


# ------------------------------------------------------------------- loader dispatch
def test_load_config_dispatches_on_board_family(tmp_path):
    c3 = default_config(5203)
    p = tmp_path / "cfg.yaml"
    save_config(c3, p)
    loaded = load_config(p)
    assert isinstance(loaded, HydraConfig5203)
    assert loaded.to_ferslib_params() == c3.to_ferslib_params()


def test_load_config_defaults_to_5202_when_unmarked(tmp_path):
    p = tmp_path / "legacy.yaml"
    p.write_text("version: 1\nboards:\n  - Open: eth:1.2.3.4\n", encoding="utf-8")
    loaded = load_config(p)
    assert isinstance(loaded, HydraConfig) and loaded.board_family == 5202


# ------------------------------------------------------------------- YAML round-trip
@pytest.mark.parametrize("family", [5202, 5203])
def test_yaml_round_trip(tmp_path, family):
    cfg = default_config(family)
    p = tmp_path / f"{family}.yaml"
    save_config(cfg, p)
    again = load_config(p)
    assert again.board_family == family
    assert again.to_ferslib_params() == cfg.to_ferslib_params()


# --------------------------------------------------------------- strict validation
def test_strict_validation_rejects_bad_5203_combo():
    with pytest.raises(ValidationError):
        HydraConfig5203(acq_mode={"AcquisitionMode": "SPECTROSCOPY"})  # 5202-only mode
    with pytest.raises(ValidationError):
        HydraConfig5203(acq_mode={"MeasMode": "NONSENSE"})


def test_5203_channel_masks_cover_128_channels():
    c3 = default_config(5203)
    board = c3.boards[0]
    assert len(board.DiscrThreshold) == 128
    # four 32-bit masks = 128 channels
    masks = [board.ChEnableMask0, board.ChEnableMask1, board.ChEnableMask2, board.ChEnableMask3]
    assert all(len(m) == 8 for m in masks)  # 8 hex digits = 32 bits each


# ------------------------------------------------------------------- legacy text
@pytest.mark.parametrize("family", [5202, 5203])
def test_legacy_txt_round_trip(family):
    cfg = default_config(family)
    txt = cfg.to_legacy_txt()
    assert detect_family(txt) == family
    back = parse_legacy_txt(txt)
    assert back.board_family == family
    assert back.to_ferslib_params() == cfg.to_ferslib_params()


def test_legacy_import_tolerates_unknown_combo_token(caplog):
    # A 5203 config carrying an out-of-list firmware probe token must still import.
    cfg5203 = default_config(5203)
    txt = cfg5203.to_legacy_txt().replace("TRG_ACCEPTED", "ACQCTRL_6")
    cfg = parse_legacy_txt(txt)
    assert cfg.board_family == 5203
    # the stray field falls back to the schema default, not a crash
    assert cfg.acq_mode.DigitalProbe0 in (
        "TRG_ACCEPTED", "CLK_1024", "TX_DATA_VALID",
    )


# --------------------------------------------------- real reference configs (if present)
@pytest.mark.parametrize(
    "rel, family",
    [
        ("janus-5202/bin/Janus_Config_Original.txt", 5202),
        ("janus-5203/bin/Janus_Config.txt", 5203),
    ],
)
def test_real_janus_configs_convert(rel, family):
    path = _REPO_ROOT / rel
    if not path.exists():
        pytest.skip(f"reference config {rel} not present")
    cfg = convert_janus_txt(path)
    assert cfg.board_family == family
    # the conversion must produce flattenable ferslib params
    assert len(cfg.to_ferslib_params()) > 0

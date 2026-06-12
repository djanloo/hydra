"""Board-family detection and homogeneous-system enforcement (5202 vs 5203).

Covers the dual-board foundation added for A5203 support: ``BoardFamily``,
``Board.family``/``has_hv``/``fers_code`` and ``System.family`` rejecting a mixed
fleet (ferslib forbids mixing families — see docs/A5203_INTEGRATION_STUDY.md §3).
The ``fake`` fixture's ``family_of[path]`` selects each opened board's FERSCode.
"""

from __future__ import annotations

import pytest

import pyfers
from pyfers import Board, BoardFamily, System
from pyfers.errors import ConfigError


# ----------------------------------------------------------------- BoardFamily
def test_board_family_capabilities():
    assert BoardFamily.A5202.has_hv is True
    assert BoardFamily.A5203.has_hv is False
    assert BoardFamily.A5202.num_channels == 64
    assert BoardFamily.A5203.num_channels == 128


def test_board_family_from_code_and_name():
    assert BoardFamily.from_code(5202) is BoardFamily.A5202
    assert BoardFamily.from_code(5203) is BoardFamily.A5203
    with pytest.raises(ValueError):
        BoardFamily.from_code(9999)
    assert BoardFamily.from_model_name("A5203") is BoardFamily.A5203
    assert BoardFamily.from_model_name("DT5202") is BoardFamily.A5202
    assert BoardFamily.from_model_name("mystery") is None


# ----------------------------------------------------------------------- Board
def test_board_detects_5202_by_default(fake):
    b = Board("eth:1.2.3.4").open()
    assert b.fers_code == 5202
    assert b.family is BoardFamily.A5202
    assert b.has_hv is True
    b.close()


def test_board_detects_5203(fake):
    fake.family_of["eth:5203"] = 5203
    b = Board("eth:5203").open()
    assert b.fers_code == 5203
    assert b.family is BoardFamily.A5203
    assert b.has_hv is False
    b.close()


def test_board_without_info_is_undetermined_but_assumes_hv(fake):
    fake.no_info_paths.add("tdl:0:0:0")
    b = Board("tdl:0:0:0").open()
    assert b.fers_code == 0
    assert b.family is None
    # Conservative default: assume HV present when family is unknown.
    assert b.has_hv is True
    b.close()


# ---------------------------------------------------------------------- System
def test_system_family_homogeneous_5202(fake):
    sys = System.open("eth:a", "eth:b")
    assert sys.family is BoardFamily.A5202
    sys.close()


def test_system_family_homogeneous_5203(fake):
    fake.family_of.update({"eth:a": 5203, "eth:b": 5203})
    sys = System.open("eth:a", "eth:b")
    assert sys.family is BoardFamily.A5203
    sys.close()


def test_system_rejects_mixed_families(fake):
    fake.family_of.update({"eth:a": 5202, "eth:b": 5203})
    with pytest.raises(ConfigError, match="mixed FERS board families"):
        System.open("eth:a", "eth:b")
    # All boards opened during the failed attempt must be closed (no handle leak).
    assert len(fake.closed) == 2


def test_system_family_ignores_infoless_endpoints(fake):
    fake.family_of["eth:a"] = 5203
    fake.no_info_paths.add("tdl:cnc")
    sys = System.open("tdl:cnc", "eth:a")
    assert sys.family is BoardFamily.A5203
    sys.close()

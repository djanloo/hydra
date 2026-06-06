"""Tests for pyfers.System orchestration against the fake pyferslib backend."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import pyferslib
from pyfers import Board, SortMode, StartMode, System
from pyfers.errors import ConfigError


# ------------------------------------------------------------- construction
def test_empty_system_raises(fake):
    with pytest.raises(ConfigError):
        System([])


def test_open_requires_paths(fake):
    with pytest.raises(ConfigError):
        System.open()


def test_open_multi_board_and_handles(fake):
    s = System.open("eth:a", "eth:b", "eth:c")
    assert [b.path for b in s.boards] == ["eth:a", "eth:b", "eth:c"]
    assert len(s.handles) == 3
    assert all(b.is_open for b in s.boards)
    s.close()
    assert s.handles == []          # closed boards skipped


def test_open_failure_closes_already_opened(fake):
    fake.fail_paths.add("eth:b")
    with pytest.raises(pyferslib.FERSError):
        System.open("eth:a", "eth:b", "eth:c")
    # only eth:a was opened before eth:b failed; it must have been closed.
    assert len(fake.closed) == 1


# ------------------------------------------------------------- from_config
def test_from_config_via_board_paths(fake):
    class Cfg:
        def board_paths(self):
            return ["eth:a", "eth:b"]

    s = System.from_config(Cfg())
    assert [b.path for b in s.boards] == ["eth:a", "eth:b"]


def test_from_config_duck_typed_boards(fake):
    class B:
        def __init__(self, open_):
            self.Open = open_

    class Cfg:
        boards = [B("eth:x"), {"open": "eth:y"}]

    s = System.from_config(Cfg())
    assert [b.path for b in s.boards] == ["eth:x", "eth:y"]


def test_from_config_no_paths_raises(fake):
    class Cfg:
        boards: list = []

    with pytest.raises(ConfigError):
        System.from_config(Cfg())


# ------------------------------------------------------------- configure
def test_configure_global_vs_targeted(fake):
    s = System.open("eth:a", "eth:b")
    h0, h1 = s.boards[0].handle, s.boards[1].handle
    s.configure(
        [
            (0, "AcquisitionMode", "COUNTING"),  # index 0 -> all boards
            (1, "HV_Vbias", "60 V"),             # index 1 -> only boards[1]
            (0, "Open", "eth:ignored"),          # 'Open' pseudo-param skipped
        ],
        mode="soft",
    )
    assert fake.devices[h0]["params"]["AcquisitionMode"] == "COUNTING"
    assert fake.devices[h1]["params"]["AcquisitionMode"] == "COUNTING"
    assert "HV_Vbias" in fake.devices[h1]["params"]
    assert "HV_Vbias" not in fake.devices[h0]["params"]
    assert "Open" not in fake.devices[h0]["params"]
    # every board is configured once, in soft mode
    assert (h0, pyferslib.CFG_SOFT) in fake.configured
    assert (h1, pyferslib.CFG_SOFT) in fake.configured


def test_configure_board_index_out_of_range(fake):
    s = System.open("eth:a", "eth:b")
    with pytest.raises(ConfigError):
        s.configure([(5, "X", "y")])


def test_configure_bad_mode(fake):
    s = System.open("eth:a")
    with pytest.raises(ConfigError):
        s.configure([], mode="weird")


# ------------------------------------------------------------- run control
def test_init_readout_all_boards(fake):
    s = System.open("eth:a", "eth:b")
    s.init_readout(SortMode.TRGTIME)
    assert len(fake.readout_init) == 2
    assert all(rm == pyferslib.ROMODE_TRGTIME_SORTING for _, rm in fake.readout_init)


def test_start_stop_pass_correct_ints(fake):
    s = System.open("eth:a", "eth:b")
    s.start_run(StartMode.CHAIN_T0, run_number=5)
    s.stop_run(StartMode.ASYNC, run_number=5)

    start = fake.acq_calls[0]
    stop = fake.acq_calls[1]
    assert start == ("start", s.handles, pyferslib.START_CHAIN_T0, 5)
    assert stop[0] == "stop" and stop[2] == pyferslib.START_ASYNC


# ------------------------------------------------------------- data plane
def test_events_decode_and_stop_on_short_batch(fake):
    s = System.open("eth:a")
    fake.drain_batches = [
        [(0, pyferslib.DTQ_SPECT, SimpleNamespace(trigger_id=11))],  # len 1 < batch 2
    ]
    evs = list(s.events(max_batch=2))
    assert len(evs) == 1
    assert evs[0].trigger_id == 11


def test_events_full_batch_then_empty(fake):
    s = System.open("eth:a")
    fake.drain_batches = [
        [(0, pyferslib.DTQ_COUNT, SimpleNamespace(counts=[1])),
         (0, pyferslib.DTQ_COUNT, None)],   # None entries are skipped
        [],                                  # empty -> stop
    ]
    evs = list(s.events(max_batch=2))
    assert len(evs) == 1                    # the None one was skipped


def test_events_stop_on_reprocess_sentinel(fake):
    s = System.open("eth:a")
    fake.drain_batches = [
        [(-1, pyferslib.RAWDATA_REPROCESS_FINISHED, None)],
    ]
    assert list(s.events(max_batch=2)) == []


# ------------------------------------------------------------- teardown
def test_flush_all_open_boards(fake):
    s = System.open("eth:a", "eth:b")
    handles = list(s.handles)
    s.flush()
    assert all(fake.devices[h].get("flushed") for h in handles)


def test_context_manager_closes_all(fake):
    with System.open("eth:a", "eth:b") as s:
        handles = list(s.handles)
    assert all(h in fake.closed for h in handles)

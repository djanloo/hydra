"""IO layer: A5203 timing files round-trip and the header is self-describing.

The binary record layout already stores per-hit channel/edge/toa(u32)/tot, so a
picoTDC file needs no new record type — only the v2 header fields (board_family /
num_ch / meas_mode) so a reader knows how to interpret it. v1 files (no such
fields) must still read with A5202 defaults.
"""

from __future__ import annotations

import numpy as np

from hydrafers.io import EventReader, EventWriter, FileHeader
from hydrafers.io.formats import FORMAT_VERSION


def _timing_event(board=0):
    return {
        "board": board, "dtq": 0x02, "tstamp_us": 1.5,
        "trigger_id": 7, "tref_tstamp": 0, "tstamp_clk": 123, "nhits": 4,
        "channel": np.array([0, 0, 100, 127], dtype=np.int64),  # 128-ch range
        "edge": np.array([0, 1, 0, 1], dtype=np.int64),
        "toa": np.array([10, 20, 3_000_000_000, 40], dtype=np.uint32),  # needs u32
        "tot": np.array([3, 0, 7, 0], dtype=np.uint32),
    }


def test_5203_header_is_self_describing(tmp_path):
    path = tmp_path / "Run1_list.dat"
    hdr = FileHeader(
        acquisition_mode="COMMON_START", board_model="A5203",
        board_family=5203, num_ch=128, meas_mode="LEAD_TRAIL", run_number=1,
    )
    with EventWriter(path, hdr) as w:
        w.write_event(_timing_event())
    r = EventReader(path)
    h = r.header()
    assert h.format_version == FORMAT_VERSION == 2
    assert h.board_family == 5203
    assert h.num_ch == 128
    assert h.meas_mode == "LEAD_TRAIL"
    assert not h.legacy


def test_5203_timing_round_trip_preserves_edges_and_u32_toa(tmp_path):
    path = tmp_path / "Run2_list.dat"
    hdr = FileHeader(board_family=5203, num_ch=128, acquisition_mode="COMMON_START")
    src = _timing_event()
    with EventWriter(path, hdr) as w:
        w.write_event(src)
    events = list(EventReader(path))
    assert len(events) == 1
    ev = events[0]
    assert ev["nhits"] == 4
    np.testing.assert_array_equal(ev["channel"][:4], src["channel"])
    np.testing.assert_array_equal(ev["edge"][:4], src["edge"])
    np.testing.assert_array_equal(ev["toa"][:4], src["toa"])  # u32 high value survives
    np.testing.assert_array_equal(ev["tot"][:4], src["tot"])
    assert ev["channel"].max() == 127  # 128-channel index preserved


def test_v1_header_without_family_defaults_to_5202(tmp_path):
    # Simulate an older file by serializing a header dict missing the v2 fields.
    data = {
        "format_version": 1, "acquisition_mode": "SPECT", "energy_nbins": 4096,
        "board_model": "A5202", "run_number": 5,
    }
    h = FileHeader.from_dict(data)
    assert h.board_family == 5202
    assert h.num_ch == 64
    assert h.meas_mode == ""

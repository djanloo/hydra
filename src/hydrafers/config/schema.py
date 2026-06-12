"""Pydantic v2 schema for HydraFERS configuration (CONTRACT.md §2).

Layer: ``hydrafers.config`` -- pure Python (pydantic v2 only). This module MUST
NOT import ``pyfers`` or any Qt/GUI symbol (CONTRACT.md §0).

The schema mirrors EVERY parameter in ``docs/param_defs_reference.txt`` grouped by
its section. Parameter field names are kept IDENTICAL to the ferslib parameter
names because they are passed verbatim to :func:`pyfers.set_param`.

Scope handling (param_defs column 3):
    * ``g`` (global)  -> a single field on the owning section model.
    * ``b`` (board)   -> a per-board override, lives on :class:`BoardConfig`.
    * ``c`` (channel) -> a list/array of 64 values, lives on :class:`BoardConfig`.

Type handling (param_defs column 4):
    * ``c`` combo    -> validated against the option list from param_defs.
    * ``u``/``fu``/``du`` unit -> accepted as the ``"value unit"`` string form and
      kept verbatim (NAME + VALUE string) for :meth:`HydraConfig.to_ferslib_params`.
    * ``b`` boolean  -> 0/1 integer (ferslib encodes booleans as 0/1 strings).
    * ``h`` hex      -> stored as an uppercase hex string (e.g. ``"FFFFFFFF"``).
    * ``d`` int / ``f`` float / ``s`` string -> native types.
    * ``m`` monitor  -> shown in GUI but NOT a configuration input (e.g. ``Vnom``):
      computed/read live by the engine, so it is intentionally NOT modelled here
      and never appears in ``to_ferslib_params`` / ``to_legacy_txt``.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# Channel count for the 5202 board family (FERSLIB_MAX_NCH_5202 in FERSlib.h).
NUM_CHANNELS: int = 64

# Board family codes (ferslib FERSCode). HydraFERS never mixes families in one
# running system (see docs/A5203_INTEGRATION_STUDY.md §3); a config file targets
# exactly one family, declared by its ``board_family`` field.
FAMILY_5202: int = 5202
FAMILY_5203: int = 5203

# A loose pattern for "value unit" strings such as "62.5 V", "100 ns", "1 GB".
# We accept an optional leading sign, an int/float value, optional whitespace and
# an optional alphabetic unit token. The exact string is preserved verbatim.
_UNIT_RE = re.compile(r"^\s*[-+]?\d+(?:\.\d+)?\s*[A-Za-z%]*\s*$")


# ---------------------------------------------------------------------------
# Combo option lists (taken VERBATIM from docs/param_defs_reference.txt).
# These are the authoritative allowed-value sets for combo ('c'-type) params.
# Quoted options in param_defs are stored unquoted here (the on-the-wire value).
# ---------------------------------------------------------------------------
HV_ADJUST_RANGE_OPTS = ("4.5", "2.5", "DISABLED")
TEMP_SENS_TYPE_OPTS = ("TMP37", "LM94021_G11", "LM94021_G00")
START_RUN_MODE_OPTS = ("ASYNC", "TDL", "TDL_EXTRUN", "TDL_GPS", "CHAIN_T0", "CHAIN_T1")
GPS_PPS_SOURCE_OPTS = ("GPS", "LEMO_RB")
EXT_RUN_SOURCE_OPTS = ("SYNC-IN", "LEMO_RA", "LEMO_RB", "LEMO_FA", "LEMO_FB")
EXT_RUN_LEVEL_OPTS = ("NIM", "TTL")
STOP_RUN_MODE_OPTS = ("MANUAL", "PRESET_TIME", "PRESET_COUNTS")
EVENT_BUILDING_MODE_OPTS = ("DISABLED", "TRGTIME_SORTING", "TRGID_SORTING")
DATA_ANALYSIS_OPTS = ("ALL", "CNT_ONLY", "DISABLED")
OF_OUTFILE_UNIT_OPTS = ("LSB", "ns")
ACQUISITION_MODE_OPTS = (
    "SPECTROSCOPY",
    "SPECT_TIMING",
    "TIMING_CSTART",
    "TIMING_CSTOP",
    "COUNTING",
    "WAVEFORM",
)
BUNCH_TRG_SOURCE_OPTS = ("T0-IN", "T1-IN", "Q-OR", "T-OR", "TLOGIC", "PTRG")
VETO_SOURCE_OPTS = ("DISABLED", "SW_CMD", "T0-IN", "T1-IN")
VALIDATION_SOURCE_OPTS = ("SW_CMD", "T0-IN", "T1-IN")
VALIDATION_MODE_OPTS = ("DISABLED", "ACCEPT", "REJECT")
COUNTING_MODE_OPTS = ("SINGLES", "PAIRED_AND")
TRG_ID_MODE_OPTS = ("TRIGGER_CNT", "VALIDATION_CNT")
TRIGGER_LOGIC_OPTS = (
    "OR64",
    "AND2_OR32",
    "OR32_AND2",
    "MAJ64",
    "MAJ32_AND2",
    "OR_QUAD",
)
TREF_SOURCE_OPTS = ("T0-IN", "T1-IN", "Q-OR", "T-OR", "PTRG", "TLOGIC")
T0_OUT_OPTS = (
    "T0-IN",
    "BUNCHTRG",
    "T-OR",
    "TLOGIC",
    "RUN",
    "PTRG",
    "BUSY",
    "DPROBE",
    "SQ_WAVE",
    "TDL_SYNC",
    "RUN_SYNC",
    "ZERO",
)
T1_OUT_OPTS = (
    "T1-IN",
    "BUNCHTRG",
    "Q-OR",
    "TLOGIC",
    "RUN",
    "PTRG",
    "BUSY",
    "DPROBE",
    "SQ_WAVE",
    "TDL_SYNC",
    "RUN_SYNC",
    "ZERO",
)
FAST_SHAPER_INPUT_OPTS = ("HG-PA", "LG-PA")
GAIN_SELECT_OPTS = ("HIGH", "LOW", "AUTO", "BOTH")
SHAPING_TIME_OPTS = (
    "87.5 ns",
    "75 ns",
    "62.5 ns",
    "50 ns",
    "37.5 ns",
    "25 ns",
    "12.5 ns",
)
EHISTO_NBIN_OPTS = ("DISABLED", "256", "512", "1K", "2K", "4K", "8K")
TOA_HISTO_NBIN_OPTS = ("DISABLED", "256", "512", "1K", "2K", "4K", "8K", "16K")
MCS_HISTO_NBIN_OPTS = ("DISABLED", "256", "512", "1K", "2K", "4K", "8K", "16K")
ANALOG_PROBE_OPTS = ("OFF", "FAST", "SLOW_LG", "SLOW_HG", "PREAMP_LG", "PREAMP_HG")
DIGITAL_PROBE_OPTS = (
    "OFF",
    "PEAK_LG",
    "PEAK_HG",
    "HOLD",
    "START_CONV",
    "DATA_COMMIT",
    "DATA_VALID",
    "CLK_1024",
    "VAL_WINDOW",
    "T_OR",
    "Q_OR",
)
TEST_PULSE_SOURCE_OPTS = ("OFF", "EXT", "T0-IN", "T1-IN", "PTRG", "SW-CMD")
TEST_PULSE_DESTINATION_OPTS = (
    ("NONE", "ALL", "EVEN", "ODD") + tuple(f"CH {i}" for i in range(NUM_CHANNELS))
)
TEST_PULSE_PREAMP_OPTS = ("LG", "HG", "BOTH")


def _normalize_unit_string(value: Any) -> str:
    """Coerce a numeric/string value into the verbatim ``"value unit"`` form.

    Plain numbers are stringified (so YAML may carry ``100`` for ``"100 ns"`` and
    we re-emit a clean string). Strings are stripped and validated against the
    loose unit pattern but otherwise preserved verbatim.
    """
    if isinstance(value, bool):  # guard: bool is a subclass of int
        raise ValueError("a boolean is not a valid unit value")
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if not _UNIT_RE.match(text):
            raise ValueError(
                f"{value!r} is not a valid 'value unit' string (e.g. '100 ns', '1 GB')"
            )
        # collapse internal whitespace to a single space
        return re.sub(r"\s+", " ", text)
    raise ValueError(f"unsupported unit value type: {type(value).__name__}")


# A reusable annotated type for unit ('u'/'fu'/'du') parameters.
UnitStr = Annotated[str, Field(...)]


def _hex_str(value: Any) -> str:
    """Normalize a channel-mask value to a bare uppercase hex string.

    Accepts ``int`` (e.g. ``0xFFFFFFFF``) or ``str`` (``"FFFFFFFF"`` or
    ``"0xFFFFFFFF"``). The stored canonical form is bare uppercase hex; the
    legacy/ferslib emitters prepend ``0x`` where required.
    """
    if isinstance(value, bool):
        raise ValueError("a boolean is not a valid hex mask")
    if isinstance(value, int):
        return f"{value:08X}"
    if isinstance(value, str):
        text = value.strip()
        if text.lower().startswith("0x"):
            text = text[2:]
        if not text or any(c not in "0123456789abcdefABCDEF" for c in text):
            raise ValueError(f"{value!r} is not a valid hexadecimal mask")
        return text.upper()
    raise ValueError(f"unsupported hex value type: {type(value).__name__}")


class _Base(BaseModel):
    """Shared base: forbid unknown params so typos surface as clear errors."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ---------------------------------------------------------------------------
# [HV_bias] -- global params only (the 'b'/'c' scoped HV params live on the board)
# ---------------------------------------------------------------------------
class HVBiasConfig(_Base):
    """[HV_bias] global parameters (param_defs scope 'g')."""

    HV_Adjust_Range: str = "4.5"
    TempSensType: str = "TMP37"
    TempFeedbackCoeff: float = 0.0
    EnableTempFeedback: int = Field(0, ge=0, le=1)

    @field_validator("HV_Adjust_Range")
    @classmethod
    def _v_adjust_range(cls, v: str) -> str:
        if v not in HV_ADJUST_RANGE_OPTS:
            raise ValueError(
                f"HV_Adjust_Range={v!r} not in allowed options {HV_ADJUST_RANGE_OPTS}"
            )
        return v

    @field_validator("TempSensType")
    @classmethod
    def _v_temp_sens(cls, v: str) -> str:
        # Allow the named sensors OR the generic "c0 c1 c2" coefficient form.
        if v in TEMP_SENS_TYPE_OPTS:
            return v
        parts = v.split()
        if len(parts) == 3:
            try:
                [float(p) for p in parts]
            except ValueError:
                pass
            else:
                return v
        raise ValueError(
            f"TempSensType={v!r} must be one of {TEMP_SENS_TYPE_OPTS} "
            "or generic coefficients 'c0 c1 c2'"
        )


# ---------------------------------------------------------------------------
# [RunCtrl]
# ---------------------------------------------------------------------------
class RunCtrlConfig(_Base):
    """[RunCtrl] global parameters."""

    StartRunMode: str = "ASYNC"
    GPSPPSSource: str = "GPS"
    ExtRunSource: str = "SYNC-IN"
    ExtRunLevel: str = "TTL"
    GPSTimeUTC: str = ""
    StopRunMode: str = "MANUAL"
    EventBuildingMode: str = "DISABLED"
    TstampCoincWindow: UnitStr = "100 ns"
    PresetTime: UnitStr = "0"
    PresetCounts: float = 0.0
    JobFirstRun: int = 0
    JobLastRun: int = 0
    RunSleep: UnitStr = "0"
    EnableJobs: int = Field(0, ge=0, le=1)
    RunNumber_AutoIncr: int = Field(0, ge=0, le=1)

    @field_validator("StartRunMode")
    @classmethod
    def _v_start(cls, v: str) -> str:
        if v not in START_RUN_MODE_OPTS:
            raise ValueError(f"StartRunMode={v!r} not in {START_RUN_MODE_OPTS}")
        return v

    @field_validator("GPSPPSSource")
    @classmethod
    def _v_gpspps(cls, v: str) -> str:
        if v not in GPS_PPS_SOURCE_OPTS:
            raise ValueError(f"GPSPPSSource={v!r} not in {GPS_PPS_SOURCE_OPTS}")
        return v

    @field_validator("ExtRunSource")
    @classmethod
    def _v_extsrc(cls, v: str) -> str:
        if v not in EXT_RUN_SOURCE_OPTS:
            raise ValueError(f"ExtRunSource={v!r} not in {EXT_RUN_SOURCE_OPTS}")
        return v

    @field_validator("ExtRunLevel")
    @classmethod
    def _v_extlvl(cls, v: str) -> str:
        if v not in EXT_RUN_LEVEL_OPTS:
            raise ValueError(f"ExtRunLevel={v!r} not in {EXT_RUN_LEVEL_OPTS}")
        return v

    @field_validator("StopRunMode")
    @classmethod
    def _v_stop(cls, v: str) -> str:
        if v not in STOP_RUN_MODE_OPTS:
            raise ValueError(f"StopRunMode={v!r} not in {STOP_RUN_MODE_OPTS}")
        return v

    @field_validator("EventBuildingMode")
    @classmethod
    def _v_ebm(cls, v: str) -> str:
        if v not in EVENT_BUILDING_MODE_OPTS:
            raise ValueError(f"EventBuildingMode={v!r} not in {EVENT_BUILDING_MODE_OPTS}")
        return v

    @field_validator("TstampCoincWindow", "PresetTime", "RunSleep", mode="before")
    @classmethod
    def _v_units(cls, v: Any) -> str:
        return _normalize_unit_string(v)


# ---------------------------------------------------------------------------
# [OutputFiles]
# ---------------------------------------------------------------------------
class OutputFilesConfig(_Base):
    """[OutputFiles] global parameters."""

    DataAnalysis: str = "ALL"
    DataFilePath: str = "DataFiles"
    OF_OutFileUnit: str = "LSB"
    OF_EnMaxSize: int = Field(0, ge=0, le=1)
    OF_MaxSize: UnitStr = "1 GB"
    OF_RawData: int = Field(0, ge=0, le=1)
    OF_ListBin: int = Field(0, ge=0, le=1)
    OF_ListAscii: int = Field(0, ge=0, le=1)
    OF_ListCSV: int = Field(0, ge=0, le=1)
    OF_Sync: int = Field(0, ge=0, le=1)
    OF_ServiceInfo: int = Field(0, ge=0, le=1)
    OF_RunInfo: int = Field(0, ge=0, le=1)
    OF_SpectHisto: int = Field(0, ge=0, le=1)
    OF_ToAHisto: int = Field(0, ge=0, le=1)
    OF_ToTHisto: int = Field(0, ge=0, le=1)
    OF_MCS: int = Field(0, ge=0, le=1)
    OF_Staircase: int = Field(0, ge=0, le=1)

    @field_validator("DataAnalysis")
    @classmethod
    def _v_da(cls, v: str) -> str:
        if v not in DATA_ANALYSIS_OPTS:
            raise ValueError(f"DataAnalysis={v!r} not in {DATA_ANALYSIS_OPTS}")
        return v

    @field_validator("OF_OutFileUnit")
    @classmethod
    def _v_ofu(cls, v: str) -> str:
        if v not in OF_OUTFILE_UNIT_OPTS:
            raise ValueError(f"OF_OutFileUnit={v!r} not in {OF_OUTFILE_UNIT_OPTS}")
        return v

    @field_validator("OF_MaxSize", mode="before")
    @classmethod
    def _v_maxsize(cls, v: Any) -> str:
        return _normalize_unit_string(v)


# ---------------------------------------------------------------------------
# [AcqMode]  (global params; ChEnableMask0/1 are board-scoped on BoardConfig)
# ---------------------------------------------------------------------------
class AcqModeConfig(_Base):
    """[AcqMode] global parameters."""

    AcquisitionMode: str = "SPECTROSCOPY"
    EnableToT: int = Field(1, ge=0, le=1)
    EnableListZeroSuppr: int = Field(0, ge=0, le=1)
    BunchTrgSource: str = "T-OR"
    VetoSource: str = "DISABLED"
    ValidationSource: str = "T0-IN"
    ValidationMode: str = "DISABLED"
    CountingMode: str = "SINGLES"
    ChTrg_Width: UnitStr = "8 ns"
    EnableCntZeroSuppr: int = Field(1, ge=0, le=1)
    TrgIdMode: str = "TRIGGER_CNT"
    TriggerLogic: str = "OR64"
    Tlogic_Width: UnitStr = "0 ns"
    MajorityLevel: int = Field(2, ge=1, le=64)
    PtrgPeriod: UnitStr = "1 s"
    TrefSource: str = "T0-IN"
    TrefWindow: UnitStr = "100 ns"
    TrefDelay: UnitStr = "0 ns"
    T0_Out: str = "T-OR"
    T1_Out: str = "BUNCHTRG"

    @field_validator("AcquisitionMode")
    @classmethod
    def _v_acq(cls, v: str) -> str:
        if v not in ACQUISITION_MODE_OPTS:
            raise ValueError(f"AcquisitionMode={v!r} not in {ACQUISITION_MODE_OPTS}")
        return v

    @field_validator("BunchTrgSource")
    @classmethod
    def _v_bunch(cls, v: str) -> str:
        if v not in BUNCH_TRG_SOURCE_OPTS:
            raise ValueError(f"BunchTrgSource={v!r} not in {BUNCH_TRG_SOURCE_OPTS}")
        return v

    @field_validator("VetoSource")
    @classmethod
    def _v_veto(cls, v: str) -> str:
        if v not in VETO_SOURCE_OPTS:
            raise ValueError(f"VetoSource={v!r} not in {VETO_SOURCE_OPTS}")
        return v

    @field_validator("ValidationSource")
    @classmethod
    def _v_valsrc(cls, v: str) -> str:
        if v not in VALIDATION_SOURCE_OPTS:
            raise ValueError(f"ValidationSource={v!r} not in {VALIDATION_SOURCE_OPTS}")
        return v

    @field_validator("ValidationMode")
    @classmethod
    def _v_valmode(cls, v: str) -> str:
        if v not in VALIDATION_MODE_OPTS:
            raise ValueError(f"ValidationMode={v!r} not in {VALIDATION_MODE_OPTS}")
        return v

    @field_validator("CountingMode")
    @classmethod
    def _v_cnt(cls, v: str) -> str:
        if v not in COUNTING_MODE_OPTS:
            raise ValueError(f"CountingMode={v!r} not in {COUNTING_MODE_OPTS}")
        return v

    @field_validator("TrgIdMode")
    @classmethod
    def _v_trgid(cls, v: str) -> str:
        if v not in TRG_ID_MODE_OPTS:
            raise ValueError(f"TrgIdMode={v!r} not in {TRG_ID_MODE_OPTS}")
        return v

    @field_validator("TriggerLogic")
    @classmethod
    def _v_trglogic(cls, v: str) -> str:
        if v not in TRIGGER_LOGIC_OPTS:
            raise ValueError(f"TriggerLogic={v!r} not in {TRIGGER_LOGIC_OPTS}")
        return v

    @field_validator("TrefSource")
    @classmethod
    def _v_tref(cls, v: str) -> str:
        if v not in TREF_SOURCE_OPTS:
            raise ValueError(f"TrefSource={v!r} not in {TREF_SOURCE_OPTS}")
        return v

    @field_validator("T0_Out")
    @classmethod
    def _v_t0(cls, v: str) -> str:
        if v not in T0_OUT_OPTS:
            raise ValueError(f"T0_Out={v!r} not in {T0_OUT_OPTS}")
        return v

    @field_validator("T1_Out")
    @classmethod
    def _v_t1(cls, v: str) -> str:
        if v not in T1_OUT_OPTS:
            raise ValueError(f"T1_Out={v!r} not in {T1_OUT_OPTS}")
        return v

    @field_validator(
        "ChTrg_Width", "Tlogic_Width", "PtrgPeriod", "TrefWindow", "TrefDelay",
        mode="before",
    )
    @classmethod
    def _v_units(cls, v: Any) -> str:
        return _normalize_unit_string(v)


# ---------------------------------------------------------------------------
# [Discr]  (global params; coarse-threshold and masks are board-scoped)
# ---------------------------------------------------------------------------
class DiscrConfig(_Base):
    """[Discr] global parameters."""

    FastShaperInput: str = "HG-PA"
    Hit_HoldOff: UnitStr = "0"
    QD_CoarseThreshold: int = Field(250, ge=0)

    @field_validator("FastShaperInput")
    @classmethod
    def _v_fsi(cls, v: str) -> str:
        if v not in FAST_SHAPER_INPUT_OPTS:
            raise ValueError(f"FastShaperInput={v!r} not in {FAST_SHAPER_INPUT_OPTS}")
        return v

    @field_validator("Hit_HoldOff", mode="before")
    @classmethod
    def _v_units(cls, v: Any) -> str:
        return _normalize_unit_string(v)


# ---------------------------------------------------------------------------
# [Spectroscopy]  (global params; HG_Gain/LG_Gain/ZS_Threshold_* are channel-scoped)
# ---------------------------------------------------------------------------
class SpectroscopyConfig(_Base):
    """[Spectroscopy] global parameters."""

    GainSelect: str = "HIGH"
    Pedestal: int = Field(100, ge=0)
    HG_ShapingTime: str = "25 ns"
    LG_ShapingTime: str = "25 ns"
    HoldDelay: UnitStr = "200 ns"
    MuxClkPeriod: UnitStr = "300 ns"
    EHistoNbin: str = "4K"
    ToAHistoNbin: str = "4K"
    ToARebin: int = Field(1, ge=1)
    ToAHistoMin: UnitStr = "0 ns"
    MCSHistoNbin: str = "4K"

    @field_validator("GainSelect")
    @classmethod
    def _v_gain(cls, v: str) -> str:
        if v not in GAIN_SELECT_OPTS:
            raise ValueError(f"GainSelect={v!r} not in {GAIN_SELECT_OPTS}")
        return v

    @field_validator("HG_ShapingTime", "LG_ShapingTime")
    @classmethod
    def _v_shaping(cls, v: str) -> str:
        if v not in SHAPING_TIME_OPTS:
            raise ValueError(f"shaping time {v!r} not in {SHAPING_TIME_OPTS}")
        return v

    @field_validator("EHistoNbin")
    @classmethod
    def _v_ehisto(cls, v: str) -> str:
        if v not in EHISTO_NBIN_OPTS:
            raise ValueError(f"EHistoNbin={v!r} not in {EHISTO_NBIN_OPTS}")
        return v

    @field_validator("ToAHistoNbin")
    @classmethod
    def _v_toahisto(cls, v: str) -> str:
        if v not in TOA_HISTO_NBIN_OPTS:
            raise ValueError(f"ToAHistoNbin={v!r} not in {TOA_HISTO_NBIN_OPTS}")
        return v

    @field_validator("MCSHistoNbin")
    @classmethod
    def _v_mcs(cls, v: str) -> str:
        if v not in MCS_HISTO_NBIN_OPTS:
            raise ValueError(f"MCSHistoNbin={v!r} not in {MCS_HISTO_NBIN_OPTS}")
        return v

    @field_validator("HoldDelay", "MuxClkPeriod", "ToAHistoMin", mode="before")
    @classmethod
    def _v_units(cls, v: Any) -> str:
        return _normalize_unit_string(v)


# ---------------------------------------------------------------------------
# [Test-Probe]  (all global params)
# ---------------------------------------------------------------------------
class TestProbeConfig(_Base):
    """[Test-Probe] global parameters."""

    AnalogProbe0: str = "OFF"
    DigitalProbe0: str = "OFF"
    ProbeChannel0: int = Field(0, ge=0, le=63)
    AnalogProbe1: str = "OFF"
    DigitalProbe1: str = "OFF"
    ProbeChannel1: int = Field(32, ge=0, le=63)
    TestPulseSource: str = "EXT"
    TestPulseAmplitude: int = Field(300, ge=0, le=4095)
    TestPulseDestination: str = "ALL"
    TestPulsePreamp: str = "BOTH"

    @field_validator("AnalogProbe0", "AnalogProbe1")
    @classmethod
    def _v_aprobe(cls, v: str) -> str:
        if v not in ANALOG_PROBE_OPTS:
            raise ValueError(f"analog probe {v!r} not in {ANALOG_PROBE_OPTS}")
        return v

    @field_validator("DigitalProbe0", "DigitalProbe1")
    @classmethod
    def _v_dprobe(cls, v: str) -> str:
        if v not in DIGITAL_PROBE_OPTS:
            raise ValueError(f"digital probe {v!r} not in {DIGITAL_PROBE_OPTS}")
        return v

    @field_validator("TestPulseSource")
    @classmethod
    def _v_tpsrc(cls, v: str) -> str:
        if v not in TEST_PULSE_SOURCE_OPTS:
            raise ValueError(f"TestPulseSource={v!r} not in {TEST_PULSE_SOURCE_OPTS}")
        return v

    @field_validator("TestPulseDestination")
    @classmethod
    def _v_tpdest(cls, v: str) -> str:
        if v not in TEST_PULSE_DESTINATION_OPTS:
            raise ValueError(
                f"TestPulseDestination={v!r} not in the allowed option list "
                "(NONE, ALL, EVEN, ODD, 'CH 0'..'CH 63')"
            )
        return v

    @field_validator("TestPulsePreamp")
    @classmethod
    def _v_tppre(cls, v: str) -> str:
        if v not in TEST_PULSE_PREAMP_OPTS:
            raise ValueError(f"TestPulsePreamp={v!r} not in {TEST_PULSE_PREAMP_OPTS}")
        return v


def _ch_list(default: int) -> list[int]:
    """Build a default per-channel list of length NUM_CHANNELS."""
    return [default] * NUM_CHANNELS


class BoardConfig(_Base):
    """Per-board connection path plus all board-scoped ('b') and channel-scoped
    ('c') parameter overrides.

    Board ('b') parameters are single values applied to the whole board.
    Channel ('c') parameters are lists of exactly :data:`NUM_CHANNELS` values.
    All fields keep the verbatim ferslib parameter name.
    """

    # [Connect] -- 'b'
    Open: str = "eth:192.168.50.3"

    # [HV_bias] -- 'b'
    HV_Vbias: UnitStr = "62.5 V"
    HV_Imax: UnitStr = "10.0 mA"

    # [HV_bias] -- 'c'
    HV_IndivAdj: list[int] = Field(default_factory=lambda: _ch_list(128))

    # [AcqMode] -- 'b' (hex masks)
    ChEnableMask0: str = "FFFFFFFF"
    ChEnableMask1: str = "FFFFFFFF"

    # [Discr] -- 'b'
    TD_CoarseThreshold: int = Field(185, ge=0, le=2047)
    Tlogic_Mask0: str = "FFFFFFFF"
    Tlogic_Mask1: str = "FFFFFFFF"
    Q_DiscrMask0: str = "FFFFFFFF"
    Q_DiscrMask1: str = "FFFFFFFF"

    # [Discr] -- 'c'
    TD_FineThreshold: list[int] = Field(default_factory=lambda: _ch_list(0))
    QD_FineThreshold: list[int] = Field(default_factory=lambda: _ch_list(0))

    # [Spectroscopy] -- 'c'
    HG_Gain: list[int] = Field(default_factory=lambda: _ch_list(51))
    LG_Gain: list[int] = Field(default_factory=lambda: _ch_list(51))
    ZS_Threshold_LG: list[int] = Field(default_factory=lambda: _ch_list(0))
    ZS_Threshold_HG: list[int] = Field(default_factory=lambda: _ch_list(0))

    # Names of channel-scoped ('c') fields, in legacy emission order.
    _CHANNEL_FIELDS: ClassVar[tuple[str, ...]] = (
        "HV_IndivAdj",
        "TD_FineThreshold",
        "QD_FineThreshold",
        "HG_Gain",
        "LG_Gain",
        "ZS_Threshold_LG",
        "ZS_Threshold_HG",
    )
    # Names of hex-mask ('h') board fields.
    _HEX_FIELDS: ClassVar[tuple[str, ...]] = (
        "ChEnableMask0",
        "ChEnableMask1",
        "Tlogic_Mask0",
        "Tlogic_Mask1",
        "Q_DiscrMask0",
        "Q_DiscrMask1",
    )
    # Names of unit ('u') board fields, kept verbatim.
    _UNIT_FIELDS: ClassVar[tuple[str, ...]] = ("HV_Vbias", "HV_Imax")
    # Names of plain-int ('d') board fields (single value).
    _INT_FIELDS: ClassVar[tuple[str, ...]] = ("TD_CoarseThreshold",)
    # Per-channel field range bounds (inclusive) -> (lo, hi).
    _CH_RANGES: ClassVar[dict[str, tuple[int, int]]] = {
        "HV_IndivAdj": (0, 255),
        "TD_FineThreshold": (0, 15),
        "QD_FineThreshold": (0, 4095),
        "HG_Gain": (1, 63),
        "LG_Gain": (1, 63),
        "ZS_Threshold_LG": (0, 65535),
        "ZS_Threshold_HG": (0, 65535),
    }

    @field_validator(
        "ChEnableMask0",
        "ChEnableMask1",
        "Tlogic_Mask0",
        "Tlogic_Mask1",
        "Q_DiscrMask0",
        "Q_DiscrMask1",
        mode="before",
    )
    @classmethod
    def _v_hex(cls, v: Any) -> str:
        return _hex_str(v)

    @field_validator("HV_Vbias", "HV_Imax", mode="before")
    @classmethod
    def _v_units(cls, v: Any) -> str:
        return _normalize_unit_string(v)

    @field_validator(
        "HV_IndivAdj",
        "TD_FineThreshold",
        "QD_FineThreshold",
        "HG_Gain",
        "LG_Gain",
        "ZS_Threshold_LG",
        "ZS_Threshold_HG",
        mode="before",
    )
    @classmethod
    def _v_ch_list(cls, v: Any, info: Any) -> list[int]:
        """Normalize a per-channel field to a 64-element list.

        Accepted input forms (the model is always stored as a length-64 list):
          * a scalar int            -> broadcast to all 64 channels;
          * a ``{default, overrides}`` mapping -> ``default`` everywhere, with
            ``overrides`` a ``{channel: value}`` map for the few that differ;
          * an explicit 64-element list.
        The first two are the compact on-disk forms emitted by ``save_config``.
        """
        name = info.field_name
        if isinstance(v, bool):
            raise ValueError(f"{name}: boolean is not a valid channel value")
        if isinstance(v, int):
            values = [v] * NUM_CHANNELS
        elif isinstance(v, dict):
            default = int(v.get("default", 0))
            values = [default] * NUM_CHANNELS
            overrides = v.get("overrides") or {}
            if not isinstance(overrides, dict):
                raise ValueError(f"{name}: 'overrides' must be a {{channel: value}} map")
            for k, val in overrides.items():
                ch = int(k)
                if not (0 <= ch < NUM_CHANNELS):
                    raise ValueError(
                        f"{name}: override channel {ch} out of range [0, {NUM_CHANNELS - 1}]"
                    )
                values[ch] = int(val)
        elif isinstance(v, (list, tuple)):
            if len(v) != NUM_CHANNELS:
                raise ValueError(
                    f"{name}: per-channel list must have exactly {NUM_CHANNELS} "
                    f"entries, got {len(v)}"
                )
            # accept str entries (e.g. from the legacy parser) with base-0 ints
            values = [int(x, 0) if isinstance(x, str) else int(x) for x in v]
        else:
            raise ValueError(
                f"{name}: expected an int (broadcast), a {{default, overrides}} map, "
                f"or a {NUM_CHANNELS}-element list"
            )
        lo, hi = cls._CH_RANGES.get(name, (None, None))
        if lo is not None:
            for i, x in enumerate(values):
                if not (lo <= x <= hi):
                    raise ValueError(
                        f"{name}[{i}]={x} out of range [{lo}, {hi}]"
                    )
        return values


class BaseHydraConfig(_Base):
    """Shared interface and plumbing for every board-family config (§0).

    Both :class:`HydraConfig` (A5202) and ``HydraConfig5203`` (A5203) subclass
    this so the engine / ``pyfers.System`` can treat any config uniformly through
    :meth:`board_paths` / :meth:`to_ferslib_params` / :meth:`to_legacy_txt`.
    The ``board_family`` discriminator (declared per subclass as a ``Literal``)
    lets the loader pick the right model from the YAML.

    Subclasses MUST define a ``board_family`` discriminator field, a ``boards``
    list (each item exposing ``Open``) and implement :meth:`to_ferslib_params`.
    """

    version: int = 1

    def board_paths(self) -> list[str]:
        """Return the per-board connection strings, ordered by board index.

        These are the verbatim ferslib ``Open`` values (e.g. ``"eth:192.168.50.3"``,
        ``"usb:0"``, ``"tdl:0:0:0"``) and are consumed by
        :meth:`pyfers.System.from_config` to open every board (CONTRACT.md §2).
        """
        return [board.Open for board in self.boards]

    def to_ferslib_params(self) -> list[tuple[int, str, str]]:
        """Flatten to ``(board_index, param_name, value_str)`` tuples.

        Implemented per family (the section sets differ). See subclasses.
        """
        raise NotImplementedError

    def to_legacy_txt(self) -> str:
        """Serialize to the legacy ``Janus_Config.txt`` text format."""
        # local import to avoid a circular dependency at module import time
        from hydrafers.config.converter import render_legacy_txt

        return render_legacy_txt(self)


class HydraConfig(BaseHydraConfig):
    """Top-level HydraFERS configuration for the **A5202** family (CONTRACT.md §2).

    Mirrors ``docs/param_defs_reference.txt``: global params grouped into the
    section sub-models, plus a list of per-board overrides (connection path,
    board-scoped and channel-scoped params).

    Kept named ``HydraConfig`` (the default/primary family) for backward
    compatibility; the sibling ``HydraConfig5203`` covers the picoTDC family.
    """

    board_family: Literal[5202] = FAMILY_5202
    boards: list[BoardConfig] = Field(default_factory=lambda: [BoardConfig()])
    hv_bias: HVBiasConfig = Field(default_factory=HVBiasConfig)
    run_ctrl: RunCtrlConfig = Field(default_factory=RunCtrlConfig)
    output_files: OutputFilesConfig = Field(default_factory=OutputFilesConfig)
    acq_mode: AcqModeConfig = Field(default_factory=AcqModeConfig)
    discr: DiscrConfig = Field(default_factory=DiscrConfig)
    spectroscopy: SpectroscopyConfig = Field(default_factory=SpectroscopyConfig)
    test_probe: TestProbeConfig = Field(default_factory=TestProbeConfig)

    @model_validator(mode="after")
    def _at_least_one_board(self) -> "HydraConfig":
        if not self.boards:
            raise ValueError("at least one board must be defined in 'boards'")
        return self

    # ------------------------------------------------------------------
    # Flatten / serialize
    # ------------------------------------------------------------------
    def to_ferslib_params(self) -> list[tuple[int, str, str]]:
        """Flatten to ``(board_index, param_name, value_str)`` tuples.

        Global params use ``board_index=0`` but apply to all boards (the engine
        replays them per handle). Board-scoped params use the real board index.
        Channel-scoped params produce one tuple per channel using the indexed
        ferslib name form ``"<Name>[<ch>]"``. Hex masks are emitted with a
        ``0x`` prefix; unit params are emitted verbatim. Monitor ('m') params
        are never emitted.
        """
        params: list[tuple[int, str, str]] = []

        # Global section params (board_index=0, applies to all).
        for section in (
            self.hv_bias,
            self.run_ctrl,
            self.output_files,
            self.acq_mode,
            self.discr,
            self.spectroscopy,
            self.test_probe,
        ):
            for name, value in section.__dict__.items():
                params.append((0, name, _scalar_to_str(value)))

        # Per-board and per-channel params.
        for b_idx, board in enumerate(self.boards):
            # connection path
            params.append((b_idx, "Open", board.Open))
            # board-scoped unit params (verbatim)
            for name in BoardConfig._UNIT_FIELDS:
                params.append((b_idx, name, getattr(board, name)))
            # board-scoped hex masks (prefixed 0x)
            for name in BoardConfig._HEX_FIELDS:
                params.append((b_idx, name, "0x" + getattr(board, name)))
            # board-scoped plain int
            params.append((b_idx, "TD_CoarseThreshold", str(board.TD_CoarseThreshold)))
            # channel-scoped arrays -> one tuple per channel
            for name in BoardConfig._CHANNEL_FIELDS:
                values = getattr(board, name)
                for ch, val in enumerate(values):
                    params.append((b_idx, f"{name}[{ch}]", str(val)))

        return params


def _scalar_to_str(value: Any) -> str:
    """Render a single scalar param value as the verbatim ferslib value string."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        # avoid trailing ".0" noise where the value is integral
        if value.is_integer():
            return str(int(value))
        return repr(value)
    return str(value)

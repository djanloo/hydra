"""Pydantic v2 schema for the **A5203 (picoTDC)** board family (CONTRACT.md §2).

Layer: ``hydrafers.config`` -- pure Python (pydantic v2 only). NO pyfers/Qt import.

The A5203 is timing-only (no SiPM, no HV, no spectroscopy): up to 128 channels of
picoTDC list data with Lead/Trail/ToT histograms. Its parameter set is disjoint
from the A5202 (see ``docs/A5203_INTEGRATION_STUDY.md`` §2.2), so it gets its own
section models and its own :class:`HydraConfig5203` sibling of
:class:`hydrafers.config.schema.HydraConfig`. Both share the
:class:`~hydrafers.config.schema.BaseHydraConfig` interface so the engine and
``pyfers.System`` treat either family uniformly.

Field names are kept IDENTICAL to the ferslib parameter names (param_defs of
janus-5203), because they are passed verbatim to ``pyfers.set_param``.
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from hydrafers.config.schema import (
    FAMILY_5203,
    BaseHydraConfig,
    UnitStr,
    _Base,
    _hex_str,
    _normalize_unit_string,
    _scalar_to_str,
)

# The A5203 carries two picoTDCs of 64 channels each (FERSLIB_MAX_NCH_5203).
NUM_CHANNELS_5203: int = 128


# ---------------------------------------------------------------------------
# Combo option lists (VERBATIM from janus-5203 bin/param_defs.txt).
# ---------------------------------------------------------------------------
START_RUN_MODE_OPTS_5203 = ("ASYNC", "TDL")
STOP_RUN_MODE_OPTS = ("MANUAL", "PRESET_TIME", "PRESET_COUNTS")
EVENT_BUILDING_MODE_OPTS = ("DISABLED", "TRGTIME_SORTING", "TRGID_SORTING")
OF_OUTFILE_UNIT_OPTS = ("LSB", "ns")
ACQUISITION_MODE_OPTS_5203 = (
    "COMMON_START",
    "COMMON_STOP",
    "TRG_MATCHING",
    "STREAMING",
    "TEST_MODE_1",
    "TEST_MODE_2",
)
MEAS_MODE_OPTS = ("LEAD_ONLY", "LEAD_TRAIL", "LEAD_TOT8", "LEAD_TOT11")
EN_HEAD_TRAIL_OPTS = ("KEEP_ALL", "ONE_WORD")
TRIGGER_SOURCE_OPTS_5203 = ("SW_ONLY", "T1-IN", "T0-IN", "PTRG", "EDGE_CONN", "MASK")
TREF_SOURCE_OPTS_5203 = ("CH0", "T0-IN", "T1-IN", "PTRG")
VETO_SOURCE_OPTS_5203 = ("DISABLED", "T0-IN", "T1-IN", "MASK")
DIGITAL_PROBE_OPTS_5203 = (
    "CLK_1024",
    "TRG_ACCEPTED",
    "TRG_REJECTED",
    "TX_DATA_VALID",
    "TX_PCK_COMMIT",
    "TX_PCK_ACCEPTED",
    "TX_PCK_REJECTED",
    "TDC_DATA_VALID",
    "TDC_DATA_COMMIT",
)
T_OUT_OPTS_5203 = (
    "T0-IN",
    "T1-IN",
    "TRIGGER",
    "RUN",
    "PTRG",
    "BUSY",
    "DPROBE",
    "SQ_WAVE",
    "TDL_SYNC",
    "RUN_SYNC",
    "ZERO",
    "MASK",
)
GLITCH_FILTER_MODE_OPTS = ("DISABLED", "TRAILING", "LEADING", "BOTH")
TDC_CH_BUFFER_SIZE_OPTS = ("4", "8", "16", "32", "64", "128", "256", "512")
HIGH_RES_CLOCK_OPTS = ("DISABLED", "DAISY_CHAIN", "FAN_OUT")
DATA_ANALYSIS_OPTS_5203 = ("NONE", "CNT_ONLY", "CNT+MEAS", "CNT+HISTO", "ALL")
LEADTRAIL_HISTO_NBIN_OPTS = ("256", "512", "1K", "2K", "4K", "8K", "16K")
TOT_HISTO_NBIN_OPTS = ("256", "512", "1K", "2K", "4K", "8K", "16K")
REBIN_OPTS = ("1", "2", "4", "8", "16", "32", "64")
ADAPTER_TYPE_OPTS = ("NONE", "A5256")
A5256_POLARITY_OPTS = ("POSITIVE", "NEGATIVE")


def _combo_validator(field_name: str, options: tuple[str, ...]):
    """Build a reusable pydantic field validator that checks a combo option."""

    def _v(cls, v: str) -> str:
        if v not in options:
            raise ValueError(f"{field_name}={v!r} not in allowed options {options}")
        return v

    return _v


# ---------------------------------------------------------------------------
# [RunCtrl] (5203) -- note TrgTimeWindow (vs the 5202 TstampCoincWindow)
# ---------------------------------------------------------------------------
class RunCtrl5203Config(_Base):
    """[RunCtrl] global parameters for the A5203."""

    StartRunMode: str = "ASYNC"
    StopRunMode: str = "MANUAL"
    EventBuildingMode: str = "DISABLED"
    TrgTimeWindow: UnitStr = "100 ns"
    PresetTime: UnitStr = "0"
    PresetCounts: float = 0.0
    JobFirstRun: int = 0
    JobLastRun: int = 0
    RunSleep: UnitStr = "0"
    EnableJobs: int = Field(0, ge=0, le=1)
    RunNumber_AutoIncr: int = Field(0, ge=0, le=1)

    _v_start = field_validator("StartRunMode")(
        classmethod(_combo_validator("StartRunMode", START_RUN_MODE_OPTS_5203))
    )
    _v_stop = field_validator("StopRunMode")(
        classmethod(_combo_validator("StopRunMode", STOP_RUN_MODE_OPTS))
    )
    _v_ebm = field_validator("EventBuildingMode")(
        classmethod(_combo_validator("EventBuildingMode", EVENT_BUILDING_MODE_OPTS))
    )

    @field_validator("TrgTimeWindow", "PresetTime", "RunSleep", mode="before")
    @classmethod
    def _v_units(cls, v: Any) -> str:
        return _normalize_unit_string(v)


# ---------------------------------------------------------------------------
# [OutputFiles] (5203) -- OF_LeadHisto/OF_ToTHisto instead of the 5202 histos
# ---------------------------------------------------------------------------
class OutputFiles5203Config(_Base):
    """[OutputFiles] global parameters for the A5203."""

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
    OF_LeadHisto: int = Field(0, ge=0, le=1)
    OF_ToTHisto: int = Field(0, ge=0, le=1)

    _v_ofu = field_validator("OF_OutFileUnit")(
        classmethod(_combo_validator("OF_OutFileUnit", OF_OUTFILE_UNIT_OPTS))
    )

    @field_validator("OF_MaxSize", mode="before")
    @classmethod
    def _v_maxsize(cls, v: Any) -> str:
        return _normalize_unit_string(v)


# ---------------------------------------------------------------------------
# [AcqMode] (5203)  (ChEnableMask0..3 are board-scoped on Board5203Config)
# ---------------------------------------------------------------------------
class AcqMode5203Config(_Base):
    """[AcqMode] global parameters for the A5203 (picoTDC timing)."""

    AcquisitionMode: str = "COMMON_START"
    MeasMode: str = "LEAD_ONLY"
    En_Head_Trail: str = "ONE_WORD"
    En_Empty_Ev_Suppr: int = Field(0, ge=0, le=1)
    TriggerSource: str = "PTRG"
    TrefSource: str = "PTRG"
    VetoSource: str = "DISABLED"
    GateWidth: UnitStr = "2 us"
    TrgWindowWidth: UnitStr = "2 us"
    TrgWindowOffset: UnitStr = "-1 us"
    PtrgPeriod: UnitStr = "10 us"
    DigitalProbe0: str = "TRG_ACCEPTED"
    DigitalProbe1: str = "TX_DATA_VALID"
    T0_Out: str = "PTRG"
    T1_Out: str = "ZERO"

    _v_acq = field_validator("AcquisitionMode")(
        classmethod(_combo_validator("AcquisitionMode", ACQUISITION_MODE_OPTS_5203))
    )
    _v_meas = field_validator("MeasMode")(
        classmethod(_combo_validator("MeasMode", MEAS_MODE_OPTS))
    )
    _v_hd = field_validator("En_Head_Trail")(
        classmethod(_combo_validator("En_Head_Trail", EN_HEAD_TRAIL_OPTS))
    )
    _v_trig = field_validator("TriggerSource")(
        classmethod(_combo_validator("TriggerSource", TRIGGER_SOURCE_OPTS_5203))
    )
    _v_tref = field_validator("TrefSource")(
        classmethod(_combo_validator("TrefSource", TREF_SOURCE_OPTS_5203))
    )
    _v_veto = field_validator("VetoSource")(
        classmethod(_combo_validator("VetoSource", VETO_SOURCE_OPTS_5203))
    )
    _v_dp0 = field_validator("DigitalProbe0")(
        classmethod(_combo_validator("DigitalProbe0", DIGITAL_PROBE_OPTS_5203))
    )
    _v_dp1 = field_validator("DigitalProbe1")(
        classmethod(_combo_validator("DigitalProbe1", DIGITAL_PROBE_OPTS_5203))
    )
    _v_t0 = field_validator("T0_Out")(
        classmethod(_combo_validator("T0_Out", T_OUT_OPTS_5203))
    )
    _v_t1 = field_validator("T1_Out")(
        classmethod(_combo_validator("T1_Out", T_OUT_OPTS_5203))
    )

    @field_validator(
        "GateWidth", "TrgWindowWidth", "TrgWindowOffset", "PtrgPeriod", mode="before"
    )
    @classmethod
    def _v_units(cls, v: Any) -> str:
        return _normalize_unit_string(v)


# ---------------------------------------------------------------------------
# [TDC] (5203)  (GlitchFilterDelay is board-scoped on Board5203Config)
# ---------------------------------------------------------------------------
class TDCConfig(_Base):
    """[TDC] global parameters for the A5203 picoTDC."""

    GlitchFilterMode: str = "DISABLED"
    ToT_reject_low_thr: int = Field(0, ge=0)
    ToT_reject_high_thr: int = Field(0, ge=0)
    TDC_ChannelBufferSize: str = "128"
    TriggerBufferSize: int = Field(16, ge=0)
    TDCpulser_Width: UnitStr = "1 ns"
    TDCpulser_Period: UnitStr = "10 ns"
    HighResClock: str = "DISABLED"

    _v_gf = field_validator("GlitchFilterMode")(
        classmethod(_combo_validator("GlitchFilterMode", GLITCH_FILTER_MODE_OPTS))
    )
    _v_buf = field_validator("TDC_ChannelBufferSize")(
        classmethod(_combo_validator("TDC_ChannelBufferSize", TDC_CH_BUFFER_SIZE_OPTS))
    )
    _v_clk = field_validator("HighResClock")(
        classmethod(_combo_validator("HighResClock", HIGH_RES_CLOCK_OPTS))
    )

    @field_validator("TDCpulser_Width", "TDCpulser_Period", mode="before")
    @classmethod
    def _v_units(cls, v: Any) -> str:
        return _normalize_unit_string(v)


# ---------------------------------------------------------------------------
# [DataAnalysis] (5203) -- Lead/Trail + ToT histogram controls
# ---------------------------------------------------------------------------
class DataAnalysis5203Config(_Base):
    """[DataAnalysis] global parameters for the A5203 (Lead/Trail/ToT histos)."""

    DataAnalysis: str = "ALL"
    LeadTrail_LSB: int = Field(0, ge=0, le=10)
    LeadTrailHistoNbin: str = "4K"
    LeadTrailRebin: str = "1"
    LeadHistoMin: UnitStr = "0 ns"
    ToT_LSB: int = Field(0, ge=0, le=18)
    ToTHistoNbin: str = "1K"
    ToTRebin: str = "1"
    ToTHistoMin: UnitStr = "0 ns"
    EnableWalkCorrection: int = Field(0, ge=0, le=1)
    WalkFitCoeff: str = "1.23E-12 33.33 1e-2"

    _v_da = field_validator("DataAnalysis")(
        classmethod(_combo_validator("DataAnalysis", DATA_ANALYSIS_OPTS_5203))
    )
    _v_lt = field_validator("LeadTrailHistoNbin")(
        classmethod(_combo_validator("LeadTrailHistoNbin", LEADTRAIL_HISTO_NBIN_OPTS))
    )
    _v_ltr = field_validator("LeadTrailRebin")(
        classmethod(_combo_validator("LeadTrailRebin", REBIN_OPTS))
    )
    _v_tot = field_validator("ToTHistoNbin")(
        classmethod(_combo_validator("ToTHistoNbin", TOT_HISTO_NBIN_OPTS))
    )
    _v_totr = field_validator("ToTRebin")(
        classmethod(_combo_validator("ToTRebin", REBIN_OPTS))
    )

    @field_validator("LeadHistoMin", "ToTHistoMin", mode="before")
    @classmethod
    def _v_units(cls, v: Any) -> str:
        return _normalize_unit_string(v)


# ---------------------------------------------------------------------------
# [Adapters] (5203) -- A5256 external discriminator adapter (DiscrThreshold is 'c')
# ---------------------------------------------------------------------------
class Adapters5203Config(_Base):
    """[Adapters] global parameters for the A5203 (DiscrThreshold is per-channel)."""

    AdapterType: str = "NONE"
    DisableThresholdCalib: int = Field(0, ge=0, le=1)
    A5256_Ch0Polarity: str = "POSITIVE"

    _v_at = field_validator("AdapterType")(
        classmethod(_combo_validator("AdapterType", ADAPTER_TYPE_OPTS))
    )
    _v_pol = field_validator("A5256_Ch0Polarity")(
        classmethod(_combo_validator("A5256_Ch0Polarity", A5256_POLARITY_OPTS))
    )


def _ch_list_5203(default: float) -> list[float]:
    """Build a default per-channel list of length NUM_CHANNELS_5203."""
    return [float(default)] * NUM_CHANNELS_5203


class Board5203Config(_Base):
    """Per-board connection path plus A5203 board-/channel-scoped overrides.

    Board ('b'): connection path, the four 32-bit channel-enable masks (128 ch),
    and the glitch-filter delay. Channel ('c'): the A5256 adapter discriminator
    threshold (mV), one value per channel.
    """

    # [Connect] -- 'b'
    Open: str = "eth:192.168.50.3"

    # [AcqMode] -- 'b' (four hex masks cover 128 channels)
    ChEnableMask0: str = "FFFFFFFF"
    ChEnableMask1: str = "FFFFFFFF"
    ChEnableMask2: str = "FFFFFFFF"
    ChEnableMask3: str = "FFFFFFFF"

    # [TDC] -- 'b'
    GlitchFilterDelay: int = Field(3, ge=0, le=15)

    # [Adapters] -- 'c' (A5256 discriminator threshold in mV, per channel)
    DiscrThreshold: list[float] = Field(default_factory=lambda: _ch_list_5203(10.0))

    # Names of channel-scoped ('c') fields, in legacy emission order.
    _CHANNEL_FIELDS: ClassVar[tuple[str, ...]] = ("DiscrThreshold",)
    # Names of hex-mask ('h') board fields.
    _HEX_FIELDS: ClassVar[tuple[str, ...]] = (
        "ChEnableMask0",
        "ChEnableMask1",
        "ChEnableMask2",
        "ChEnableMask3",
    )
    # Plain-int ('d') board fields (single value).
    _INT_FIELDS: ClassVar[tuple[str, ...]] = ("GlitchFilterDelay",)
    # Unit ('u') board fields kept verbatim (none on the A5203).
    _UNIT_FIELDS: ClassVar[tuple[str, ...]] = ()

    @field_validator(
        "ChEnableMask0", "ChEnableMask1", "ChEnableMask2", "ChEnableMask3",
        mode="before",
    )
    @classmethod
    def _v_hex(cls, v: Any) -> str:
        return _hex_str(v)

    @field_validator("DiscrThreshold", mode="before")
    @classmethod
    def _v_discr(cls, v: Any, info: Any) -> list[float]:
        """Normalize DiscrThreshold to a 128-element float list.

        Accepts a scalar (broadcast), a ``{default, overrides}`` map, or an
        explicit 128-element list -- mirroring the 5202 per-channel forms.
        """
        name = info.field_name
        n = NUM_CHANNELS_5203
        if isinstance(v, bool):
            raise ValueError(f"{name}: boolean is not a valid threshold")
        if isinstance(v, (int, float)):
            return [float(v)] * n
        if isinstance(v, dict):
            default = float(v.get("default", 0.0))
            values = [default] * n
            overrides = v.get("overrides") or {}
            if not isinstance(overrides, dict):
                raise ValueError(f"{name}: 'overrides' must be a {{channel: value}} map")
            for k, val in overrides.items():
                ch = int(k)
                if not (0 <= ch < n):
                    raise ValueError(
                        f"{name}: override channel {ch} out of range [0, {n - 1}]"
                    )
                values[ch] = float(val)
            return values
        if isinstance(v, (list, tuple)):
            if len(v) != n:
                raise ValueError(
                    f"{name}: per-channel list must have exactly {n} entries, got {len(v)}"
                )
            return [float(x) for x in v]
        raise ValueError(
            f"{name}: expected a number (broadcast), a {{default, overrides}} map, "
            f"or a {n}-element list"
        )


class HydraConfig5203(BaseHydraConfig):
    """Top-level HydraFERS configuration for the **A5203** family (CONTRACT.md §2).

    Sibling of :class:`hydrafers.config.schema.HydraConfig`; both share the
    :class:`~hydrafers.config.schema.BaseHydraConfig` interface. Select this model
    by setting ``board_family: 5203`` at the top of the YAML.
    """

    board_family: Literal[5203] = FAMILY_5203
    boards: list[Board5203Config] = Field(default_factory=lambda: [Board5203Config()])
    run_ctrl: RunCtrl5203Config = Field(default_factory=RunCtrl5203Config)
    output_files: OutputFiles5203Config = Field(default_factory=OutputFiles5203Config)
    acq_mode: AcqMode5203Config = Field(default_factory=AcqMode5203Config)
    tdc: TDCConfig = Field(default_factory=TDCConfig)
    data_analysis: DataAnalysis5203Config = Field(default_factory=DataAnalysis5203Config)
    adapters: Adapters5203Config = Field(default_factory=Adapters5203Config)

    # Order in which global section sub-models are flattened/emitted.
    _GLOBAL_SECTION_ATTRS: ClassVar[tuple[str, ...]] = (
        "run_ctrl",
        "output_files",
        "acq_mode",
        "tdc",
        "data_analysis",
        "adapters",
    )

    @model_validator(mode="after")
    def _at_least_one_board(self) -> "HydraConfig5203":
        if not self.boards:
            raise ValueError("at least one board must be defined in 'boards'")
        return self

    def to_ferslib_params(self) -> list[tuple[int, str, str]]:
        """Flatten to ``(board_index, param_name, value_str)`` tuples (5203).

        Global params use ``board_index=0`` (the engine replays them per handle).
        Board-scoped params use the real index; channel-scoped params produce one
        ``"<Name>[<ch>]"`` tuple per channel. Hex masks get a ``0x`` prefix; unit
        params are emitted verbatim.
        """
        params: list[tuple[int, str, str]] = []

        for attr in self._GLOBAL_SECTION_ATTRS:
            section = getattr(self, attr)
            for name, value in section.__dict__.items():
                params.append((0, name, _scalar_to_str(value)))

        for b_idx, board in enumerate(self.boards):
            params.append((b_idx, "Open", board.Open))
            for name in Board5203Config._HEX_FIELDS:
                params.append((b_idx, name, "0x" + getattr(board, name)))
            for name in Board5203Config._INT_FIELDS:
                params.append((b_idx, name, str(getattr(board, name))))
            for name in Board5203Config._CHANNEL_FIELDS:
                values = getattr(board, name)
                for ch, val in enumerate(values):
                    params.append((b_idx, f"{name}[{ch}]", _scalar_to_str(val)))

        return params


__all__ = [
    "NUM_CHANNELS_5203",
    "RunCtrl5203Config",
    "OutputFiles5203Config",
    "AcqMode5203Config",
    "TDCConfig",
    "DataAnalysis5203Config",
    "Adapters5203Config",
    "Board5203Config",
    "HydraConfig5203",
]

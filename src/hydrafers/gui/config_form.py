"""hydrafers.gui.config_form — declarative config-editing widgets (CONTRACT.md §6).

Builds PySide6 editing widgets for every field in :mod:`hydrafers.config.schema`
from a compact field-spec table, so the GUI exposes the SAME parameter surface as
the legacy Janus tabs (AcqMode, Discr, Spectroscopy, RunCtrl, Output, HV, Test-Probe)
plus per-board / per-channel overrides.

Public widgets / models:
    * :class:`SectionForm`     — a grid of labelled inputs bound to one global
      section model (e.g. ``acq_mode``); ``load(model)`` fills it, ``values()``
      returns a dict suitable for the section constructor.
    * :class:`BoardParams`     — shared per-board parameter model (single source
      of truth for the board/channel dicts and the selected board index).
    * :class:`BoardScopeForm`  — one section's per-board scalars + per-channel
      arrays (broadcast value + an 8×8 dialog), all bound to a ``BoardParams``.

The board/channel params for each section (``BOARD_SCALARS`` / ``CHANNEL_ARRAYS``)
live on that section's own settings tab, next to its global params — matching the
legacy Janus tab layout rather than a separate catch-all tab.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from hydrafers.gui.icons import icon as _icon
from hydrafers.config.schema import (
    ACQUISITION_MODE_OPTS,
    ANALOG_PROBE_OPTS,
    BUNCH_TRG_SOURCE_OPTS,
    COUNTING_MODE_OPTS,
    DATA_ANALYSIS_OPTS,
    DIGITAL_PROBE_OPTS,
    EHISTO_NBIN_OPTS,
    EVENT_BUILDING_MODE_OPTS,
    EXT_RUN_LEVEL_OPTS,
    EXT_RUN_SOURCE_OPTS,
    FAST_SHAPER_INPUT_OPTS,
    GAIN_SELECT_OPTS,
    GPS_PPS_SOURCE_OPTS,
    HV_ADJUST_RANGE_OPTS,
    MCS_HISTO_NBIN_OPTS,
    NUM_CHANNELS,
    OF_OUTFILE_UNIT_OPTS,
    SHAPING_TIME_OPTS,
    START_RUN_MODE_OPTS,
    STOP_RUN_MODE_OPTS,
    T0_OUT_OPTS,
    T1_OUT_OPTS,
    TEMP_SENS_TYPE_OPTS,
    TEST_PULSE_DESTINATION_OPTS,
    TEST_PULSE_PREAMP_OPTS,
    TEST_PULSE_SOURCE_OPTS,
    TOA_HISTO_NBIN_OPTS,
    TREF_SOURCE_OPTS,
    TRG_ID_MODE_OPTS,
    TRIGGER_LOGIC_OPTS,
    VALIDATION_MODE_OPTS,
    VALIDATION_SOURCE_OPTS,
    VETO_SOURCE_OPTS,
    BoardConfig,
)
from hydrafers.config.schema_5203 import (
    A5256_POLARITY_OPTS,
    ACQUISITION_MODE_OPTS_5203,
    ADAPTER_TYPE_OPTS,
    DATA_ANALYSIS_OPTS_5203,
    DIGITAL_PROBE_OPTS_5203,
    EN_HEAD_TRAIL_OPTS,
    EVENT_BUILDING_MODE_OPTS as EVENT_BUILDING_MODE_OPTS_5203,
    GLITCH_FILTER_MODE_OPTS,
    HIGH_RES_CLOCK_OPTS,
    LEADTRAIL_HISTO_NBIN_OPTS,
    MEAS_MODE_OPTS,
    NUM_CHANNELS_5203,
    REBIN_OPTS,
    START_RUN_MODE_OPTS_5203,
    STOP_RUN_MODE_OPTS as STOP_RUN_MODE_OPTS_5203,
    T_OUT_OPTS_5203,
    TDC_CH_BUFFER_SIZE_OPTS,
    TOT_HISTO_NBIN_OPTS,
    TREF_SOURCE_OPTS_5203,
    TRIGGER_SOURCE_OPTS_5203,
    VETO_SOURCE_OPTS_5203,
    Board5203Config,
)


# ---------------------------------------------------------------------------
# Field specification
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FieldSpec:
    """Declarative description of one editable config field."""

    key: str
    label: str
    kind: str  # 'combo' | 'bool' | 'int' | 'float' | 'unit' | 'str' | 'hex'
    options: tuple[str, ...] = ()
    lo: int | None = None
    hi: int | None = None
    tip: str = ""


def combo(key, label, opts, tip=""):
    return FieldSpec(key, label, "combo", options=tuple(opts), tip=tip)


def boolean(key, label, tip=""):
    return FieldSpec(key, label, "bool", tip=tip)


def integer(key, label, lo=0, hi=2**31 - 1, tip=""):
    return FieldSpec(key, label, "int", lo=lo, hi=hi, tip=tip)


def real(key, label, tip=""):
    return FieldSpec(key, label, "float", tip=tip)


def unit(key, label, tip=""):
    return FieldSpec(key, label, "unit", tip=tip)


def text(key, label, tip=""):
    return FieldSpec(key, label, "str", tip=tip)


def hexmask(key, label, tip=""):
    return FieldSpec(key, label, "hex", tip=tip)


# ---------------------------------------------------------------------------
# Section field tables — one list per global config section.
# Order follows hydrafers.yaml / the legacy Janus tabs.
# ---------------------------------------------------------------------------
SECTION_SPECS: dict[str, list[FieldSpec]] = {
    "acq_mode": [
        combo("AcquisitionMode", "Acquisition Mode", ACQUISITION_MODE_OPTS,
              "Main acquisition mode of the board"),
        boolean("EnableToT", "Enable ToT",
                "Timing mode: 1 = ToA 16b + ToT 9b, 0 = ToA 25b"),
        boolean("EnableListZeroSuppr", "List Zero-Suppression",
                "Suppress events with 0 hits in timing list output"),
        combo("BunchTrgSource", "Bunch Trg Source", BUNCH_TRG_SOURCE_OPTS,
              "Bunch trigger source (spectroscopy / counting)"),
        combo("VetoSource", "Veto Source", VETO_SOURCE_OPTS,
              "Veto signal (inhibits bunch trigger, active high)"),
        combo("ValidationSource", "Validation Source", VALIDATION_SOURCE_OPTS,
              "Trigger validation signal source"),
        combo("ValidationMode", "Validation Mode", VALIDATION_MODE_OPTS,
              "ACCEPT: validate if signal in window; REJECT: reject if in window"),
        combo("CountingMode", "Counting Mode", COUNTING_MODE_OPTS,
              "SINGLES: per-channel self-trigger; PAIRED_AND: coincidence pairs"),
        unit("ChTrg_Width", "Ch Trg Width",
             "Coincidence window for PAIRED_AND (8–2032 ns, step 8 ns)"),
        boolean("EnableCntZeroSuppr", "Counting Zero-Suppr",
                "Suppress channels with 0 counts in COUNTING mode"),
        combo("TrgIdMode", "Trigger-ID Mode", TRG_ID_MODE_OPTS,
              "Trigger ID counts all triggers or only validation signals"),
        combo("TriggerLogic", "Trigger Logic", TRIGGER_LOGIC_OPTS,
              "Combinatorial trigger network over the 64 self-trigger inputs"),
        unit("Tlogic_Width", "Tlogic Width",
             "Trigger-logic output width (0 = linear output)"),
        integer("MajorityLevel", "Majority Level", 1, 64,
                "Majority threshold for MAJ trigger logic"),
        unit("PtrgPeriod", "Periodic Trg Period", "Period of internal periodic trigger"),
        combo("TrefSource", "Tref Source", TREF_SOURCE_OPTS,
              "Tref (common start/stop) source in timing mode"),
        unit("TrefWindow", "Tref Window", "Tref gate/window (8 ns steps)"),
        unit("TrefDelay", "Tref Delay", "Tref delay, can be negative (8 ns steps)"),
        combo("T0_Out", "T0 Output", T0_OUT_OPTS, "T0 LEMO output assignment"),
        combo("T1_Out", "T1 Output", T1_OUT_OPTS, "T1 LEMO output assignment"),
    ],
    "discr": [
        combo("FastShaperInput", "Fast Shaper Input", FAST_SHAPER_INPUT_OPTS,
              "Fast shaper input: high- or low-gain preamp"),
        unit("Hit_HoldOff", "Hit Hold-Off",
             "Trigger hold-off (imposed dead time)"),
        integer("QD_CoarseThreshold", "Q Coarse Threshold", 0, 65535,
                "Charge discriminator coarse threshold (all channels)"),
    ],
    "spectroscopy": [
        combo("GainSelect", "Gain Select", GAIN_SELECT_OPTS,
              "Output gain: HG only / LG only / auto / both"),
        integer("Pedestal", "Pedestal", 0, 65535,
                "Common pedestal (ADC reading with no signal)"),
        combo("HG_ShapingTime", "HG Shaping Time", SHAPING_TIME_OPTS,
              "Slow-shaper shaping time, high gain"),
        combo("LG_ShapingTime", "LG Shaping Time", SHAPING_TIME_OPTS,
              "Slow-shaper shaping time, low gain"),
        unit("HoldDelay", "Hold Delay",
             "Delay from bunch-trigger to hold (peak-detect window)"),
        unit("MuxClkPeriod", "Mux Clk Period", "Multiplexer readout speed (best 300 ns)"),
        combo("EHistoNbin", "PHA Histo Bins", EHISTO_NBIN_OPTS, "PHA histogram bin count"),
        combo("ToAHistoNbin", "ToA Histo Bins", TOA_HISTO_NBIN_OPTS,
              "ToA histogram bin count"),
        integer("ToARebin", "ToA Rebin", 1, 1024, "Rebin factor for ToA histogram"),
        unit("ToAHistoMin", "ToA Histo Min", "Minimum ToA value in the histogram"),
        combo("MCSHistoNbin", "MCS Histo Bins", MCS_HISTO_NBIN_OPTS,
              "MCS histogram bin count (counting mode)"),
    ],
    "hv_bias": [
        combo("HV_Adjust_Range", "HV Adjust Range", HV_ADJUST_RANGE_OPTS,
              "DAC range for individual HV adjust"),
        text("TempSensType", "Temp Sensor Type",
             "TMP37 / LM94021_G11 / LM94021_G00, or 'c0 c1 c2' coefficients"),
        real("TempFeedbackCoeff", "Temp Feedback Coeff",
             "Vbias temperature feedback (mV/°C)"),
        boolean("EnableTempFeedback", "Enable Temp Feedback",
                "Enable Vbias temperature feedback"),
    ],
    "run_ctrl": [
        combo("StartRunMode", "Start Run Mode", START_RUN_MODE_OPTS,
              "Run start synchronization mode"),
        combo("StopRunMode", "Stop Run Mode", STOP_RUN_MODE_OPTS, "Run stop mode"),
        unit("PresetTime", "Preset Time", "Run duration for PRESET_TIME stop mode"),
        real("PresetCounts", "Preset Counts", "Event count for PRESET_COUNTS stop mode"),
        combo("EventBuildingMode", "Event Building", EVENT_BUILDING_MODE_OPTS,
              "Event building: off / sort by timestamp / by trigger-ID"),
        unit("TstampCoincWindow", "Tstamp Coinc Window",
             "Coincidence window for timestamp event building"),
        combo("GPSPPSSource", "GPS PPS Source", GPS_PPS_SOURCE_OPTS, "PPS GPS source"),
        combo("ExtRunSource", "Ext Run Source", EXT_RUN_SOURCE_OPTS,
              "External source for the start-run signal"),
        combo("ExtRunLevel", "Ext Run Level", EXT_RUN_LEVEL_OPTS,
              "Logic level of the external run source"),
        text("GPSTimeUTC", "GPS Time UTC", "Start-run GPS time (UTC, ISO 8601)"),
        boolean("EnableJobs", "Enable Jobs", "Enable multi-run jobs"),
        integer("JobFirstRun", "Job First Run", 0, 9999, "First run of the job"),
        integer("JobLastRun", "Job Last Run", 0, 9999, "Last run of the job"),
        unit("RunSleep", "Run Sleep", "Wait time between job runs"),
        boolean("RunNumber_AutoIncr", "Auto-Increment Run #",
                "Auto-increment the run number after each run"),
    ],
    "output_files": [
        combo("DataAnalysis", "Data Analysis", DATA_ANALYSIS_OPTS,
              "Data analysis enable mask"),
        text("DataFilePath", "Data File Path", "Destination folder for output files"),
        combo("OF_OutFileUnit", "Out File Unit", OF_OUTFILE_UNIT_OPTS,
              "ToA/ToT unit in output (LSB or ns)"),
        boolean("OF_EnMaxSize", "Enable Max Size", "Enable list-file maximum size"),
        unit("OF_MaxSize", "Max File Size", "Max size of list files (min 1 MB)"),
        boolean("OF_RawData", "Raw Data", "Output raw event list"),
        boolean("OF_ListBin", "List (binary)", "Output event list, binary"),
        boolean("OF_ListAscii", "List (ASCII)", "Output event list, ASCII"),
        boolean("OF_ListCSV", "List (CSV)", "Output event list, CSV"),
        boolean("OF_Sync", "Sync Check", "Output BrdID-Tstamp-TrgID sync check"),
        boolean("OF_ServiceInfo", "Service Info", "Output service event info"),
        boolean("OF_RunInfo", "Run Info", "Output run info"),
        boolean("OF_SpectHisto", "PHA Spectrum", "Output PHA spectrum"),
        boolean("OF_ToAHisto", "ToA Spectrum", "Output ToA spectrum"),
        boolean("OF_ToTHisto", "ToT Spectrum", "Output ToT spectrum"),
        boolean("OF_MCS", "MCS Spectrum", "Output MCS spectrum"),
        boolean("OF_Staircase", "Staircase", "Output staircase"),
    ],
    "test_probe": [
        combo("AnalogProbe0", "Analog Probe 0", ANALOG_PROBE_OPTS, "Signal on analog probe 0"),
        combo("DigitalProbe0", "Digital Probe 0", DIGITAL_PROBE_OPTS, "Signal on digital probe 0"),
        integer("ProbeChannel0", "Probe Channel 0", 0, 63, "Channel connected to probes 0"),
        combo("AnalogProbe1", "Analog Probe 1", ANALOG_PROBE_OPTS, "Signal on analog probe 1"),
        combo("DigitalProbe1", "Digital Probe 1", DIGITAL_PROBE_OPTS, "Signal on digital probe 1"),
        integer("ProbeChannel1", "Probe Channel 1", 0, 63, "Channel connected to probes 1"),
        combo("TestPulseSource", "Test Pulse Source", TEST_PULSE_SOURCE_OPTS, "Test pulse source"),
        integer("TestPulseAmplitude", "Test Pulse Amplitude", 0, 4095,
                "DAC setting for internal test pulser (12-bit)"),
        combo("TestPulseDestination", "Test Pulse Dest", TEST_PULSE_DESTINATION_OPTS,
              "Test pulse routing"),
        combo("TestPulsePreamp", "Test Pulse Preamp", TEST_PULSE_PREAMP_OPTS,
              "Test pulse feeds HG and/or LG preamps"),
    ],
}

# Section attribute name -> human title (for the Settings tab labels).
SECTION_TITLES: dict[str, str] = {
    "acq_mode": "Acquisition",
    "discr": "Discriminator",
    "spectroscopy": "Spectroscopy",
    "hv_bias": "HV / Bias",
    "run_ctrl": "Run Control",
    "output_files": "Output Files",
    "test_probe": "Test / Probe",
}

# Order of the settings sub-tabs for the A5202 family (after the Connection tab).
SECTION_ORDER_5202: tuple[str, ...] = (
    "acq_mode", "discr", "spectroscopy", "hv_bias",
    "run_ctrl", "output_files", "test_probe",
)


# ---------------------------------------------------------------------------
# A5203 (picoTDC) section field tables. Disjoint from the 5202 (no HV /
# spectroscopy / analog probes; adds TDC, Data Analysis and Adapters).
# ---------------------------------------------------------------------------
SECTION_SPECS_5203: dict[str, list[FieldSpec]] = {
    "acq_mode": [
        combo("AcquisitionMode", "Acquisition Mode", ACQUISITION_MODE_OPTS_5203,
              "picoTDC acquisition mode"),
        combo("MeasMode", "Measurement Mode", MEAS_MODE_OPTS,
              "Which edges/intervals the TDC captures (lead / lead+trail / lead+ToT)"),
        combo("En_Head_Trail", "Header/Trailer", EN_HEAD_TRAIL_OPTS,
              "Keep all header/trailer words or one-word trailer"),
        boolean("En_Empty_Ev_Suppr", "Empty-Event Suppr",
                "Suppress events with no hits"),
        combo("TriggerSource", "Trigger Source", TRIGGER_SOURCE_OPTS_5203,
              "Trigger source"),
        combo("TrefSource", "Tref Source", TREF_SOURCE_OPTS_5203,
              "Time-reference source"),
        combo("VetoSource", "Veto Source", VETO_SOURCE_OPTS_5203,
              "Veto signal (inhibits the trigger, active high)"),
        unit("GateWidth", "Gate Width", "Gate width (rounded to 12.8 ns steps)"),
        unit("TrgWindowWidth", "Trg Window Width", "Trigger window width (12.8 ns steps)"),
        unit("TrgWindowOffset", "Trg Window Offset",
             "Trigger window offset vs trigger (can be negative, 12.8 ns steps)"),
        unit("PtrgPeriod", "Periodic Trg Period", "Internal periodic-trigger period"),
        combo("DigitalProbe0", "Digital Probe 0", DIGITAL_PROBE_OPTS_5203,
              "T0-OUT digital probe source"),
        combo("DigitalProbe1", "Digital Probe 1", DIGITAL_PROBE_OPTS_5203,
              "T1-OUT digital probe source"),
        combo("T0_Out", "T0 Output", T_OUT_OPTS_5203, "T0 LEMO output assignment"),
        combo("T1_Out", "T1 Output", T_OUT_OPTS_5203, "T1 LEMO output assignment"),
    ],
    "tdc": [
        combo("GlitchFilterMode", "Glitch Filter", GLITCH_FILTER_MODE_OPTS,
              "Enforce minimum pulse width/distance on leading/trailing edges"),
        integer("ToT_reject_low_thr", "ToT Reject Low", 0, 2**31 - 1,
                "ToT reject lower threshold (0 = disabled)"),
        integer("ToT_reject_high_thr", "ToT Reject High", 0, 2**31 - 1,
                "ToT reject higher threshold (0 = disabled)"),
        combo("TDC_ChannelBufferSize", "Ch Buffer Size", TDC_CH_BUFFER_SIZE_OPTS,
              "Max hits buffered per channel"),
        integer("TriggerBufferSize", "Trigger Buffer Size", 0, 4096,
                "Pending-trigger FIFO depth"),
        unit("TDCpulser_Width", "TDC Pulser Width", "picoTDC pulser output width"),
        unit("TDCpulser_Period", "TDC Pulser Period", "picoTDC pulser output period"),
        combo("HighResClock", "High-Res Clock", HIGH_RES_CLOCK_OPTS,
              "High-resolution clock distribution (MCX connectors)"),
    ],
    "data_analysis": [
        combo("DataAnalysis", "Data Analysis", DATA_ANALYSIS_OPTS_5203,
              "Analysis depth (counts / measures / histograms)"),
        integer("LeadTrail_LSB", "Lead/Trail LSB", 0, 10,
                "Leading/trailing LSB exponent: LSB = 3.125 ps · 2^N (max N=10)"),
        combo("LeadTrailHistoNbin", "Lead/Trail Bins", LEADTRAIL_HISTO_NBIN_OPTS,
              "Lead/Trail histogram bin count"),
        combo("LeadTrailRebin", "Lead/Trail Rebin", REBIN_OPTS,
              "Lead/Trail histogram rebin factor"),
        unit("LeadHistoMin", "Lead Histo Min", "Minimum value in the Lead histogram"),
        integer("ToT_LSB", "ToT LSB", 0, 18,
                "ToT LSB exponent: LSB = 3.125 ps · 2^N (max N=18)"),
        combo("ToTHistoNbin", "ToT Bins", TOT_HISTO_NBIN_OPTS, "ToT histogram bin count"),
        combo("ToTRebin", "ToT Rebin", REBIN_OPTS, "ToT histogram rebin factor"),
        unit("ToTHistoMin", "ToT Histo Min", "Minimum value in the ToT histogram"),
        boolean("EnableWalkCorrection", "Walk Correction",
                "Enable time-walk correction by ToT"),
        text("WalkFitCoeff", "Walk Fit Coeff", "Walk-vs-ToT polynomial coefficients"),
    ],
    "adapters": [
        combo("AdapterType", "Adapter Type", ADAPTER_TYPE_OPTS,
              "External adapter (e.g. A5256 discriminator)"),
        boolean("DisableThresholdCalib", "Disable Thr Calib",
                "Disable discriminator threshold calibration"),
        combo("A5256_Ch0Polarity", "A5256 Ch0 Polarity", A5256_POLARITY_OPTS,
              "Input polarity of A5256 channel 0"),
    ],
    "run_ctrl": [
        combo("StartRunMode", "Start Run Mode", START_RUN_MODE_OPTS_5203,
              "Run start mode (ASYNC or TDL)"),
        combo("StopRunMode", "Stop Run Mode", STOP_RUN_MODE_OPTS_5203, "Run stop mode"),
        unit("PresetTime", "Preset Time", "Run duration for PRESET_TIME stop mode"),
        real("PresetCounts", "Preset Counts", "Event count for PRESET_COUNTS stop mode"),
        combo("EventBuildingMode", "Event Building", EVENT_BUILDING_MODE_OPTS_5203,
              "Event building: off / sort by timestamp / by trigger-ID"),
        unit("TrgTimeWindow", "Trg Time Window",
             "Coincidence window for timestamp event building"),
        boolean("EnableJobs", "Enable Jobs", "Enable multi-run jobs"),
        integer("JobFirstRun", "Job First Run", 0, 9999, "First run of the job"),
        integer("JobLastRun", "Job Last Run", 0, 9999, "Last run of the job"),
        unit("RunSleep", "Run Sleep", "Wait time between job runs"),
        boolean("RunNumber_AutoIncr", "Auto-Increment Run #",
                "Auto-increment the run number after each run"),
    ],
    "output_files": [
        text("DataFilePath", "Data File Path", "Destination folder for output files"),
        combo("OF_OutFileUnit", "Out File Unit", OF_OUTFILE_UNIT_OPTS,
              "ToA/ToT unit in output (LSB or ns)"),
        boolean("OF_EnMaxSize", "Enable Max Size", "Enable list-file maximum size"),
        unit("OF_MaxSize", "Max File Size", "Max size of list files (min 1 MB)"),
        boolean("OF_RawData", "Raw Data", "Output raw event list"),
        boolean("OF_ListBin", "List (binary)", "Output event list, binary"),
        boolean("OF_ListAscii", "List (ASCII)", "Output event list, ASCII"),
        boolean("OF_ListCSV", "List (CSV)", "Output event list, CSV"),
        boolean("OF_Sync", "Sync Check", "Output BrdID-Tstamp-TrgID sync check"),
        boolean("OF_ServiceInfo", "Service Info", "Output service event info"),
        boolean("OF_RunInfo", "Run Info", "Output run info"),
        boolean("OF_LeadHisto", "Lead Spectrum", "Output leading-edge timing spectrum"),
        boolean("OF_ToTHisto", "ToT Spectrum", "Output ToT spectrum"),
    ],
}

SECTION_TITLES_5203: dict[str, str] = {
    "acq_mode": "Acquisition",
    "tdc": "TDC",
    "data_analysis": "Data Analysis",
    "adapters": "Adapters",
    "run_ctrl": "Run Control",
    "output_files": "Output Files",
}

SECTION_ORDER_5203: tuple[str, ...] = (
    "acq_mode", "tdc", "data_analysis", "adapters", "run_ctrl", "output_files",
)


# ---------------------------------------------------------------------------
# Widget helpers
# ---------------------------------------------------------------------------
def _make_widget(spec: FieldSpec) -> QWidget:
    if spec.kind == "combo":
        w = QComboBox()
        w.addItems(list(spec.options))
        return w
    if spec.kind == "bool":
        return QCheckBox()
    if spec.kind == "int":
        w = QSpinBox()
        w.setRange(spec.lo if spec.lo is not None else 0,
                   spec.hi if spec.hi is not None else 2**31 - 1)
        return w
    if spec.kind == "float":
        w = QDoubleSpinBox()
        w.setRange(-1e12, 1e12)
        w.setDecimals(3)
        return w
    # unit / str / hex
    w = QLineEdit()
    if spec.kind == "hex":
        w.setMaxLength(8)
    return w


def _set_widget(w: QWidget, spec: FieldSpec, value) -> None:
    if spec.kind == "combo":
        i = w.findText(str(value))
        w.setCurrentIndex(i if i >= 0 else 0)
    elif spec.kind == "bool":
        w.setChecked(bool(int(value)))
    elif spec.kind == "int":
        w.setValue(int(value))
    elif spec.kind == "float":
        w.setValue(float(value))
    else:
        w.setText(str(value))


def _wire_change(w: QWidget, kind: str, slot) -> None:
    """Connect *w*'s user-edit signal to *slot*.

    For line edits we use ``textEdited`` (fires only on real user input, not on
    programmatic ``setText``); combos/spins are guarded by a ``_suppress`` flag
    in the owning form during ``load``.
    """
    if kind == "combo":
        w.currentIndexChanged.connect(slot)
    elif kind == "bool":
        w.toggled.connect(slot)
    elif kind in ("int", "float"):
        w.valueChanged.connect(slot)
    else:  # unit / str / hex
        w.textEdited.connect(slot)


def _widget_value(w: QWidget, spec: FieldSpec):
    if spec.kind == "combo":
        return w.currentText()
    if spec.kind == "bool":
        return 1 if w.isChecked() else 0
    if spec.kind == "int":
        return w.value()
    if spec.kind == "float":
        return float(w.value())
    if spec.kind == "hex":
        return w.text().strip().upper()
    return w.text()


# ---------------------------------------------------------------------------
# Section headers: an icon + title, with the content indented to line up under
# the title text (icon width + spacing) rather than under the icon.
# ---------------------------------------------------------------------------
SCOPE_GLOBAL_ICON = "mdi6.earth"            # applies to all boards
SCOPE_BOARD_ICON = "mdi6.developer-board"   # one value per board
SCOPE_CHANNEL_ICON = "mdi6.view-grid"       # one value per channel (64)

_HEADING_COLOR = "#607d8b"
_ICON_PX = 20
_ICON_GAP = 8
#: Left indent for a section's content so it aligns under the heading TEXT.
CONTENT_INDENT = _ICON_PX + _ICON_GAP


def _section_header(icon_name: str, text: str) -> QWidget:
    """A heading row: [icon] Title, with the icon at the start of the text."""
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 2)
    row.setSpacing(_ICON_GAP)
    ico = QLabel()
    ico.setFixedWidth(_ICON_PX)
    pm = _icon(icon_name, _HEADING_COLOR).pixmap(_ICON_PX, _ICON_PX)
    if not pm.isNull():
        ico.setPixmap(pm)
    row.addWidget(ico, 0, Qt.AlignmentFlag.AlignVCenter)
    lbl = QLabel(text)
    lbl.setObjectName("SectionHeading")
    row.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addStretch(1)
    return box


# ---------------------------------------------------------------------------
# SectionForm — one global config section
# ---------------------------------------------------------------------------
class SectionForm(QWidget):
    """Editable form bound to one global section model (e.g. ``acq_mode``).

    A plain widget (one ``#Card`` with a 2-column grid) so it can be stacked
    above per-board params inside a single scroll area on a settings tab.
    """

    #: Emitted when the user edits any field (not while ``load`` is filling it).
    changed = Signal()

    def __init__(self, specs: list[FieldSpec], title: str = "Global Parameters",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._specs = specs
        self._widgets: dict[str, QWidget] = {}
        self._suppress = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("Card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(18, 12, 18, 14)
        cv.setSpacing(8)
        cv.addWidget(_section_header(SCOPE_GLOBAL_ICON, title))

        grid = QGridLayout()
        grid.setContentsMargins(CONTENT_INDENT, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)

        # Two balanced columns: first half left (cols 0,1), rest right (cols 2,3).
        half = (len(specs) + 1) // 2
        for i, spec in enumerate(specs):
            col = 0 if i < half else 2
            row = i if i < half else i - half
            lbl = QLabel(spec.label + ":")
            lbl.setObjectName("FieldLabel")
            if spec.tip:
                lbl.setToolTip(spec.tip)
            w = _make_widget(spec)
            if spec.tip:
                w.setToolTip(spec.tip)
            self._widgets[spec.key] = w
            _wire_change(w, spec.kind, self._emit_changed)
            grid.addWidget(lbl, row, col, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(w, row, col + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        cv.addLayout(grid)

        outer.addWidget(card)

    def _emit_changed(self, *_) -> None:
        if not self._suppress:
            self.changed.emit()

    def load(self, model) -> None:
        self._suppress = True
        try:
            for spec in self._specs:
                _set_widget(self._widgets[spec.key], spec, getattr(model, spec.key))
        finally:
            self._suppress = False

    def values(self) -> dict:
        return {spec.key: _widget_value(self._widgets[spec.key], spec)
                for spec in self._specs}


# ---------------------------------------------------------------------------
# Per-channel array editor dialog (8×8 grid)
# ---------------------------------------------------------------------------
class ChannelArrayDialog(QDialog):
    """Modal grid editor for a per-channel array (64 or 128 channels, int/float).

    The grid is laid out 8 columns wide; the row count follows ``num_ch`` (64 ->
    8×8, 128 -> 16×8). Float arrays (e.g. the A5256 discriminator threshold) use
    double spin boxes.
    """

    _COLS = 8

    def __init__(self, title: str, values: list, lo: float, hi: float,
                 num_ch: int = NUM_CHANNELS, is_float: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._lo, self._hi = lo, hi
        self._is_float = is_float
        self._num_ch = max(1, int(num_ch))
        self._spins: list = []

        def _spin():
            sp = QDoubleSpinBox() if is_float else QSpinBox()
            sp.setRange(lo, hi)
            if is_float:
                sp.setDecimals(2)
            return sp

        v = QVBoxLayout(self)
        info = QLabel(f"{title}   (range {lo}–{hi}, {self._num_ch} ch)")
        info.setObjectName("CardTitle")
        v.addWidget(info)

        rows = (self._num_ch + self._COLS - 1) // self._COLS
        grid = QGridLayout()
        grid.setSpacing(4)
        for c in range(self._COLS):
            h = QLabel(f"+{c}")
            h.setObjectName("FieldLabel")
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(h, 0, c + 1)
        for r in range(rows):
            rh = QLabel(f"{r * self._COLS:>3}")
            rh.setObjectName("FieldLabel")
            grid.addWidget(rh, r + 1, 0)
            for c in range(self._COLS):
                ch = r * self._COLS + c
                if ch >= self._num_ch:
                    break
                sp = _spin()
                sp.setValue((float(values[ch]) if is_float else int(values[ch]))
                            if ch < len(values) else lo)
                sp.setFixedWidth(82)
                self._spins.append(sp)
                grid.addWidget(sp, r + 1, c + 1)
        v.addLayout(grid)

        # Fill-all helper
        fill_row = QHBoxLayout()
        fill_row.addWidget(QLabel("Set all to:"))
        self._fill = _spin()
        fill_row.addWidget(self._fill)
        btn_fill = QPushButton("Apply to all")
        btn_fill.clicked.connect(self._apply_all)
        fill_row.addWidget(btn_fill)
        fill_row.addStretch(1)
        v.addLayout(fill_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def _apply_all(self) -> None:
        val = self._fill.value()
        for sp in self._spins:
            sp.setValue(val)

    def values(self) -> list:
        return [sp.value() for sp in self._spins]


# ---------------------------------------------------------------------------
# Per-board / per-channel parameter groupings, BY SECTION.
# These live on each functional settings tab (matching the legacy Janus tabs),
# next to that section's global params — NOT in a separate catch-all tab.
# ---------------------------------------------------------------------------
# Per-board scalar overrides (Open is owned by the Connect page).
BOARD_SCALARS: dict[str, list[FieldSpec]] = {
    "acq_mode": [
        hexmask("ChEnableMask0", "Ch Enable Mask 0", "Channel enable mask, ch 0–31 (hex)"),
        hexmask("ChEnableMask1", "Ch Enable Mask 1", "Channel enable mask, ch 32–63 (hex)"),
    ],
    "discr": [
        integer("TD_CoarseThreshold", "Timing Coarse Threshold", 0, 2047,
                "Timing discriminator coarse threshold (all channels)"),
        hexmask("Tlogic_Mask0", "Tlogic Mask 0", "Trigger-logic mask, ch 0–31 (hex)"),
        hexmask("Tlogic_Mask1", "Tlogic Mask 1", "Trigger-logic mask, ch 32–63 (hex)"),
        hexmask("Q_DiscrMask0", "Q-OR Mask 0", "Q-OR mask, ch 0–31 (hex)"),
        hexmask("Q_DiscrMask1", "Q-OR Mask 1", "Q-OR mask, ch 32–63 (hex)"),
    ],
    "hv_bias": [
        unit("HV_Vbias", "HV Vbias", "Bias voltage (range 20–85 V)"),
        unit("HV_Imax", "HV Imax", "Max HV current before shutdown"),
    ],
}

# Per-channel arrays: (key, label, lo, hi).
CHANNEL_ARRAYS: dict[str, list[tuple[str, str, int, int]]] = {
    "discr": [
        ("TD_FineThreshold", "Timing Fine Threshold", 0, 15),
        ("QD_FineThreshold", "Charge Fine Threshold", 0, 4095),
    ],
    "spectroscopy": [
        ("HG_Gain", "High Gain", 1, 63),
        ("LG_Gain", "Low Gain", 1, 63),
        ("ZS_Threshold_LG", "ZS Threshold LG", 0, 65535),
        ("ZS_Threshold_HG", "ZS Threshold HG", 0, 65535),
    ],
    "hv_bias": [
        ("HV_IndivAdj", "HV Individual Adjust", 0, 255),
    ],
}


# --- A5203 per-board / per-channel parameter groupings -----------------------
# Channel-array entries may carry an optional 5th element "float" to mark a
# floating-point per-channel array (e.g. the A5256 discriminator threshold, mV).
BOARD_SCALARS_5203: dict[str, list[FieldSpec]] = {
    "acq_mode": [
        hexmask("ChEnableMask0", "Ch Enable Mask 0", "Channel enable mask, ch 0–31 (hex)"),
        hexmask("ChEnableMask1", "Ch Enable Mask 1", "Channel enable mask, ch 32–63 (hex)"),
        hexmask("ChEnableMask2", "Ch Enable Mask 2", "Channel enable mask, ch 64–95 (hex)"),
        hexmask("ChEnableMask3", "Ch Enable Mask 3", "Channel enable mask, ch 96–127 (hex)"),
    ],
    "tdc": [
        integer("GlitchFilterDelay", "Glitch Filter Delay", 0, 15,
                "Glitch-filter delay (~800 ps to ~10 ns, 16 steps)"),
    ],
}

CHANNEL_ARRAYS_5203: dict[str, list[tuple]] = {
    "adapters": [
        ("DiscrThreshold", "Discriminator Threshold (mV)", -1000, 1000, "float"),
    ],
}


# ---------------------------------------------------------------------------
# Per-family selection helpers. A config file targets exactly one family
# (never mixed); these return the right spec tables / board class / channel
# count so the GUI builders are written once and parameterized by family.
# ---------------------------------------------------------------------------
def section_order(family: int) -> tuple[str, ...]:
    return SECTION_ORDER_5203 if int(family) == 5203 else SECTION_ORDER_5202


def section_specs(family: int) -> dict[str, list[FieldSpec]]:
    return SECTION_SPECS_5203 if int(family) == 5203 else SECTION_SPECS


def section_titles(family: int) -> dict[str, str]:
    return SECTION_TITLES_5203 if int(family) == 5203 else SECTION_TITLES


def board_scalars(family: int) -> dict[str, list[FieldSpec]]:
    return BOARD_SCALARS_5203 if int(family) == 5203 else BOARD_SCALARS


def channel_arrays(family: int) -> dict[str, list[tuple]]:
    return CHANNEL_ARRAYS_5203 if int(family) == 5203 else CHANNEL_ARRAYS


def board_class(family: int) -> type:
    return Board5203Config if int(family) == 5203 else BoardConfig


def num_channels(family: int) -> int:
    return NUM_CHANNELS_5203 if int(family) == 5203 else NUM_CHANNELS


def _default_board_dict(board_cls: type = BoardConfig) -> dict:
    d = board_cls().model_dump()
    d.pop("Open", None)
    return d


class BoardParams(QObject):
    """Shared per-board parameter model (single source of truth).

    Holds the list of per-board dicts (everything except ``Open``) plus the
    currently-selected board index. Many :class:`BoardScopeForm` instances — one
    per settings tab — bind to it, so changing the board in one tab updates them
    all, and they all read/write the same dicts.
    """

    board_changed = Signal(int)
    count_changed = Signal(int)

    def __init__(self, board_cls: type = BoardConfig) -> None:
        super().__init__()
        self._board_cls = board_cls
        self._boards: list[dict] = [_default_board_dict(board_cls)]
        self._cur = 0
        self._paths: list[str] = []

    def count(self) -> int:
        return len(self._boards)

    def current(self) -> int:
        return self._cur

    def paths(self) -> list[str]:
        return self._paths

    def dict(self, idx: int) -> dict:
        return self._boards[idx]

    def dicts(self) -> list[dict]:
        return [dict(d) for d in self._boards]

    def set_current(self, idx: int) -> None:
        if 0 <= idx < len(self._boards) and idx != self._cur:
            self._cur = idx
            self.board_changed.emit(idx)

    def set_count(self, n: int, paths: list[str] | None = None) -> None:
        n = max(1, n)
        while len(self._boards) < n:
            self._boards.append(_default_board_dict(self._board_cls))
        while len(self._boards) > n:
            self._boards.pop()
        if paths is not None:
            self._paths = list(paths)
        if self._cur >= n:
            self._cur = n - 1
        self.count_changed.emit(n)
        self.board_changed.emit(self._cur)

    def load(self, boards: list[BoardConfig]) -> None:
        self._boards = []
        for b in boards:
            d = b.model_dump()
            d.pop("Open", None)
            self._boards.append(d)
        if not self._boards:
            self._boards = [_default_board_dict(self._board_cls)]
        self._cur = 0
        self._paths = [b.Open for b in boards]
        self.count_changed.emit(len(self._boards))
        self.board_changed.emit(0)


class BoardScopeForm(QWidget):
    """Per-board / per-channel editor for ONE section, bound to a shared
    :class:`BoardParams`. Renders a board selector, the section's board-scalar
    fields, and its per-channel arrays (broadcast value + an 8×8 dialog).
    Writes edits straight through to the shared model and emits :attr:`changed`.
    """

    changed = Signal()

    def __init__(self, params: BoardParams,
                 scalars: list[FieldSpec],
                 arrays: list[tuple],
                 parent: QWidget | None = None,
                 num_ch: int = NUM_CHANNELS) -> None:
        super().__init__(parent)
        self._p = params
        self._scalars = scalars
        # Normalize array specs to (key, label, lo, hi, is_float).
        self._arrays = [
            (a[0], a[1], a[2], a[3], (len(a) > 4 and a[4] == "float")) for a in arrays
        ]
        self._num_ch = max(1, int(num_ch))
        self._suppress = False
        self._scalar_widgets: dict[str, QWidget] = {}
        self._array_bcast: dict[str, QWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(12)

        # board selector
        sel = QHBoxLayout()
        sel.addWidget(QLabel("Board:"))
        self._sel = QSpinBox()
        self._sel.setRange(0, max(0, params.count() - 1))
        self._sel.valueChanged.connect(self._on_sel)
        sel.addWidget(self._sel)
        self._path = QLabel("")
        self._path.setObjectName("FieldValue")
        sel.addWidget(self._path)
        sel.addStretch(1)
        root.addLayout(sel)

        # per-board scalar card
        if scalars:
            card = QFrame()
            card.setObjectName("Card")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(18, 12, 18, 12)
            cv.setSpacing(8)
            cv.addWidget(_section_header(SCOPE_BOARD_ICON, "Per-Board Parameters"))
            form = QFormLayout()
            form.setContentsMargins(CONTENT_INDENT, 0, 0, 0)
            form.setHorizontalSpacing(18)
            form.setVerticalSpacing(9)
            for spec in scalars:
                w = _make_widget(spec)
                if spec.tip:
                    w.setToolTip(spec.tip)
                self._scalar_widgets[spec.key] = w
                _wire_change(w, spec.kind,
                             lambda *_, k=spec.key, s=spec: self._scalar_edited(k, s))
                form.addRow(spec.label + ":", w)
            cv.addLayout(form)
            root.addWidget(card)

        # per-channel arrays card
        if arrays:
            card = QFrame()
            card.setObjectName("Card")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(18, 12, 18, 12)
            cv.setSpacing(8)
            cv.addWidget(_section_header(SCOPE_CHANNEL_ICON, "Per-Channel Parameters"))
            grid = QGridLayout()
            grid.setContentsMargins(CONTENT_INDENT, 0, 0, 0)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(9)
            grid.addWidget(self._hdr("Parameter"), 0, 0)
            grid.addWidget(self._hdr("Broadcast value"), 0, 1)
            grid.addWidget(self._hdr(""), 0, 2)
            for r, (key, label, lo, hi, is_float) in enumerate(self._arrays, start=1):
                lbl = QLabel(label + ":")
                lbl.setObjectName("FieldLabel")
                grid.addWidget(lbl, r, 0)
                bsp = QDoubleSpinBox() if is_float else QSpinBox()
                bsp.setRange(lo, hi)
                if is_float:
                    bsp.setDecimals(2)
                bsp.setToolTip(f"Set every channel to this value (range {lo}–{hi})")
                self._array_bcast[key] = bsp
                grid.addWidget(bsp, r, 1)
                btn_all = QPushButton("Set all")
                btn_all.clicked.connect(lambda _=False, k=key: self._broadcast(k))
                btn_edit = QPushButton("Per-channel…")
                btn_edit.clicked.connect(
                    lambda _=False, k=key, ll=label, a=lo, b=hi, f=is_float:
                    self._edit(k, ll, a, b, f)
                )
                hb = QHBoxLayout()
                hb.setContentsMargins(0, 0, 0, 0)
                hb.addWidget(btn_all)
                hb.addWidget(btn_edit)
                cell = QWidget()
                cell.setLayout(hb)
                grid.addWidget(cell, r, 2)
            grid.setColumnStretch(0, 1)
            cv.addLayout(grid)
            root.addWidget(card)

        params.board_changed.connect(self._reload)
        params.count_changed.connect(self._on_count)
        self._on_count(params.count())
        self._reload(params.current())

    @staticmethod
    def _hdr(t: str) -> QLabel:
        lbl = QLabel(t)
        lbl.setObjectName("FieldLabel")
        return lbl

    def _on_sel(self, v: int) -> None:
        if not self._suppress:
            self._p.set_current(v)

    def _on_count(self, n: int) -> None:
        self._suppress = True
        self._sel.setRange(0, max(0, n - 1))
        self._suppress = False
        self._update_path()

    def _reload(self, idx: int) -> None:
        self._suppress = True
        try:
            self._sel.setValue(idx)
            d = self._p.dict(idx)
            for spec in self._scalars:
                _set_widget(self._scalar_widgets[spec.key], spec, d[spec.key])
            for key, _label, lo, _hi, _f in self._arrays:
                vals = d.get(key, [lo] * self._num_ch)
                self._array_bcast[key].setValue(vals[0] if vals else lo)
        finally:
            self._suppress = False
        self._update_path()

    def _update_path(self) -> None:
        paths = self._p.paths()
        i = self._p.current()
        self._path.setText(f"  ({paths[i]})" if i < len(paths) else "")

    def _scalar_edited(self, key: str, spec: FieldSpec) -> None:
        if self._suppress:
            return
        self._p.dict(self._p.current())[key] = _widget_value(
            self._scalar_widgets[key], spec
        )
        self.changed.emit()

    def _broadcast(self, key: str) -> None:
        val = self._array_bcast[key].value()
        self._p.dict(self._p.current())[key] = [val] * self._num_ch
        self.changed.emit()

    def _edit(self, key: str, label: str, lo, hi, is_float: bool = False) -> None:
        cur = self._p.dict(self._p.current()).get(key, [lo] * self._num_ch)
        dlg = ChannelArrayDialog(
            label, cur, lo, hi, num_ch=self._num_ch, is_float=is_float, parent=self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vals = dlg.values()
            self._p.dict(self._p.current())[key] = vals
            self._array_bcast[key].setValue(vals[0] if vals else lo)
            self.changed.emit()

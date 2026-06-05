"""hydrafers.gui.config_form — declarative config-editing widgets (CONTRACT.md §6).

Builds PySide6 editing widgets for every field in :mod:`hydrafers.config.schema`
from a compact field-spec table, so the GUI exposes the SAME parameter surface as
the legacy Janus tabs (AcqMode, Discr, Spectroscopy, RunCtrl, Output, HV, Test-Probe)
plus per-board / per-channel overrides.

Two public widgets:
    * :class:`SectionForm`        — a grid of labelled inputs bound to one global
      section model (e.g. ``acq_mode``); ``load(model)`` fills it, ``values()``
      returns a dict suitable for ``model_copy(update=…)``.
    * :class:`BoardSettingsForm`  — per-board scalar overrides + per-channel array
      editing (broadcast value + an 8×8 per-channel dialog).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
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
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

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
# SectionForm — one global config section
# ---------------------------------------------------------------------------
class SectionForm(QScrollArea):
    """Editable form bound to one global section model (e.g. ``acq_mode``)."""

    #: Emitted when the user edits any field (not while ``load`` is filling it).
    changed = Signal()

    def __init__(self, specs: list[FieldSpec], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._specs = specs
        self._widgets: dict[str, QWidget] = {}
        self._suppress = False

        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(16, 14, 16, 14)

        card = QFrame()
        card.setObjectName("Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 14, 18, 14)
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

        outer.addWidget(card)
        outer.addStretch(1)
        self.setWidget(inner)

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
    """Modal 8×8 grid editor for a 64-element per-channel array."""

    def __init__(self, title: str, values: list[int], lo: int, hi: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._lo, self._hi = lo, hi
        self._spins: list[QSpinBox] = []

        v = QVBoxLayout(self)
        info = QLabel(f"{title}   (range {lo}–{hi})")
        info.setObjectName("CardTitle")
        v.addWidget(info)

        grid = QGridLayout()
        grid.setSpacing(4)
        # header columns
        for c in range(8):
            h = QLabel(f"+{c}")
            h.setObjectName("FieldLabel")
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(h, 0, c + 1)
        for r in range(8):
            rh = QLabel(f"{r * 8:>2}")
            rh.setObjectName("FieldLabel")
            grid.addWidget(rh, r + 1, 0)
            for c in range(8):
                ch = r * 8 + c
                sp = QSpinBox()
                sp.setRange(lo, hi)
                sp.setValue(int(values[ch]) if ch < len(values) else lo)
                sp.setFixedWidth(78)
                self._spins.append(sp)
                grid.addWidget(sp, r + 1, c + 1)
        v.addLayout(grid)

        # Fill-all helper
        fill_row = QHBoxLayout()
        fill_row.addWidget(QLabel("Set all to:"))
        self._fill = QSpinBox()
        self._fill.setRange(lo, hi)
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

    def values(self) -> list[int]:
        return [sp.value() for sp in self._spins]


# ---------------------------------------------------------------------------
# BoardSettingsForm — per-board scalars + per-channel arrays
# ---------------------------------------------------------------------------
# Per-channel arrays: (key, label, lo, hi)
_CHANNEL_ARRAYS = [
    ("HV_IndivAdj", "HV Individual Adjust", 0, 255),
    ("TD_FineThreshold", "Timing Fine Threshold", 0, 15),
    ("QD_FineThreshold", "Charge Fine Threshold", 0, 4095),
    ("HG_Gain", "High Gain", 1, 63),
    ("LG_Gain", "Low Gain", 1, 63),
    ("ZS_Threshold_LG", "ZS Threshold LG", 0, 65535),
    ("ZS_Threshold_HG", "ZS Threshold HG", 0, 65535),
]

# Per-board scalar fields (excluding Open, which the Connect page owns).
_BOARD_SCALARS = [
    unit("HV_Vbias", "HV Vbias", "Bias voltage (range 20–85 V)"),
    unit("HV_Imax", "HV Imax", "Max HV current before shutdown"),
    hexmask("ChEnableMask0", "Ch Enable Mask 0", "Channel enable mask, ch 0–31 (hex)"),
    hexmask("ChEnableMask1", "Ch Enable Mask 1", "Channel enable mask, ch 32–63 (hex)"),
    integer("TD_CoarseThreshold", "Timing Coarse Threshold", 0, 2047,
            "Timing discriminator coarse threshold (all channels)"),
    hexmask("Tlogic_Mask0", "Tlogic Mask 0", "Trigger-logic mask, ch 0–31 (hex)"),
    hexmask("Tlogic_Mask1", "Tlogic Mask 1", "Trigger-logic mask, ch 32–63 (hex)"),
    hexmask("Q_DiscrMask0", "Q-OR Mask 0", "Q-OR mask, ch 0–31 (hex)"),
    hexmask("Q_DiscrMask1", "Q-OR Mask 1", "Q-OR mask, ch 32–63 (hex)"),
]


class BoardSettingsForm(QWidget):
    """Per-board override editor: a board selector, scalar fields, and per-channel
    array editors (broadcast value + an 8×8 dialog).

    Holds an internal list of board-parameter dicts (everything except ``Open``,
    which the Connect page owns). ``set_count`` grows/shrinks that list; the form
    flushes the visible board before switching selection.
    """

    #: Emitted when the user edits any board/channel field.
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._boards: list[dict] = [self._default_dict()]
        self._cur = 0
        self._suppress = False
        self._scalar_widgets: dict[str, QWidget] = {}
        self._array_state: dict[str, list[int]] = {}
        self._array_bcast: dict[str, QSpinBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        # --- board selector row ---
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Editing board:"))
        self._board_sel = QSpinBox()
        self._board_sel.setRange(0, 0)
        self._board_sel.valueChanged.connect(self._on_board_change)
        sel_row.addWidget(self._board_sel)
        self._path_lbl = QLabel("")
        self._path_lbl.setObjectName("FieldValue")
        sel_row.addWidget(self._path_lbl)
        sel_row.addStretch(1)
        root.addLayout(sel_row)

        # --- scalar card ---
        scalar_card = QFrame()
        scalar_card.setObjectName("Card")
        sc_v = QVBoxLayout(scalar_card)
        sc_v.setContentsMargins(18, 12, 18, 12)
        title = QLabel("Board Parameters")
        title.setObjectName("CardTitle")
        sc_v.addWidget(title)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(9)
        for spec in _BOARD_SCALARS:
            w = _make_widget(spec)
            if spec.tip:
                w.setToolTip(spec.tip)
            self._scalar_widgets[spec.key] = w
            _wire_change(w, spec.kind, self._emit_changed)
            form.addRow(spec.label + ":", w)
        sc_v.addLayout(form)
        root.addWidget(scalar_card)

        # --- channel arrays card ---
        arr_card = QFrame()
        arr_card.setObjectName("Card")
        ac_v = QVBoxLayout(arr_card)
        ac_v.setContentsMargins(18, 12, 18, 12)
        atitle = QLabel("Per-Channel Parameters")
        atitle.setObjectName("CardTitle")
        ac_v.addWidget(atitle)
        agrid = QGridLayout()
        agrid.setHorizontalSpacing(12)
        agrid.setVerticalSpacing(9)
        agrid.addWidget(self._hdr("Parameter"), 0, 0)
        agrid.addWidget(self._hdr("Broadcast value"), 0, 1)
        agrid.addWidget(self._hdr(""), 0, 2)
        for r, (key, label, lo, hi) in enumerate(_CHANNEL_ARRAYS, start=1):
            lbl = QLabel(label + ":")
            lbl.setObjectName("FieldLabel")
            agrid.addWidget(lbl, r, 0)
            bsp = QSpinBox()
            bsp.setRange(lo, hi)
            bsp.setToolTip(f"Set every channel to this value (range {lo}–{hi})")
            self._array_bcast[key] = bsp
            agrid.addWidget(bsp, r, 1)
            btn_all = QPushButton("Set all")
            btn_all.clicked.connect(lambda _=False, k=key: self._broadcast(k))
            btn_edit = QPushButton("Per-channel…")
            btn_edit.clicked.connect(lambda _=False, k=key, ll=label, a=lo, b=hi:
                                     self._edit_channels(k, ll, a, b))
            hb = QHBoxLayout()
            hb.setContentsMargins(0, 0, 0, 0)
            hb.addWidget(btn_all)
            hb.addWidget(btn_edit)
            cell = QWidget()
            cell.setLayout(hb)
            agrid.addWidget(cell, r, 2)
        agrid.setColumnStretch(0, 1)
        ac_v.addLayout(agrid)
        root.addWidget(arr_card)
        root.addStretch(1)

        self._load_board(0)

    # -------- helpers --------
    @staticmethod
    def _hdr(t: str) -> QLabel:
        lbl = QLabel(t)
        lbl.setObjectName("FieldLabel")
        return lbl

    @staticmethod
    def _default_dict() -> dict:
        d = BoardConfig().model_dump()
        d.pop("Open", None)
        return d

    def _emit_changed(self, *_) -> None:
        if not self._suppress:
            self.changed.emit()

    def _broadcast(self, key: str) -> None:
        val = self._array_bcast[key].value()
        self._array_state[key] = [val] * NUM_CHANNELS
        self._emit_changed()

    def _edit_channels(self, key: str, label: str, lo: int, hi: int) -> None:
        dlg = ChannelArrayDialog(label, self._array_state[key], lo, hi, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._array_state[key] = dlg.values()
            self._emit_changed()

    # -------- board switching --------
    def _on_board_change(self, new_idx: int) -> None:
        if new_idx == self._cur:
            return
        self._flush(self._cur)
        self._load_board(new_idx)

    def _flush(self, idx: int) -> None:
        if not (0 <= idx < len(self._boards)):
            return
        d = self._boards[idx]
        for spec in _BOARD_SCALARS:
            d[spec.key] = _widget_value(self._scalar_widgets[spec.key], spec)
        for key, *_ in _CHANNEL_ARRAYS:
            d[key] = list(self._array_state[key])

    def _load_board(self, idx: int) -> None:
        if not (0 <= idx < len(self._boards)):
            return
        self._cur = idx
        d = self._boards[idx]
        self._suppress = True
        try:
            for spec in _BOARD_SCALARS:
                _set_widget(self._scalar_widgets[spec.key], spec, d[spec.key])
            for key, _label, lo, _hi in _CHANNEL_ARRAYS:
                vals = list(d.get(key, [lo] * NUM_CHANNELS))
                self._array_state[key] = vals
                # broadcast box shows the common value, or the first if mixed
                self._array_bcast[key].setValue(vals[0] if vals else lo)
        finally:
            self._suppress = False

    # -------- public API --------
    def set_count(self, n: int, paths: list[str] | None = None) -> None:
        """Match the number of boards to *n* (preserving existing dicts)."""
        n = max(1, n)
        self._flush(self._cur)
        while len(self._boards) < n:
            self._boards.append(self._default_dict())
        while len(self._boards) > n:
            self._boards.pop()
        self._paths = list(paths or [])
        self._board_sel.setRange(0, n - 1)
        if self._cur >= n:
            self._cur = n - 1
            self._board_sel.setValue(self._cur)
        self._update_path_label()
        self._load_board(self._cur)

    def _update_path_label(self) -> None:
        paths = getattr(self, "_paths", [])
        if self._cur < len(paths):
            self._path_lbl.setText(f"  ({paths[self._cur]})")
        else:
            self._path_lbl.setText("")

    def load_boards(self, boards: list[BoardConfig]) -> None:
        """Load full per-board parameter dicts from a config."""
        self._boards = []
        for b in boards:
            d = b.model_dump()
            d.pop("Open", None)
            self._boards.append(d)
        if not self._boards:
            self._boards = [self._default_dict()]
        self._cur = 0
        self._board_sel.setRange(0, len(self._boards) - 1)
        self._board_sel.setValue(0)
        self._paths = [b.Open for b in boards]
        self._update_path_label()
        self._load_board(0)

    def board_dicts(self) -> list[dict]:
        """Return current per-board parameter dicts (no ``Open``)."""
        self._flush(self._cur)
        return [dict(d) for d in self._boards]

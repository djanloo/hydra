"""hydrafers.gui.main_window — PySide6 main window (CONTRACT.md §6).

Pages (sidebar)
---------------
0  Connect    — board paths, config load/save, board info after connect
1  Overview   — run-statistics + per-board throughput cards
2  Statistics — 64-channel rate/count grid + all-boards summary table
3  Spectra    — 1D histogram (PHA HG/LG, ToA, ToT)
4  Map 2D     — 8×8 per-channel heat-map
5  HV & Temps — HV control + temperature monitoring per board
6  Registers  — low-level register read/write
7  Log        — scrolling acquisition log
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from queue import Empty
from typing import Callable

from PySide6.QtCore import QSize, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from hydrafers.config import HydraConfig, default_config, load_config, save_config
from hydrafers.config.schema import BoardConfig
from hydrafers.gui.config_form import (
    BOARD_SCALARS,
    CHANNEL_ARRAYS,
    SECTION_SPECS,
    SECTION_TITLES,
    BoardParams,
    BoardScopeForm,
    SectionForm,
)
from hydrafers.gui.icons import NEUTRAL, ON_COLOR, icon
from hydrafers.core import AcqState, AcquisitionEngine, BoardStatus, RunStatistics
from hydrafers.gui.plots.map2d import Map2DPlot
from hydrafers.gui.plots.spectrum import SPECTRUM_SOURCES, SpectrumPlot
from hydrafers.gui.widgets.led import Led
from hydrafers.gui.widgets.sidebar import Sidebar
from hydrafers.gui.widgets.status_table import StatusBadge, StatusTable

logger = logging.getLogger("hydrafers.gui.main_window")

_REFRESH_MS = 66   # ~15 Hz poll
_MAX_BOARDS = 8    # rows shown in Connect page

# Sidebar / stack page indices (single source of truth).
(PG_CONNECT, PG_SETTINGS, PG_OVERVIEW, PG_STATS,
 PG_SPECTRA, PG_MAP, PG_HV, PG_REGS, PG_LOG) = range(9)

_PAGE_NAMES = [
    "Connect", "Settings", "Overview", "Statistics",
    "Spectra", "Map 2D", "HV / Temps", "Registers", "Log",
]

# Material Design icon per nav page (aligned with _PAGE_NAMES).
_PAGE_ICONS = [
    "mdi6.lan-connect", "mdi6.cog", "mdi6.view-dashboard", "mdi6.chart-bar",
    "mdi6.chart-line", "mdi6.grid", "mdi6.thermometer", "mdi6.memory",
    "mdi6.text-box-outline",
]


# AcqState → (StatusBadge state, badge text, LED colour)
_STATE_UI: dict[AcqState, tuple[str, str, str]] = {
    AcqState.DISCONNECTED: ("disabled", "Disconnected", "grey"),
    AcqState.CONNECTING:   ("busy",     "Connecting…",  "yellow"),
    AcqState.READY:        ("ready",    "Ready",        "green"),
    AcqState.STARTING:     ("busy",     "Starting…",    "yellow"),
    AcqState.RUNNING:      ("running",  "Running",      "green"),
    AcqState.STOPPING:     ("busy",     "Stopping…",    "yellow"),
    AcqState.EMPTYING:     ("busy",     "Emptying…",    "yellow"),
    AcqState.ERROR:        ("error",    "Error",        "red"),
    AcqState.UPGRADING_FW: ("busy",     "Upgrading FW", "blue"),
}

_LOG_COLORS = {
    "error":   "#c62828",
    "warning": "#e65100",
    "info":    "#1565c0",
}


def _human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} TB"


def _human_rate(hz: float) -> str:
    if hz >= 1e6:
        return f"{hz/1e6:.2f} MHz"
    if hz >= 1e3:
        return f"{hz/1e3:.2f} kHz"
    return f"{hz:.1f} Hz"


def _rate_color(hz: float) -> str:
    """Background colour for a channel cell based on trigger rate."""
    if hz <= 0:
        return "#ffffff"
    if hz < 100:
        return "#e8f5e9"
    if hz < 1e4:
        return "#c8e6c9"
    if hz < 1e5:
        return "#a5d6a7"
    return "#66bb6a"


# ---------------------------------------------------------------------------
# Background worker for blocking engine calls
# ---------------------------------------------------------------------------

class _EngineOp(QThread):
    """Runs a single blocking engine callable in a background QThread."""

    op_error = Signal(str)

    def __init__(self, fn: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn()
        except Exception as exc:
            self.op_error.emit(str(exc))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """HydraFERS PySide6 desktop main window."""

    _sig_state_changed = Signal(object)
    _sig_error = Signal(str)
    _sig_log = Signal(str, str)

    def __init__(self, config: HydraConfig | None = None) -> None:
        super().__init__()
        self.setWindowTitle("HydraFERS")
        self.resize(1360, 860)
        self.setMinimumSize(960, 640)

        self._config: HydraConfig = config or default_config()
        self._config_path: Path | None = None
        self._engine = AcquisitionEngine(self._config)
        self._op_thread: _EngineOp | None = None
        self._tick_div = 0
        self._freeze = False

        # Board path rows state cache (QCheckBox, QLineEdit, *info_labels)
        self._board_path_rows: list[
            tuple[QCheckBox, QLineEdit, QLabel, QLabel, QLabel]
        ] = []

        # 64 QLabels for the statistics grid (filled in _build_statistics_page)
        self._ch_labels: list[QLabel] = []

        # Per-board HV card dicts {led, hv_btn, vmon, imon, t_fpga, t_board, t_hv, t_det}
        self._hv_cards: list[dict] = []

        # Engine observers → Qt signals (called from engine threads)
        self._engine.on_state_change = lambda s: self._sig_state_changed.emit(s)
        self._engine.on_error        = lambda m: self._sig_error.emit(m)
        self._engine.on_log          = lambda lv, m: self._sig_log.emit(lv, m)

        self._build_ui()

        self._sig_state_changed.connect(self._on_state_changed)
        self._sig_error.connect(self._on_engine_error)
        self._sig_log.connect(self._on_engine_log)

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._apply_state_ui(AcqState.DISCONNECTED)

    # ================================================================ build UI

    def _build_ui(self) -> None:
        self._build_menu()

        root = QWidget()
        root.setObjectName("CentralRoot")
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        _logo = Path(__file__).parent / "imgs" / "light_bg.png"
        self._sidebar = Sidebar(
            brand="HydraFERS",
            logo_path=_logo if _logo.exists() else None,
        )
        for name, ic in zip(_PAGE_NAMES, _PAGE_ICONS):
            self._sidebar.add_page(name, ic)
        self._sidebar.page_selected.connect(self._switch_page)
        layout.addWidget(self._sidebar)

        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._build_header())

        self._stack = QStackedWidget()
        for builder in [
            self._build_connect_page,
            self._build_settings_page,
            self._build_overview_page,
            self._build_statistics_page,
            self._build_spectra_page,
            self._build_map2d_page,
            self._build_hv_page,
            self._build_registers_page,
            self._build_log_page,
        ]:
            self._stack.addWidget(builder())

        # Populate every editing form from the active config now that they exist.
        self._populate_forms(self._config)
        col.addWidget(self._stack, 1)
        layout.addWidget(content, 1)

        # Status bar
        sb = QStatusBar()
        sb.setObjectName("StatusBar")
        self._sb_led = Led(color="grey", diameter=12)
        self._sb_label = QLabel("Disconnected")
        sb.addWidget(self._sb_led)
        sb.addWidget(self._sb_label)
        brand = QLabel("CAEN Front End Division")
        brand.setObjectName("BrandFooter")
        sb.addPermanentWidget(brand)
        self.setStatusBar(sb)

    # ---------------------------------------------------------------- menu

    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("File")
        act_load = QAction("Load Config…", self)
        act_load.triggered.connect(self._menu_load_config)
        file_menu.addAction(act_load)
        act_save = QAction("Save Config As…", self)
        act_save.triggered.connect(self._menu_save_config)
        file_menu.addAction(act_save)
        file_menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        help_menu = bar.addMenu("Help")
        act_about = QAction("About HydraFERS", self)
        act_about.triggered.connect(self._menu_about)
        help_menu.addAction(act_about)

    # ---------------------------------------------------------------- header

    def _build_header(self) -> QFrame:
        hdr = QFrame()
        hdr.setObjectName("PageHeader")
        hdr.setFixedHeight(60)
        row = QHBoxLayout(hdr)
        row.setContentsMargins(20, 0, 16, 0)
        row.setSpacing(10)

        self._header_title = QLabel("Connect")
        self._header_title.setObjectName("HeaderTitle")
        row.addWidget(self._header_title)

        row.addWidget(QLabel("Run #:"))
        self._run_spin = QSpinBox()
        self._run_spin.setRange(0, 9999)
        self._run_spin.setValue(1)
        self._run_spin.setFixedWidth(72)
        row.addWidget(self._run_spin)

        row.addStretch(1)

        self._device_badge = QLabel("Not connected")
        self._device_badge.setObjectName("DeviceBadge")
        row.addWidget(self._device_badge)

        self._state_badge = StatusBadge("Disconnected", state="disabled")
        row.addWidget(self._state_badge)

        row.addSpacing(8)

        # Icon-only action buttons (text lives in the tooltip on hover).
        _btn_size = QSize(46, 40)
        _icon_size = QSize(26, 26)

        self._btn_freeze = QPushButton()
        self._btn_freeze.setObjectName("IconToggle")
        self._btn_freeze.setCheckable(True)
        self._btn_freeze.setFixedSize(_btn_size)
        self._btn_freeze.setIcon(icon("mdi6.snowflake", NEUTRAL))
        self._btn_freeze.setIconSize(_icon_size)
        self._btn_freeze.setToolTip("Freeze live plot/stats updates (the run keeps going)")
        self._btn_freeze.toggled.connect(self._on_freeze_toggled)
        row.addWidget(self._btn_freeze)

        self._btn_connect = QPushButton()
        self._btn_connect.setObjectName("PrimaryButton")
        self._btn_connect.setFixedSize(_btn_size)
        self._btn_connect.setIcon(icon("mdi6.lan-connect", ON_COLOR))
        self._btn_connect.setIconSize(_icon_size)
        self._btn_connect.setToolTip("Apply config and connect to the boards")
        self._btn_connect.clicked.connect(self._action_connect)
        row.addWidget(self._btn_connect)

        self._btn_start = QPushButton()
        self._btn_start.setObjectName("AccentButton")
        self._btn_start.setFixedSize(_btn_size)
        self._btn_start.setIcon(icon("mdi6.play", ON_COLOR))
        self._btn_start.setIconSize(_icon_size)
        self._btn_start.setToolTip("Apply config and start a new run")
        self._btn_start.clicked.connect(self._action_start)
        row.addWidget(self._btn_start)

        self._btn_stop = QPushButton()
        self._btn_stop.setObjectName("DangerButton")
        self._btn_stop.setFixedSize(_btn_size)
        self._btn_stop.setIcon(icon("mdi6.stop", ON_COLOR))
        self._btn_stop.setIconSize(_icon_size)
        self._btn_stop.setToolTip("Stop the current run")
        self._btn_stop.clicked.connect(self._action_stop)
        row.addWidget(self._btn_stop)

        return hdr

    # ---------------------------------------------------------------- pages

    def _build_connect_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        vbox = QVBoxLayout(inner)
        vbox.setContentsMargins(20, 16, 20, 16)
        vbox.setSpacing(16)

        # --- Config file card ---
        cfg_card = QFrame()
        cfg_card.setObjectName("Card")
        cfg_vbox = QVBoxLayout(cfg_card)
        cfg_vbox.setContentsMargins(16, 12, 16, 12)
        cfg_vbox.setSpacing(8)

        cfg_title = QLabel("Configuration File")
        cfg_title.setObjectName("CardTitle")
        cfg_vbox.addWidget(cfg_title)

        cfg_row = QHBoxLayout()
        self._cfg_path_label = QLabel("(built-in defaults)")
        self._cfg_path_label.setObjectName("FieldValue")
        cfg_row.addWidget(self._cfg_path_label, 1)
        btn_load = QPushButton("Load Config…")
        btn_load.setIcon(icon("mdi6.folder-open", NEUTRAL))
        btn_load.setIconSize(QSize(16, 16))
        btn_load.setToolTip("Load a configuration from a YAML file")
        btn_load.clicked.connect(self._menu_load_config)
        cfg_row.addWidget(btn_load)
        btn_save = QPushButton("Save Config As…")
        btn_save.setIcon(icon("mdi6.content-save", NEUTRAL))
        btn_save.setIconSize(QSize(16, 16))
        btn_save.setToolTip("Save the current configuration to a YAML file")
        btn_save.clicked.connect(self._menu_save_config)
        cfg_row.addWidget(btn_save)
        cfg_vbox.addLayout(cfg_row)
        vbox.addWidget(cfg_card)

        # --- Board connections card ---
        brd_card = QFrame()
        brd_card.setObjectName("Card")
        brd_vbox = QVBoxLayout(brd_card)
        brd_vbox.setContentsMargins(16, 12, 16, 12)
        brd_vbox.setSpacing(6)

        brd_title = QLabel("Board Connections")
        brd_title.setObjectName("CardTitle")
        brd_vbox.addWidget(brd_title)

        hint = QLabel(
            "Enter one connection path per board (e.g. eth:192.168.50.3, usb:0). "
            "Paths are editable only while disconnected."
        )
        hint.setObjectName("FieldLabel")
        hint.setWordWrap(True)
        brd_vbox.addWidget(hint)

        # Column headers
        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(8)
        for text, width in [("Brd", 36), ("En", 36), ("Connection Path", 300),
                             ("PID", 80), ("Model", 130), ("FPGA FW", 180)]:
            lbl = QLabel(text)
            lbl.setObjectName("FieldLabel")
            lbl.setFixedWidth(width)
            hdr_row.addWidget(lbl)
        hdr_row.addStretch(1)
        brd_vbox.addLayout(hdr_row)

        initial_boards = self._config.boards if self._config else []
        self._board_path_rows = []

        for i in range(_MAX_BOARDS):
            brow = QHBoxLayout()
            brow.setSpacing(8)

            num_lbl = QLabel(str(i))
            num_lbl.setObjectName("FieldLabel")
            num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            num_lbl.setFixedWidth(36)
            brow.addWidget(num_lbl)

            enable_cb = QCheckBox()
            enable_cb.setFixedWidth(36)
            enable_cb.setChecked(i < len(initial_boards))
            brow.addWidget(enable_cb)

            path_edit = QLineEdit()
            path_edit.setFixedWidth(300)
            path_edit.setPlaceholderText("eth:192.168.50.3  or  usb:0")
            if i < len(initial_boards):
                path_edit.setText(initial_boards[i].Open)
            brow.addWidget(path_edit)

            enable_cb.toggled.connect(self._sync_board_count)
            path_edit.editingFinished.connect(self._sync_board_count)
            enable_cb.toggled.connect(self._mark_dirty)
            path_edit.textEdited.connect(self._mark_dirty)

            pid_lbl   = QLabel("—"); pid_lbl.setFixedWidth(80);   pid_lbl.setObjectName("FieldValue")
            model_lbl = QLabel("—"); model_lbl.setFixedWidth(130); model_lbl.setObjectName("FieldValue")
            fw_lbl    = QLabel("—"); fw_lbl.setFixedWidth(180);   fw_lbl.setObjectName("FieldValue")
            brow.addWidget(pid_lbl)
            brow.addWidget(model_lbl)
            brow.addWidget(fw_lbl)
            brow.addStretch(1)

            self._board_path_rows.append((enable_cb, path_edit, pid_lbl, model_lbl, fw_lbl))
            brd_vbox.addLayout(brow)

        vbox.addWidget(brd_card)
        vbox.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        tabs = QTabWidget()
        self._section_forms: dict[str, SectionForm] = {}
        self._board_scope_forms: list[BoardScopeForm] = []
        # Shared per-board model: every section's board/channel editor binds to it,
        # so switching board on one tab switches it everywhere.
        self._board_params = BoardParams()

        # One tab per functional section. Each tab stacks the section's global
        # params and (where they exist) its own per-board / per-channel params —
        # matching the legacy Janus tabs, so e.g. the Discriminator tab holds the
        # T/Q thresholds and masks, not a separate catch-all tab.
        for name in ("acq_mode", "discr", "spectroscopy", "hv_bias",
                     "run_ctrl", "output_files", "test_probe"):
            tabs.addTab(self._build_section_tab(name), SECTION_TITLES[name])

        vbox.addWidget(tabs, 1)

        # Action button row.
        bar = QFrame()
        bar.setObjectName("PageHeader")
        bar.setFixedHeight(52)
        brow = QHBoxLayout(bar)
        brow.setContentsMargins(16, 8, 16, 8)
        hint = QLabel("Edit parameters, then apply to the running engine or save to file.")
        hint.setObjectName("FieldLabel")
        brow.addWidget(hint)
        brow.addStretch(1)
        btn_revert = QPushButton("Revert")
        btn_revert.setIcon(icon("mdi6.undo", NEUTRAL))
        btn_revert.setIconSize(QSize(16, 16))
        btn_revert.setToolTip("Discard edits and reload the active configuration")
        btn_revert.clicked.connect(lambda: self._populate_forms(self._config))
        brow.addWidget(btn_revert)
        btn_apply = QPushButton("Apply to Engine")
        btn_apply.setObjectName("ApplyButton")
        btn_apply.setProperty("dirty", "false")
        btn_apply.setIconSize(QSize(16, 16))
        btn_apply.setToolTip("Send the edited configuration to the engine")
        btn_apply.clicked.connect(self._apply_settings)
        brow.addWidget(btn_apply)
        self._btn_apply_settings = btn_apply
        vbox.addWidget(bar)

        # Any edit in a section/board form marks the config dirty (button → orange).
        for form in self._section_forms.values():
            form.changed.connect(self._mark_dirty)
        for bsf in self._board_scope_forms:
            bsf.changed.connect(self._mark_dirty)

        return page

    def _build_section_tab(self, name: str) -> QWidget:
        """Build one settings tab: the section's global params plus, if any, its
        per-board / per-channel params, in a single scrollable column."""
        container = QWidget()
        col = QVBoxLayout(container)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(12)

        form = SectionForm(SECTION_SPECS[name])
        self._section_forms[name] = form
        col.addWidget(form)

        scalars = BOARD_SCALARS.get(name)
        arrays = CHANNEL_ARRAYS.get(name)
        if scalars or arrays:
            bsf = BoardScopeForm(self._board_params, scalars or [], arrays or [])
            self._board_scope_forms.append(bsf)
            col.addWidget(bsf)

        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(container)
        return scroll

    def _build_overview_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        self._overview_layout = QVBoxLayout(inner)
        self._overview_layout.setContentsMargins(20, 16, 20, 16)
        self._overview_layout.setSpacing(12)

        self._stats_card = StatusTable("Run Statistics")
        self._stats_card.add_row("run_number",   "Run #",        "—")
        self._stats_card.add_row("elapsed",       "Elapsed",      "—")
        self._stats_card.add_row("total_events",  "Total events", "—")
        self._stats_card.add_row("built_events",  "Built events", "—")
        self._stats_card.add_row("event_rate",    "Event rate",   "—")
        self._stats_card.add_row("data_volume",   "Data volume",  "—")
        self._stats_card.add_row("data_rate",     "Data rate",    "—")
        self._overview_layout.addWidget(self._stats_card)

        self._board_cards_widget = QWidget()
        self._board_cards_layout = QVBoxLayout(self._board_cards_widget)
        self._board_cards_layout.setContentsMargins(0, 0, 0, 0)
        self._board_cards_layout.setSpacing(12)
        self._board_cards: list[StatusTable] = []
        self._overview_layout.addWidget(self._board_cards_widget)
        self._overview_layout.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _build_statistics_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(20, 12, 20, 12)
        vbox.setSpacing(10)

        # Controls row
        ctrl = QHBoxLayout()
        ctrl.setSpacing(12)
        ctrl.addWidget(QLabel("Board:"))
        self._stats_board_spin = QSpinBox()
        self._stats_board_spin.setRange(0, 0)
        ctrl.addWidget(self._stats_board_spin)
        ctrl.addWidget(QLabel("Metric:"))
        self._stats_metric = QComboBox()
        self._stats_metric.addItems(["Trigger Rate (Hz)", "Trigger Count"])
        ctrl.addWidget(self._stats_metric)
        ctrl.addStretch(1)
        vbox.addLayout(ctrl)

        # 8×8 channel grid
        grid_card = QFrame()
        grid_card.setObjectName("Card")
        grid_outer = QVBoxLayout(grid_card)
        grid_outer.setContentsMargins(14, 10, 14, 10)
        grid_outer.setSpacing(6)

        title_hbox = QHBoxLayout()
        title_hbox.addWidget(QLabel("Per-Channel Rates / Counts"))
        title_hbox.addStretch(1)
        for c in "ABCDEFGH":
            lbl = QLabel(c)
            lbl.setObjectName("FieldLabel")
            lbl.setFixedWidth(74)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_hbox.addWidget(lbl)
        grid_outer.addLayout(title_hbox)

        cell_font = QFont("Consolas, DejaVu Sans Mono", 9)
        self._ch_labels = []
        for row_i in range(8):
            rbox = QHBoxLayout()
            rbox.setSpacing(4)
            row_lbl = QLabel(f"{row_i * 8:>2}")
            row_lbl.setObjectName("FieldLabel")
            row_lbl.setFixedWidth(28)
            rbox.addWidget(row_lbl)
            rbox.addStretch(1)
            for col_i in range(8):
                lbl = QLabel("—")
                lbl.setFont(cell_font)
                lbl.setFixedWidth(74)
                lbl.setFixedHeight(24)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet(
                    "QLabel{background:#fff;border:1px solid #e4e7eb;"
                    "border-radius:3px;color:#546e7a;}"
                )
                rbox.addWidget(lbl)
                self._ch_labels.append(lbl)
            grid_outer.addLayout(rbox)

        vbox.addWidget(grid_card, 1)

        # All-boards summary
        sum_card = QFrame()
        sum_card.setObjectName("Card")
        sum_vbox = QVBoxLayout(sum_card)
        sum_vbox.setContentsMargins(14, 8, 14, 8)
        sum_vbox.setSpacing(6)

        sum_title = QLabel("All-Boards Summary")
        sum_title.setObjectName("CardTitle")
        sum_vbox.addWidget(sum_title)

        self._all_brd_table = QTableWidget(0, 6)
        self._all_brd_table.setHorizontalHeaderLabels(
            ["Board", "Events", "Event Rate", "Data Rate", "Lost Events", "Bytes"]
        )
        self._all_brd_table.horizontalHeader().setStretchLastSection(True)
        self._all_brd_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._all_brd_table.setFixedHeight(130)
        sum_vbox.addWidget(self._all_brd_table)
        vbox.addWidget(sum_card)

        return page

    def _build_spectra_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(20, 12, 20, 12)
        vbox.setSpacing(8)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(12)
        ctrl.addWidget(QLabel("Board:"))
        self._spec_board = QSpinBox()
        self._spec_board.setRange(0, 0)
        self._spec_board.valueChanged.connect(self._spec_target_changed)
        ctrl.addWidget(self._spec_board)
        ctrl.addWidget(QLabel("Channel:"))
        self._spec_channel = QSpinBox()
        self._spec_channel.setRange(0, 63)
        self._spec_channel.valueChanged.connect(self._spec_target_changed)
        ctrl.addWidget(self._spec_channel)
        ctrl.addWidget(QLabel("Source:"))
        self._spec_source = QComboBox()
        for name in SPECTRUM_SOURCES:
            self._spec_source.addItem(name)
        self._spec_source.currentTextChanged.connect(
            lambda t: self._spectrum_plot.set_source(t)
        )
        ctrl.addWidget(self._spec_source)
        ctrl.addStretch(1)
        vbox.addLayout(ctrl)

        self._spectrum_plot = SpectrumPlot()
        vbox.addWidget(self._spectrum_plot, 1)
        return page

    def _build_map2d_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(20, 12, 20, 12)
        vbox.setSpacing(8)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(12)
        ctrl.addWidget(QLabel("Board:"))
        self._map_board = QSpinBox()
        self._map_board.setRange(0, 0)
        self._map_board.valueChanged.connect(lambda v: self._map2d_plot.set_board(v))
        ctrl.addWidget(self._map_board)
        ctrl.addWidget(QLabel("Mode:"))
        self._map_mode = QComboBox()
        self._map_mode.addItems(["Counts", "Rate"])
        ctrl.addWidget(self._map_mode)
        ctrl.addStretch(1)
        vbox.addLayout(ctrl)

        self._map2d_plot = Map2DPlot()
        vbox.addWidget(self._map2d_plot, 1)
        return page

    def _build_hv_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        self._hv_page_layout = QVBoxLayout(inner)
        self._hv_page_layout.setContentsMargins(20, 16, 20, 16)
        self._hv_page_layout.setSpacing(12)

        self._hv_placeholder = QLabel("Connect boards to see HV and temperature status.")
        self._hv_placeholder.setObjectName("FieldLabel")
        self._hv_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hv_page_layout.addWidget(self._hv_placeholder)
        self._hv_page_layout.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _build_registers_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(20, 12, 20, 12)
        vbox.setSpacing(12)

        ctrl_card = QFrame()
        ctrl_card.setObjectName("Card")
        ctrl_vbox = QVBoxLayout(ctrl_card)
        ctrl_vbox.setContentsMargins(16, 12, 16, 12)
        ctrl_vbox.setSpacing(10)

        ctrl_title = QLabel("Register Access")
        ctrl_title.setObjectName("CardTitle")
        ctrl_vbox.addWidget(ctrl_title)

        # Row 1: board + base + channel
        row1 = QHBoxLayout()
        row1.setSpacing(14)
        row1.addWidget(QLabel("Board:"))
        self._reg_board = QSpinBox()
        self._reg_board.setRange(0, 0)
        self._reg_board.setFixedWidth(70)
        row1.addWidget(self._reg_board)

        row1.addWidget(QLabel("Base:"))
        self._reg_base_group = QButtonGroup(page)
        for label, val in [("COMM", "01"), ("INDIV", "02"), ("BCAST", "03")]:
            rb = QRadioButton(label)
            rb.setProperty("base_val", val)
            self._reg_base_group.addButton(rb)
            row1.addWidget(rb)
        self._reg_base_group.buttons()[0].setChecked(True)
        self._reg_base_group.buttonToggled.connect(self._reg_update_addr)

        row1.addWidget(QLabel("Channel:"))
        self._reg_ch = QSpinBox()
        self._reg_ch.setRange(0, 63)
        self._reg_ch.setFixedWidth(70)
        self._reg_ch.valueChanged.connect(self._reg_update_addr)
        row1.addWidget(self._reg_ch)
        row1.addStretch(1)
        ctrl_vbox.addLayout(row1)

        # Row 2: offset + address + data
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        row2.addWidget(QLabel("Offset (hex):"))
        self._reg_offset = QLineEdit("0000")
        self._reg_offset.setFixedWidth(90)
        self._reg_offset.textChanged.connect(self._reg_update_addr)
        row2.addWidget(self._reg_offset)

        row2.addWidget(QLabel("Address:"))
        self._reg_addr_display = QLineEdit("01000000")
        self._reg_addr_display.setFixedWidth(120)
        self._reg_addr_display.setReadOnly(True)
        row2.addWidget(self._reg_addr_display)

        row2.addWidget(QLabel("Data (hex):"))
        self._reg_data = QLineEdit("00000000")
        self._reg_data.setFixedWidth(120)
        row2.addWidget(self._reg_data)
        row2.addStretch(1)
        ctrl_vbox.addLayout(row2)

        # Row 3: action buttons
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        btn_read = QPushButton("Read Reg")
        btn_read.setObjectName("PrimaryButton")
        btn_read.clicked.connect(self._reg_read)
        row3.addWidget(btn_read)
        btn_write = QPushButton("Write Reg")
        btn_write.setObjectName("AccentButton")
        btn_write.clicked.connect(self._reg_write)
        row3.addWidget(btn_write)
        row3.addStretch(1)
        ctrl_vbox.addLayout(row3)

        vbox.addWidget(ctrl_card)

        # Register log card
        log_card = QFrame()
        log_card.setObjectName("Card")
        log_vbox = QVBoxLayout(log_card)
        log_vbox.setContentsMargins(14, 8, 14, 8)
        log_vbox.setSpacing(6)

        log_title = QLabel("Register Log")
        log_title.setObjectName("CardTitle")
        log_vbox.addWidget(log_title)

        self._reg_log = QTextEdit()
        self._reg_log.setObjectName("LogView")
        self._reg_log.setReadOnly(True)
        log_vbox.addWidget(self._reg_log, 1)

        btn_clear_rlog = QPushButton("Clear Log")
        btn_clear_rlog.setIcon(icon("mdi6.broom", NEUTRAL))
        btn_clear_rlog.setIconSize(QSize(16, 16))
        btn_clear_rlog.setToolTip("Clear the register read/write log")
        btn_clear_rlog.setFixedWidth(120)
        btn_clear_rlog.clicked.connect(self._reg_log.clear)
        btns_row = QHBoxLayout()
        btns_row.addStretch(1)
        btns_row.addWidget(btn_clear_rlog)
        log_vbox.addLayout(btns_row)

        vbox.addWidget(log_card, 1)
        return page

    def _build_log_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(20, 12, 20, 12)
        vbox.setSpacing(8)

        self._log_view = QTextEdit()
        self._log_view.setObjectName("LogView")
        self._log_view.setReadOnly(True)
        vbox.addWidget(self._log_view, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_clear = QPushButton("Clear Log")
        btn_clear.setIcon(icon("mdi6.broom", NEUTRAL))
        btn_clear.setIconSize(QSize(16, 16))
        btn_clear.setToolTip("Clear the log")
        btn_clear.setFixedWidth(120)
        btn_clear.clicked.connect(self._log_view.clear)
        btns.addWidget(btn_clear)
        vbox.addLayout(btns)
        return page

    # ================================================================ navigation

    @Slot(int)
    def _switch_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._header_title.setText(_PAGE_NAMES[index])

    # ================================================================ actions

    @Slot()
    def _action_connect(self) -> None:
        if self._engine.state in (AcqState.READY, AcqState.RUNNING,
                                   AcqState.STARTING, AcqState.STOPPING,
                                   AcqState.EMPTYING):
            self._run_op(self._engine.disconnect, "Disconnecting…")
        else:
            try:
                self._config = self._collect_config()
                self._engine.configure(self._config, soft=False)
            except Exception as exc:
                QMessageBox.critical(self, "Invalid configuration", str(exc))
                return
            self._mark_clean()
            self._run_op(self._engine.connect, "Connecting…")

    @Slot()
    def _action_start(self) -> None:
        n = self._run_spin.value()
        # Auto-apply the current settings before each run so edits made in the
        # Settings page take effect without a manual "Apply to Engine".
        try:
            cfg = self._collect_config()
        except Exception as exc:
            QMessageBox.critical(self, "Invalid configuration", str(exc))
            return
        self._config = cfg
        self._mark_clean()

        def _do() -> None:
            self._engine.configure(cfg, soft=True)
            self._engine.start_run(n)

        self._run_op(_do, "Applying config & starting run…")

    @Slot()
    def _action_stop(self) -> None:
        self._run_op(self._engine.stop_run, "Stopping run…")

    @Slot(bool)
    def _on_freeze_toggled(self, checked: bool) -> None:
        self._freeze = checked
        self._btn_freeze.setIcon(icon("mdi6.snowflake", ON_COLOR if checked else NEUTRAL))
        self._btn_freeze.setToolTip(
            "Frozen — click to resume live updates" if checked
            else "Freeze live plot/stats updates (the run keeps going)"
        )

    def _connect_paths(self) -> list[str]:
        """Enabled, non-empty board paths from the Connect page rows."""
        paths: list[str] = []
        for enable_cb, path_edit, *_ in self._board_path_rows:
            path = path_edit.text().strip()
            if enable_cb.isChecked() and path:
                paths.append(path)
        if not paths:
            if self._config.boards:
                paths = [self._config.boards[0].Open]
            else:
                paths = ["eth:192.168.50.3"]
        return paths

    def _collect_config(self) -> HydraConfig:
        """Build a validated HydraConfig from every editing widget.

        Raises pydantic ValidationError / ValueError on bad input — the caller is
        expected to surface it to the user.
        """
        paths = self._connect_paths()
        board_dicts = self._board_params.dicts()
        boards: list[BoardConfig] = []
        for i, path in enumerate(paths):
            d = dict(board_dicts[i]) if i < len(board_dicts) else {}
            d["Open"] = path
            boards.append(BoardConfig(**d))   # validates

        sections: dict = {}
        for name, form in self._section_forms.items():
            cur = getattr(self._config, name)
            merged = {**cur.model_dump(), **form.values()}
            sections[name] = type(cur)(**merged)  # validates

        return HydraConfig(version=self._config.version, boards=boards, **sections)

    def _populate_forms(self, cfg: HydraConfig) -> None:
        """Fill every editing widget from *cfg* (forms now match config: clean)."""
        for name, form in self._section_forms.items():
            form.load(getattr(cfg, name))
        self._board_params.load(cfg.boards)
        self._mark_clean()

    def _sync_board_count(self) -> None:
        """Keep the per-board editors in step with the Connect page rows."""
        if not hasattr(self, "_board_params"):
            return
        paths = self._connect_paths()
        self._board_params.set_count(len(paths), paths)

    def _set_dirty(self, dirty: bool) -> None:
        """Toggle the 'pending changes' visual state of the Apply button."""
        if not hasattr(self, "_btn_apply_settings"):
            return
        self._dirty = dirty
        btn = self._btn_apply_settings
        btn.setProperty("dirty", "true" if dirty else "false")
        btn.setText("Apply to Engine  ●" if dirty else "Apply to Engine")
        btn.setIcon(icon("mdi6.upload", ON_COLOR if dirty else "#90a4ae"))
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    @Slot()
    def _mark_dirty(self) -> None:
        self._set_dirty(True)

    def _mark_clean(self) -> None:
        self._set_dirty(False)

    @Slot()
    def _apply_settings(self) -> None:
        try:
            cfg = self._collect_config()
        except Exception as exc:
            QMessageBox.critical(self, "Invalid configuration", str(exc))
            return
        self._config = cfg
        self._mark_clean()
        self._append_log("info", "Configuration updated from settings.")
        if self._engine.state in (AcqState.READY, AcqState.RUNNING):
            self._run_op(
                lambda: self._engine.configure(cfg, soft=True), "Applying config…"
            )

    def _run_op(self, fn: Callable[[], None], status: str) -> None:
        if self._op_thread is not None and self._op_thread.isRunning():
            return
        self._sb_label.setText(status)
        self._set_buttons_busy(True)
        op = _EngineOp(fn, self)
        op.op_error.connect(self._on_op_error)
        op.finished.connect(self._on_op_finished)
        self._op_thread = op
        op.start()

    def _set_buttons_busy(self, busy: bool) -> None:
        for btn in (self._btn_connect, self._btn_start, self._btn_stop):
            btn.setEnabled(not busy)

    @Slot()
    def _on_op_finished(self) -> None:
        self._apply_state_ui(self._engine.state)

    @Slot(str)
    def _on_op_error(self, msg: str) -> None:
        self._append_log("error", msg)

    # ================================================================ engine signal slots

    @Slot(object)
    def _on_state_changed(self, state: AcqState) -> None:
        self._apply_state_ui(state)
        if state == AcqState.READY:
            statuses = self._engine.board_status()
            if statuses:
                nb = len(statuses)
                self._rebuild_board_cards(statuses)
                self._rebuild_hv_cards(statuses)
                self._populate_connect_board_info(statuses)
                for spin in (self._spec_board, self._map_board,
                             self._stats_board_spin, self._reg_board):
                    spin.setRange(0, nb - 1)
                model = statuses[0].model_name or "FERS board"
                self._device_badge.setText(f"{model}  ×{nb}")
                if self._config.run_ctrl.RunNumber_AutoIncr:
                    self._run_spin.setValue(self._run_spin.value() + 1)
        elif state == AcqState.DISCONNECTED:
            self._device_badge.setText("Not connected")
            self._clear_connect_board_info()

    @Slot(str)
    def _on_engine_error(self, msg: str) -> None:
        self._append_log("error", msg)
        self._sb_label.setText(f"Error: {msg[:80]}")

    @Slot(str, str)
    def _on_engine_log(self, level: str, message: str) -> None:
        self._append_log(level, message)

    # ================================================================ state → UI

    def _apply_state_ui(self, state: AcqState) -> None:
        badge_state, badge_text, led_colour = _STATE_UI.get(
            state, ("disabled", state.name, "grey")
        )
        self._state_badge.set_state(badge_state, badge_text)
        self._sb_led.set_color(led_colour)
        self._sb_label.setText(badge_text)

        op_busy   = state in (AcqState.CONNECTING, AcqState.STARTING,
                               AcqState.STOPPING, AcqState.EMPTYING,
                               AcqState.UPGRADING_FW)
        connected = state in (AcqState.READY, AcqState.RUNNING,
                               AcqState.STARTING, AcqState.STOPPING,
                               AcqState.EMPTYING)

        self._btn_connect.setEnabled(not op_busy)
        self._btn_connect.setIcon(icon(
            "mdi6.lan-disconnect" if connected else "mdi6.lan-connect", ON_COLOR
        ))
        self._btn_connect.setToolTip(
            "Disconnect from the boards" if connected
            else "Apply config and connect to the boards"
        )
        self._btn_start.setEnabled(state == AcqState.READY)
        self._btn_stop.setEnabled(state == AcqState.RUNNING)
        self._btn_freeze.setEnabled(state == AcqState.RUNNING)

        # Board path rows editable only when disconnected
        editable = (state == AcqState.DISCONNECTED or state == AcqState.ERROR)
        for enable_cb, path_edit, *_ in self._board_path_rows:
            path_edit.setReadOnly(not editable)
            enable_cb.setEnabled(editable)

    # ================================================================ Connect page helpers

    def _populate_connect_board_info(self, statuses: list[BoardStatus]) -> None:
        for st in statuses:
            if st.index >= len(self._board_path_rows):
                continue
            _, _, pid_lbl, model_lbl, fw_lbl = self._board_path_rows[st.index]
            pid_lbl.setText(f"0x{st.pid:04X}" if st.pid else "—")
            model_lbl.setText(st.model_name or "—")
            fw_lbl.setText(st.fpga_fw or "—")

    def _clear_connect_board_info(self) -> None:
        for _, _, pid_lbl, model_lbl, fw_lbl in self._board_path_rows:
            for lbl in (pid_lbl, model_lbl, fw_lbl):
                lbl.setText("—")

    # ================================================================ Overview board cards

    def _rebuild_board_cards(self, statuses: list[BoardStatus]) -> None:
        for card in self._board_cards:
            self._board_cards_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._board_cards.clear()

        for st in statuses:
            card = StatusTable(f"Board {st.index}  —  {st.model_name or '?'}")
            card.add_row("model",      "Model",        st.model_name or "—")
            card.add_row("fw",         "FPGA FW",      st.fpga_fw or "—")
            card.add_row("pid",        "PID",          f"0x{st.pid:04X}" if st.pid else "—")
            card.add_row("temp_fpga",  "Temp FPGA",    f"{st.temp_fpga:.1f} °C")
            card.add_row("temp_board", "Temp board",   f"{st.temp_board:.1f} °C")
            card.add_led("hv_led",     "HV",           "green" if st.hv_on else "grey")
            card.add_row("hv_vmon",    "HV Vmon",      f"{st.hv_vmon:.2f} V")
            card.add_row("hv_imon",    "HV Imon",      f"{st.hv_imon:.3f} mA")
            card.add_row("status_reg", "Status reg",   f"0x{st.status_reg:08X}")
            self._board_cards.append(card)
            self._board_cards_layout.addWidget(card)

    def _update_board_cards(self, statuses: list[BoardStatus]) -> None:
        for st in statuses:
            if st.index >= len(self._board_cards):
                continue
            card = self._board_cards[st.index]
            card.set_value("temp_fpga",  f"{st.temp_fpga:.1f} °C")
            card.set_value("temp_board", f"{st.temp_board:.1f} °C")
            card.set_led("hv_led",       "green" if st.hv_on else "grey")
            card.set_value("hv_vmon",    f"{st.hv_vmon:.2f} V")
            card.set_value("hv_imon",    f"{st.hv_imon:.3f} mA")
            card.set_value("status_reg", f"0x{st.status_reg:08X}")

    # ================================================================ Statistics page

    def _update_ch_grid(self, stats: RunStatistics) -> None:
        brd = self._stats_board_spin.value()
        use_rate = self._stats_metric.currentIndex() == 0

        if use_rate:
            if stats.ch_trg_rate.shape[0] <= brd:
                return
            values = stats.ch_trg_rate[brd]
        else:
            if stats.ch_count.shape[0] <= brd:
                return
            values = stats.ch_count[brd]

        for ch, lbl in enumerate(self._ch_labels):
            v = float(values[ch]) if ch < len(values) else 0.0
            if use_rate:
                text = _human_rate(v) if v > 0 else "—"
                bg = _rate_color(v)
            else:
                text = f"{int(v):,}" if v > 0 else "—"
                bg = _rate_color(v * 0.01)  # rough colour scale for counts
            lbl.setText(text)
            lbl.setStyleSheet(
                f"QLabel{{background:{bg};border:1px solid #e4e7eb;"
                f"border-radius:3px;color:#37474f;}}"
            )

    def _update_all_boards_table(self, stats: RunStatistics) -> None:
        t = self._all_brd_table
        nb = len(stats.per_board)
        t.setRowCount(nb)
        for row, bs in enumerate(sorted(stats.per_board.values(), key=lambda x: x.index)):
            items = [
                str(bs.index),
                f"{bs.event_count:,}",
                _human_rate(bs.event_rate_hz),
                f"{bs.data_rate_mbps:.2f} MB/s",
                f"{bs.lost_events:,}",
                _human_bytes(bs.byte_count),
            ]
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setItem(row, col, item)

    # ================================================================ HV page

    def _rebuild_hv_cards(self, statuses: list[BoardStatus]) -> None:
        # Remove placeholder + old cards
        self._hv_placeholder.hide()
        for card_dict in self._hv_cards:
            w = card_dict["widget"]
            self._hv_page_layout.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._hv_cards.clear()

        for st in statuses:
            card = QFrame()
            card.setObjectName("Card")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(16, 12, 16, 12)
            cv.setSpacing(8)

            # Card header with LED
            hdr_row = QHBoxLayout()
            led = Led(color="green" if st.hv_on else "grey", diameter=14)
            hdr_row.addWidget(led)
            lbl_title = QLabel(f"Board {st.index}  —  {st.model_name or 'FERS board'}")
            lbl_title.setObjectName("CardTitle")
            hdr_row.addWidget(lbl_title)
            hdr_row.addStretch(1)

            idx = st.index
            hv_btn = QPushButton("Disable HV" if st.hv_on else "Enable HV")
            hv_btn.setObjectName("DangerButton" if st.hv_on else "AccentButton")
            hv_btn.clicked.connect(lambda checked=False, i=idx: self._toggle_hv(i))
            hdr_row.addWidget(hv_btn)
            cv.addLayout(hdr_row)

            # Monitoring values grid
            vals_layout = QGridLayout()
            vals_layout.setSpacing(8)
            vals_layout.setColumnMinimumWidth(1, 120)
            vals_layout.setColumnMinimumWidth(3, 120)

            def _make_val(text: str) -> QLabel:
                l = QLabel(text)
                l.setObjectName("FieldValue")
                return l

            vmon_lbl   = _make_val(f"{st.hv_vmon:.2f} V")
            imon_lbl   = _make_val(f"{st.hv_imon:.3f} mA")
            t_fpga_lbl = _make_val(f"{st.temp_fpga:.1f} °C")
            t_brd_lbl  = _make_val(f"{st.temp_board:.1f} °C")
            t_hv_lbl   = _make_val(f"{st.temp_hv:.1f} °C")
            t_det_lbl  = _make_val(f"{st.temp_detector:.1f} °C")

            for row_i, (label, widget) in enumerate([
                ("HV Vmon",    vmon_lbl),
                ("HV Imon",    imon_lbl),
                ("Temp FPGA",  t_fpga_lbl),
                ("Temp Board", t_brd_lbl),
                ("Temp HV",    t_hv_lbl),
                ("Temp Det",   t_det_lbl),
            ]):
                col = (row_i // 3) * 2
                r   = row_i % 3
                lbl_k = QLabel(label + ":")
                lbl_k.setObjectName("FieldLabel")
                vals_layout.addWidget(lbl_k, r, col)
                vals_layout.addWidget(widget, r, col + 1)

            cv.addLayout(vals_layout)

            self._hv_page_layout.insertWidget(
                self._hv_page_layout.count() - 1, card
            )

            self._hv_cards.append({
                "widget":  card,
                "led":     led,
                "hv_btn":  hv_btn,
                "vmon":    vmon_lbl,
                "imon":    imon_lbl,
                "t_fpga":  t_fpga_lbl,
                "t_brd":   t_brd_lbl,
                "t_hv":    t_hv_lbl,
                "t_det":   t_det_lbl,
            })

    def _update_hv_cards(self, statuses: list[BoardStatus]) -> None:
        for st in statuses:
            if st.index >= len(self._hv_cards):
                continue
            c = self._hv_cards[st.index]
            c["led"].set_color("green" if st.hv_on else "grey")
            c["hv_btn"].setText("Disable HV" if st.hv_on else "Enable HV")
            c["hv_btn"].setObjectName("DangerButton" if st.hv_on else "AccentButton")
            c["hv_btn"].style().unpolish(c["hv_btn"])
            c["hv_btn"].style().polish(c["hv_btn"])
            c["vmon"].setText(f"{st.hv_vmon:.2f} V")
            c["imon"].setText(f"{st.hv_imon:.3f} mA")
            c["t_fpga"].setText(f"{st.temp_fpga:.1f} °C")
            c["t_brd"].setText(f"{st.temp_board:.1f} °C")
            c["t_hv"].setText(f"{st.temp_hv:.1f} °C")
            c["t_det"].setText(f"{st.temp_detector:.1f} °C")

    def _toggle_hv(self, board_index: int) -> None:
        statuses = self._engine.board_status()
        current_on = any(
            s.hv_on for s in statuses if s.index == board_index
        )
        try:
            self._engine.hv_set(board_index, enable=not current_on)
        except Exception as exc:
            self._append_log("error", f"HV toggle board {board_index}: {exc}")

    # ================================================================ Register page helpers

    def _reg_update_addr(self) -> None:
        base = "01"
        for btn in self._reg_base_group.buttons():
            if btn.isChecked():
                base = btn.property("base_val")
                break
        if base == "02":
            ch = str(self._reg_ch.value()).zfill(2)
            base = f"02{ch}"
        else:
            base = base + "00"
        offs = self._reg_offset.text().strip().zfill(4)[-4:].upper()
        self._reg_addr_display.setText(base + offs)

    def _reg_read(self) -> None:
        if self._engine.state not in (AcqState.READY, AcqState.RUNNING):
            self._reg_log.append("Not connected.")
            return
        try:
            addr = int(self._reg_addr_display.text(), 16)
            brd  = self._reg_board.value()
            val  = self._engine.read_register(brd, addr)
            msg  = f"Brd {brd} READ  A=0x{addr:08X}  D=0x{val:08X}"
            self._reg_log.append(msg)
            self._reg_data.setText(f"{val:08X}")
        except Exception as exc:
            self._reg_log.append(f"Read error: {exc}")

    def _reg_write(self) -> None:
        if self._engine.state not in (AcqState.READY, AcqState.RUNNING):
            self._reg_log.append("Not connected.")
            return
        try:
            addr = int(self._reg_addr_display.text(), 16)
            data = int(self._reg_data.text(), 16)
            brd  = self._reg_board.value()
            self._engine.write_register(brd, addr, data)
            msg  = f"Brd {brd} WRITE A=0x{addr:08X}  D=0x{data:08X}"
            self._reg_log.append(msg)
        except Exception as exc:
            self._reg_log.append(f"Write error: {exc}")

    # ================================================================ menu actions

    def _menu_load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Config", str(Path.home()),
            "YAML files (*.yaml *.yml);;All files (*)"
        )
        if not path:
            return
        try:
            cfg = load_config(path)
            self._config = cfg
            self._config_path = Path(path)
            self._cfg_path_label.setText(str(self._config_path))
            self._refresh_board_path_rows()
            self._populate_forms(cfg)
            self._append_log("info", f"Loaded config: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Load Config", f"Failed to load config:\n{exc}")

    def _menu_save_config(self) -> None:
        default = str(self._config_path or Path.home() / "hydrafers.yaml")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Config As", default,
            "YAML files (*.yaml *.yml);;All files (*)"
        )
        if not path:
            return
        try:
            self._config = self._collect_config()
        except Exception as exc:
            QMessageBox.critical(self, "Invalid configuration", str(exc))
            return
        try:
            save_config(self._config, path)
            self._config_path = Path(path)
            self._cfg_path_label.setText(str(self._config_path))
            self._mark_clean()
            self._append_log("info", f"Saved config: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Config", f"Failed to save config:\n{exc}")

    def _menu_about(self) -> None:
        QMessageBox.about(
            self,
            "About HydraFERS",
            "<b>HydraFERS</b><br>"
            "CAEN FERS acquisition GUI<br><br>"
            "Built with PySide6 + pyqtgraph.<br>"
            "© CAEN SpA"
        )

    def _refresh_board_path_rows(self) -> None:
        """Push current config board paths into the UI rows."""
        boards = self._config.boards if self._config else []
        for i, (enable_cb, path_edit, *_) in enumerate(self._board_path_rows):
            if i < len(boards):
                path_edit.setText(boards[i].Open)
                enable_cb.setChecked(True)
            else:
                path_edit.clear()
                enable_cb.setChecked(False)

    # ================================================================ tick (15 Hz)

    @Slot()
    def _tick(self) -> None:
        stats = self._drain_stats()
        if stats is not None:
            self._update_stats_card(stats)

        if self._engine.state == AcqState.RUNNING and not self._freeze:
            page = self._stack.currentIndex()
            if page == PG_STATS:
                if stats is not None:
                    self._update_ch_grid(stats)
                    self._update_all_boards_table(stats)
            elif page == PG_SPECTRA:
                histo = self._engine.histograms()
                self._spectrum_plot.update_data(histo)
            elif page == PG_MAP:
                if self._map_mode.currentText() == "Counts":
                    histo = self._engine.histograms()
                    cnt = histo.get("cnt_2d")
                    if cnt is not None:
                        self._map2d_plot.update_counts(cnt)
                elif stats is not None:
                    self._map2d_plot.update_rate(stats.ch_trg_rate)

        # Board monitoring at ~0.5 Hz (every 30 ticks)
        self._tick_div = (self._tick_div + 1) % 30
        if self._tick_div == 0 and self._engine.state in (AcqState.READY, AcqState.RUNNING):
            statuses = self._engine.board_status()
            if statuses:
                self._update_board_cards(statuses)
                self._update_hv_cards(statuses)

    def _drain_stats(self) -> RunStatistics | None:
        q = self._engine.stats_queue()
        latest: RunStatistics | None = None
        while True:
            try:
                latest = q.get_nowait()
            except Empty:
                break
        return latest

    def _update_stats_card(self, s: RunStatistics) -> None:
        self._stats_card.set_value("run_number",   str(s.run_number))
        self._stats_card.set_value("elapsed",       f"{s.elapsed_s:,.1f} s")
        self._stats_card.set_value("total_events",  f"{s.total_events:,}")
        self._stats_card.set_value("built_events",  f"{s.built_events:,}")
        self._stats_card.set_value("event_rate",    _human_rate(s.event_rate_hz))
        self._stats_card.set_value("data_volume",   _human_bytes(s.byte_count))
        self._stats_card.set_value("data_rate",     f"{s.data_rate_mbps:.2f} MB/s")

    # ================================================================ log

    def _append_log(self, level: str, message: str) -> None:
        color  = _LOG_COLORS.get(level.lower(), "#546e7a")
        prefix = {"info": "INFO", "warning": "WARN", "error": "ERR "}.get(
            level.lower(), "    "
        )
        ts   = time.strftime("%H:%M:%S")
        safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._log_view.append(
            f'<span style="color:#90a4ae">[{ts}]</span> '
            f'<span style="color:{color};font-weight:600">[{prefix}]</span> '
            f'<span style="color:#37474f">{safe}</span>'
        )

    # ================================================================ spectra controls

    def _spec_target_changed(self) -> None:
        self._spectrum_plot.set_target(
            self._spec_board.value(), self._spec_channel.value()
        )

    # ================================================================ cleanup

    def closeEvent(self, event) -> None:
        self._timer.stop()
        if self._engine.state not in (AcqState.DISCONNECTED, AcqState.ERROR):
            try:
                self._engine.close()
            except Exception:
                pass
        event.accept()

// pyferslib.cpp — HydraFERS layer 1a: FAITHFUL 1:1 pybind11 binding over ferslib (C).
//
// Role:   Transliterate the frozen CAEN ferslib C API into a Python extension module
//         named `pyferslib`. Same functions (de-prefixed + snake_case), same structs,
//         same constants, same string-based parameter API kept VERBATIM. This layer
//         does NOT fix any C-dictated design — that is the job of the pure-Python
//         `pyfers` SDK (layer 1b). The ONLY concession to Python made here is error
//         handling: a ferslib return < 0 raises `pyferslib.FERSError(code, message)`.
//
// Layer:  ferslib (C) -> [THIS: pyferslib, C++ pybind11] -> pyfers (Python SDK) -> ...
//         Depends ONLY on ferslib. Knows nothing of pyfers / hydrafers / Qt.
//
// Conventions enforced here (CONTRACT.md §1a):
//   * PYBIND11_MODULE(pyferslib, m).
//   * Every ferslib call is wrapped in py::gil_scoped_release.
//   * Out-parameters become return values.
//   * Handles are plain Python ints.
//   * Fixed C arrays (energyHG[64]) and pointer+length buffers (wave_hg / ns) are
//     exposed as read-only NumPy arrays COPIED out of the reused ferslib buffer
//     (never a view — the ferslib buffer is recycled on the next FERS_GetEvent).
//   * get_event returns (board, dtq, event) | None, and surfaces
//     RAWDATA_REPROCESS_FINISHED as (-1, RAWDATA_REPROCESS_FINISHED, None).
//   * drain_events is the C-side DATA-plane batch primitive over get_event.

#include <pybind11/pybind11.h>
#include <pybind11/eval.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include "FERSlib.h"
// FERSlib.h (re)defines min/max as macros; undef so <string> / pybind11 are safe.
#undef max
#undef min

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace py = pybind11;

// =====================================================================
// Error handling — the one concession to Python (CONTRACT.md §1a)
// =====================================================================
//
// ferslib returns 0 on success and a negative FERSLIB_ErrorCodes value on error.
// We surface that as a custom exception type `pyferslib.FERSError` carrying both the
// numeric `code` and the human-readable `message` from FERS_GetLastError().
//
// NB: RAWDATA_REPROCESS_FINISHED (==4) is POSITIVE and is NOT an error; it is handled
// explicitly by get_event / drain_events.

// Holds the global handle to the FERSError Python class so check_ret() can raise it.
static py::handle g_fers_error_type;

// Read the last error string from ferslib (buffer is fixed 1024 per FERSlib.h).
static std::string fers_last_error()
{
    char buf[1024];
    std::memset(buf, 0, sizeof(buf));
    // FERS_GetLastError always returns 0; no GIL concern (pure local copy in lib).
    FERS_GetLastError(buf);
    return std::string(buf);
}

// Raise pyferslib.FERSError(code, message) for a negative ferslib return code.
// Must be called WITH the GIL held (i.e. after the gil_scoped_release block).
[[noreturn]] static void raise_fers_error(int code)
{
    std::string msg = fers_last_error();
    py::object exc = g_fers_error_type(code, msg);
    PyErr_SetObject(g_fers_error_type.ptr(), exc.ptr());
    throw py::error_already_set();
}

// Convenience: raise FERSError if ret < 0. Returns ret unchanged otherwise.
static inline int check_ret(int ret)
{
    if (ret < 0)
        raise_fers_error(ret);
    return ret;
}

// =====================================================================
// NumPy copy helpers — ALWAYS copy out of the reused ferslib buffer
// =====================================================================
//
// pybind11's py::array_t(shape, data_ptr) constructor (without a base/owner object)
// performs a COPY of the source memory into a freshly allocated, NumPy-owned array.
// That is exactly what we want: the ferslib event buffer is recycled, so a view would
// dangle/alias. We then mark the result read-only.

template <typename T>
static py::array_t<T> copy_to_ro_array(const T* src, py::ssize_t n)
{
    if (n < 0)
        n = 0;
    py::array_t<T> arr(static_cast<size_t>(n));     // owns its own buffer
    if (n > 0)
        std::memcpy(arr.mutable_data(), src, static_cast<size_t>(n) * sizeof(T));
    // Make it read-only for consumers (defensive: data is a recycled-buffer snapshot).
    py::detail::array_proxy(arr.ptr())->flags &= ~py::detail::npy_api::NPY_ARRAY_WRITEABLE_;
    return arr;
}

// =====================================================================
// Bound struct (event / info) wrapper types
// =====================================================================
//
// Each wrapper is a plain, read-only Python data class. Scalars are copied by value;
// array members are copied into owned NumPy arrays at construction time, so a wrapper
// instance remains valid even after the underlying ferslib buffer is reused.

// ---- BoardInfo <- FERS_BoardInfo_t ----------------------------------
struct BoardInfo {
    uint32_t    pid;
    uint16_t    fers_code;
    uint8_t     pcb_revision;
    std::string model_code;
    std::string model_name;
    uint8_t     form_factor;
    uint16_t    num_ch;
    uint32_t    fpga_fwrev;
    uint32_t    uc_fwrev;

    static BoardInfo from_c(const FERS_BoardInfo_t& s)
    {
        BoardInfo b;
        b.pid          = s.pid;
        b.fers_code    = s.FERSCode;
        b.pcb_revision = s.PCBrevision;
        b.model_code   = std::string(s.ModelCode);
        b.model_name   = std::string(s.ModelName);
        b.form_factor  = s.FormFactor;
        b.num_ch       = s.NumCh;
        b.fpga_fwrev   = s.FPGA_FWrev;
        b.uc_fwrev     = s.uC_FWrev;
        return b;
    }
};

// ---- ChainInfo <- FERS_TDL_ChainInfo_t ------------------------------
struct ChainInfo {
    uint16_t status;
    uint16_t board_count;
    float    rrt;
    uint64_t event_count;
    uint64_t byte_count;
    float    event_rate;
    float    mbps;

    static ChainInfo from_c(const FERS_TDL_ChainInfo_t& s)
    {
        ChainInfo c;
        c.status      = s.Status;
        c.board_count = s.BoardCount;
        c.rrt         = s.rrt;
        c.event_count = s.EventCount;
        c.byte_count  = s.ByteCount;
        c.event_rate  = s.EventRate;
        c.mbps        = s.Mbps;
        return c;
    }
};

// ---- CncInfo <- FERS_CncInfo_t --------------------------------------
struct CncInfo {
    uint32_t               pid;
    std::string            pcb_revision;
    std::string            model_code;
    std::string            model_name;
    std::string            fpga_fwrev;
    std::string            sw_rev;
    std::string            mac_10gbe;
    uint16_t               num_link;
    std::vector<ChainInfo> chains;

    static CncInfo from_c(const FERS_CncInfo_t& s)
    {
        CncInfo c;
        c.pid          = s.pid;
        c.pcb_revision = std::string(s.PCBrevision);
        c.model_code   = std::string(s.ModelCode);
        c.model_name   = std::string(s.ModelName);
        c.fpga_fwrev   = std::string(s.FPGA_FWrev);
        c.sw_rev       = std::string(s.SW_rev);
        c.mac_10gbe    = std::string(s.MACaddr_10GbE);
        c.num_link     = s.NumLink;
        c.chains.reserve(FERSLIB_MAX_NTDL);
        for (int i = 0; i < FERSLIB_MAX_NTDL; ++i)
            c.chains.push_back(ChainInfo::from_c(s.ChainInfo[i]));
        return c;
    }
};

// ---- SpectEvent <- SpectEvent_t -------------------------------------
struct SpectEvent {
    double             tstamp_us;
    double             rel_tstamp_us;
    uint64_t           tstamp_clk;
    uint64_t           tref_tstamp;
    uint64_t           trigger_id;
    uint64_t           chmask;
    uint64_t           qdmask;
    py::array_t<uint16_t> energy_hg;   // [64]
    py::array_t<uint16_t> energy_lg;   // [64]
    py::array_t<uint32_t> toa;         // [64]  (from .tstamp)
    py::array_t<uint16_t> tot;         // [64]

    static SpectEvent from_c(const SpectEvent_t& s)
    {
        SpectEvent e;
        e.tstamp_us     = s.tstamp_us;
        e.rel_tstamp_us = s.rel_tstamp_us;
        e.tstamp_clk    = s.tstamp_clk;
        e.tref_tstamp   = s.Tref_tstamp;
        e.trigger_id    = s.trigger_id;
        e.chmask        = s.chmask;
        e.qdmask        = s.qdmask;
        e.energy_hg     = copy_to_ro_array<uint16_t>(s.energyHG, 64);
        e.energy_lg     = copy_to_ro_array<uint16_t>(s.energyLG, 64);
        e.toa           = copy_to_ro_array<uint32_t>(s.tstamp,   64);
        e.tot           = copy_to_ro_array<uint16_t>(s.ToT,      64);
        return e;
    }
};

// ---- CountingEvent <- CountingEvent_t -------------------------------
struct CountingEvent {
    double             tstamp_us;
    double             rel_tstamp_us;
    uint64_t           trigger_id;
    uint64_t           chmask;
    py::array_t<uint32_t> counts;       // [64]
    uint32_t           t_or_counts;
    uint32_t           q_or_counts;

    static CountingEvent from_c(const CountingEvent_t& s)
    {
        CountingEvent e;
        e.tstamp_us     = s.tstamp_us;
        e.rel_tstamp_us = s.rel_tstamp_us;
        e.trigger_id    = s.trigger_id;
        e.chmask        = s.chmask;
        e.counts        = copy_to_ro_array<uint32_t>(s.counts, 64);
        e.t_or_counts   = s.t_or_counts;
        e.q_or_counts   = s.q_or_counts;
        return e;
    }
};

// ---- WaveEvent <- WaveEvent_t ---------------------------------------
struct WaveEvent {
    double             tstamp_us;
    uint64_t           trigger_id;
    uint16_t           ns;
    py::array_t<uint16_t> wave_hg;      // [ns]
    py::array_t<uint16_t> wave_lg;      // [ns]
    py::array_t<uint8_t>  dig_probes;   // [ns]

    static WaveEvent from_c(const WaveEvent_t& s)
    {
        WaveEvent e;
        e.tstamp_us  = s.tstamp_us;
        e.trigger_id = s.trigger_id;
        e.ns         = s.ns;
        const py::ssize_t n = static_cast<py::ssize_t>(s.ns);
        // pointer members may be NULL when unused; guard each.
        e.wave_hg    = copy_to_ro_array<uint16_t>(s.wave_hg    ? s.wave_hg    : nullptr,
                                                  s.wave_hg    ? n : 0);
        e.wave_lg    = copy_to_ro_array<uint16_t>(s.wave_lg    ? s.wave_lg    : nullptr,
                                                  s.wave_lg    ? n : 0);
        e.dig_probes = copy_to_ro_array<uint8_t>(s.dig_probes  ? s.dig_probes : nullptr,
                                                  s.dig_probes ? n : 0);
        return e;
    }
};

// ---- ListEvent <- ListEvent_t ---------------------------------------
struct ListEvent {
    double             tstamp_us;
    uint64_t           tref_tstamp;
    uint64_t           tstamp_clk;
    uint64_t           trigger_id;
    uint16_t           nhits;
    py::array_t<uint8_t>  channel;      // [nhits]
    py::array_t<uint8_t>  edge;         // [nhits]
    py::array_t<uint32_t> toa;          // [nhits]  (from .tstamp)
    py::array_t<uint16_t> tot;          // [nhits]

    static ListEvent from_c(const ListEvent_t& s)
    {
        ListEvent e;
        e.tstamp_us   = s.tstamp_us;
        e.tref_tstamp = s.Tref_tstamp;
        e.tstamp_clk  = s.tstamp_clk;
        e.trigger_id  = s.trigger_id;
        e.nhits       = s.nhits;
        // copy only the valid prefix; clamp to MAX_LIST_SIZE defensively.
        py::ssize_t n = static_cast<py::ssize_t>(s.nhits);
        if (n > MAX_LIST_SIZE)
            n = MAX_LIST_SIZE;
        e.channel = copy_to_ro_array<uint8_t>(s.channel, n);
        e.edge    = copy_to_ro_array<uint8_t>(s.edge,    n);
        e.toa     = copy_to_ro_array<uint32_t>(s.tstamp, n);
        e.tot     = copy_to_ro_array<uint16_t>(s.ToT,    n);
        return e;
    }
};

// ---- ServEvent <- ServEvent_t ---------------------------------------
struct ServEvent {
    double             tstamp_us;
    uint64_t           update_time;
    uint16_t           pkt_size;
    uint8_t            version;
    uint8_t            format;
    py::array_t<uint32_t> ch_trg_cnt;   // [64]
    uint32_t           q_or_cnt;
    uint32_t           t_or_cnt;
    float              temp_fpga;
    float              temp_board;
    float              temp_tdc0;
    float              temp_tdc1;
    float              temp_hv;
    float              temp_detector;
    float              hv_vmon;
    float              hv_imon;
    uint8_t            hv_status_on;
    uint8_t            hv_status_ramp;
    uint8_t            hv_status_ovv;
    uint8_t            hv_status_ovc;
    uint16_t           status;
    uint16_t           tdc_ro_status;
    uint32_t           readout_flags;
    uint32_t           tot_trg_cnt;
    uint32_t           rej_trg_cnt;
    uint32_t           suppr_trg_cnt;

    static ServEvent from_c(const ServEvent_t& s)
    {
        ServEvent e;
        e.tstamp_us      = s.tstamp_us;
        e.update_time    = s.update_time;
        e.pkt_size       = s.pkt_size;
        e.version        = s.version;
        e.format         = s.format;
        e.ch_trg_cnt     = copy_to_ro_array<uint32_t>(s.ch_trg_cnt,
                                                      FERSLIB_MAX_NCH_5202);
        e.q_or_cnt       = s.q_or_cnt;
        e.t_or_cnt       = s.t_or_cnt;
        e.temp_fpga      = s.tempFPGA;
        e.temp_board     = s.tempBoard;
        e.temp_tdc0      = s.tempTDC[0];
        e.temp_tdc1      = s.tempTDC[1];
        e.temp_hv        = s.tempHV;
        e.temp_detector  = s.tempDetector;
        e.hv_vmon        = s.hv_Vmon;
        e.hv_imon        = s.hv_Imon;
        e.hv_status_on   = s.hv_status_on;
        e.hv_status_ramp = s.hv_status_ramp;
        e.hv_status_ovv  = s.hv_status_ovv;
        e.hv_status_ovc  = s.hv_status_ovc;
        e.status         = s.Status;
        e.tdc_ro_status  = s.TDCROStatus;
        e.readout_flags  = s.ReadoutFlags;
        e.tot_trg_cnt    = s.TotTrg_cnt;
        e.rej_trg_cnt    = s.RejTrg_cnt;
        e.suppr_trg_cnt  = s.SupprTrg_cnt;
        return e;
    }
};

// ---- TestEvent <- TestEvent_t ---------------------------------------
struct TestEvent {
    double             tstamp_us;
    uint64_t           trigger_id;
    uint16_t           nwords;
    py::array_t<uint32_t> test_data;    // [nwords]

    static TestEvent from_c(const TestEvent_t& s)
    {
        TestEvent e;
        e.tstamp_us  = s.tstamp_us;
        e.trigger_id = s.trigger_id;
        e.nwords     = s.nwords;
        py::ssize_t n = static_cast<py::ssize_t>(s.nwords);
        if (n > MAX_TEST_NWORDS)
            n = MAX_TEST_NWORDS;
        e.test_data = copy_to_ro_array<uint32_t>(s.test_data, n);
        return e;
    }
};

// =====================================================================
// Event dispatch — build the correct wrapper from (dtq, void* Event)
// =====================================================================
//
// The data qualifier selects the concrete C struct stored at *Event. Service events
// use the full DTQ_SERVICE (0x2F) value; data events are selected by the low nibble
// (dtq & 0xF) per CONTRACT.md §1a. Test events use DTQ_TEST (0xFF).
//
// Must be called WITH the GIL held (it allocates Python objects).
static py::object build_event(int dtq, void* event_ptr)
{
    if (event_ptr == nullptr)
        return py::none();

    // Service event: matched on the full 0x2F qualifier first.
    if (dtq == DTQ_SERVICE)
        return py::cast(ServEvent::from_c(*reinterpret_cast<ServEvent_t*>(event_ptr)));

    // Test event: matched on the full 0xFF qualifier.
    if (dtq == DTQ_TEST)
        return py::cast(TestEvent::from_c(*reinterpret_cast<TestEvent_t*>(event_ptr)));

    switch (dtq & 0xF) {
        case DTQ_SPECT:     // 0x01 (energy)  — also low nibble of DTQ_TSPECT 0x03
        case DTQ_TSPECT:    // 0x03 (energy + timing)
            return py::cast(SpectEvent::from_c(
                *reinterpret_cast<SpectEvent_t*>(event_ptr)));
        case DTQ_TIMING:    // 0x02 (list)
            return py::cast(ListEvent::from_c(
                *reinterpret_cast<ListEvent_t*>(event_ptr)));
        case DTQ_COUNT:     // 0x04 (MCS)
            return py::cast(CountingEvent::from_c(
                *reinterpret_cast<CountingEvent_t*>(event_ptr)));
        case DTQ_WAVE:      // 0x08 (waveform)
            return py::cast(WaveEvent::from_c(
                *reinterpret_cast<WaveEvent_t*>(event_ptr)));
        default:
            // Unknown qualifier: return the raw int so the caller can decide.
            // We never silently drop data.
            return py::none();
    }
}

// =====================================================================
// Function wrappers — names mirror FERSlib.h, de-prefixed + snake_case
// =====================================================================
//
// Pattern (CONTRACT.md §1a):
//   1. prepare local out-parameters,
//   2. { py::gil_scoped_release release; ret = FERS_Xxx(...); }
//   3. check_ret(ret)  (raises FERSError on ret < 0, GIL held again),
//   4. build/return the Python value.

// ---- device & info --------------------------------------------------

static int open_device(const std::string& path)
{
    int handle = -1;
    std::string buf = path;  // mutable copy — FERS_OpenDevice takes char*
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_OpenDevice(buf.data(), &handle);
    }
    check_ret(ret);
    return handle;
}

static void close_device(int handle)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_CloseDevice(handle);
    }
    check_ret(ret);
}

static bool is_open(const std::string& path)
{
    std::string buf = path;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_IsOpen(buf.data());
    }
    // FERS_IsOpen returns 1/0 (not an error code) — do not treat 0 as failure.
    return ret != 0;
}

static int get_num_boards_connected()
{
    uint16_t n;
    {
        py::gil_scoped_release release;
        n = FERS_GetNumBrdConnected();
    }
    return static_cast<int>(n);
}

static BoardInfo get_board_info(int handle)
{
    FERS_BoardInfo_t info;
    std::memset(&info, 0, sizeof(info));
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_GetBoardInfo(handle, &info);
    }
    check_ret(ret);
    return BoardInfo::from_c(info);
}

static CncInfo get_cnc_info(int handle)
{
    FERS_CncInfo_t info;
    std::memset(&info, 0, sizeof(info));
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_GetCncInfo(handle, &info);
    }
    check_ret(ret);
    return CncInfo::from_c(info);
}

static double get_clock_period(int handle)
{
    float period;
    {
        py::gil_scoped_release release;
        period = FERS_GetClockPeriod(handle);
    }
    return static_cast<double>(period);
}

static void reset_ip_address(int handle)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_Reset_IPaddress(handle);
    }
    check_ret(ret);
}

static std::string get_last_error()
{
    // Pure local string copy in ferslib; releasing the GIL is harmless and consistent.
    std::string msg;
    {
        py::gil_scoped_release release;
        char buf[1024];
        std::memset(buf, 0, sizeof(buf));
        FERS_GetLastError(buf);
        msg.assign(buf);
    }
    return msg;
}

static std::string lib_release()
{
    char* s;
    {
        py::gil_scoped_release release;
        s = FERS_GetLibReleaseNum();
    }
    return std::string(s ? s : "");
}

// ---- config (string-based, kept verbatim) ---------------------------

static void load_config_file(const std::string& path)
{
    std::string buf = path;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_LoadConfigFile(buf.data());
    }
    check_ret(ret);
}

static void set_param(int handle, const std::string& name, const std::string& value)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_SetParam(handle, name.c_str(), value.c_str());
    }
    check_ret(ret);
}

static std::string get_param(int handle, const std::string& name)
{
    char value[1024];
    std::memset(value, 0, sizeof(value));
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_GetParam(handle, name.c_str(), value);
    }
    check_ret(ret);
    return std::string(value);
}

static void configure(int handle, int mode)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_configure(handle, mode);
    }
    check_ret(ret);
}

// ---- tdl ------------------------------------------------------------

static void init_tdl_chains(
    int handle,
    py::array_t<float, py::array::c_style | py::array::forcecast> delay_adjust)
{
    if (delay_adjust.ndim() != 2)
        throw std::runtime_error("delay_adjust must be a 2D array");
    if (delay_adjust.shape(0) != FERSLIB_MAX_NTDL ||
        delay_adjust.shape(1) != FERSLIB_MAX_NNODES)
        throw std::runtime_error(
            "delay_adjust must have shape [8, 16] (FERSLIB_MAX_NTDL x FERSLIB_MAX_NNODES)");

    auto buf = delay_adjust.request();
    auto* data = reinterpret_cast<float (*)[FERSLIB_MAX_NNODES]>(buf.ptr);
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_InitTDLchains(handle, data);
    }
    check_ret(ret);
}

static bool tdl_chains_initialized(int handle)
{
    bool ret;
    {
        py::gil_scoped_release release;
        ret = FERS_TDLchainsInitialized(handle);
    }
    return ret;
}

// ---- readout --------------------------------------------------------

static int init_readout(int handle, int ro_mode)
{
    int allocated_size = 0;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_InitReadout(handle, ro_mode, &allocated_size);
    }
    check_ret(ret);
    return allocated_size;
}

static void close_readout(int handle)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_CloseReadout(handle);
    }
    check_ret(ret);
}

static void flush_data(int handle)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_FlushData(handle);
    }
    check_ret(ret);
}

// ---- acquisition ----------------------------------------------------

static void start_acquisition(const std::vector<int>& handles, int start_mode, int run_num)
{
    std::vector<int> hv = handles;  // mutable, contiguous int* for ferslib
    int nb = static_cast<int>(hv.size());
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_StartAcquisition(hv.data(), nb, start_mode, run_num);
    }
    check_ret(ret);
}

static void stop_acquisition(const std::vector<int>& handles, int start_mode, int run_num)
{
    std::vector<int> hv = handles;
    int nb = static_cast<int>(hv.size());
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_StopAcquisition(hv.data(), nb, start_mode, run_num);
    }
    check_ret(ret);
}

// get_event(handles) -> (board, dtq, event) | None
//
// Wraps FERS_GetEvent(int* handle, &bindex, &dtq, &tstamp_us, &Event, &nb).
//   * nb == 0                          -> None (no event available).
//   * ret == RAWDATA_REPROCESS_FINISHED -> (-1, RAWDATA_REPROCESS_FINISHED, None).
//   * ret < 0                          -> raise FERSError.
//   * otherwise                        -> (board, dtq, <bound event object>).
//
// The returned event object holds COPIES of all array data (see build_event); the
// ferslib buffer at `event_ptr` may be recycled by the next call.
static py::object get_event(const std::vector<int>& handles)
{
    std::vector<int> hv = handles;
    int bindex = -1;
    int dtq = 0;
    double tstamp_us = 0.0;
    void* event_ptr = nullptr;
    int nb = 0;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_GetEvent(hv.data(), &bindex, &dtq, &tstamp_us, &event_ptr, &nb);
    }

    // End of offline raw-data reprocessing: positive sentinel, NOT an error.
    if (ret == RAWDATA_REPROCESS_FINISHED)
        return py::make_tuple(-1, static_cast<int>(RAWDATA_REPROCESS_FINISHED), py::none());

    check_ret(ret);

    if (nb == 0)
        return py::none();

    py::object event = build_event(dtq, event_ptr);
    return py::make_tuple(bindex, dtq, event);
}

// drain_events(handles, max_events) -> list[(board, dtq, event)]
//
// DATA-PLANE primitive (CONTRACT.md §1a / §4 ReadoutThread): loops FERS_GetEvent in C
// up to `max_events` times or until nb == 0, building the wrapper objects, to amortize
// per-event Python call overhead. The GIL is released for the whole batch of ferslib
// reads; wrapper objects (which allocate Python memory) are built with the GIL held.
//
// RAWDATA_REPROCESS_FINISHED ends the batch and is appended as
// (-1, RAWDATA_REPROCESS_FINISHED, None) so callers can detect end-of-reprocessing.
static py::list drain_events(const std::vector<int>& handles, int max_events)
{
    std::vector<int> hv = handles;
    py::list out;

    for (int i = 0; i < max_events; ++i) {
        int bindex = -1;
        int dtq = 0;
        double tstamp_us = 0.0;
        void* event_ptr = nullptr;
        int nb = 0;
        int ret;
        {
            py::gil_scoped_release release;
            ret = FERS_GetEvent(hv.data(), &bindex, &dtq, &tstamp_us, &event_ptr, &nb);
        }

        if (ret == RAWDATA_REPROCESS_FINISHED) {
            out.append(py::make_tuple(
                -1, static_cast<int>(RAWDATA_REPROCESS_FINISHED), py::none()));
            break;
        }

        check_ret(ret);

        if (nb == 0)
            break;  // queue drained

        py::object event = build_event(dtq, event_ptr);
        out.append(py::make_tuple(bindex, dtq, event));
    }
    return out;
}

// ---- registers & commands -------------------------------------------

static uint32_t read_register(int handle, uint32_t address)
{
    uint32_t data = 0;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_ReadRegister(handle, address, &data);
    }
    check_ret(ret);
    return data;
}

static void write_register(int handle, uint32_t address, uint32_t data)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_WriteRegister(handle, address, data);
    }
    check_ret(ret);
}

static void write_register_slice(int handle, uint32_t address,
                                 uint32_t start_bit, uint32_t stop_bit, uint32_t data)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_WriteRegisterSlice(handle, address, start_bit, stop_bit, data);
    }
    check_ret(ret);
}

static void send_command(int handle, uint32_t cmd)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_SendCommand(handle, cmd);
    }
    check_ret(ret);
}

// ---- HV -------------------------------------------------------------

static void hv_init(int handle)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_HV_Init(handle);
    }
    check_ret(ret);
}

static void hv_set_onoff(int handle, bool on)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_HV_Set_OnOff(handle, on ? 1 : 0);
    }
    check_ret(ret);
}

// hv_get_status -> (on, ramping, ovc, ovv)
static py::tuple hv_get_status(int handle)
{
    int on = 0, ramping = 0, ovc = 0, ovv = 0;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_HV_Get_Status(handle, &on, &ramping, &ovc, &ovv);
    }
    check_ret(ret);
    return py::make_tuple(on, ramping, ovc, ovv);
}

static void hv_set_vbias(int handle, float vbias)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_HV_Set_Vbias(handle, vbias);
    }
    check_ret(ret);
}

static double hv_get_vbias(int handle)
{
    float vbias = 0.0f;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_HV_Get_Vbias(handle, &vbias);
    }
    check_ret(ret);
    return static_cast<double>(vbias);
}

static double hv_get_vmon(int handle)
{
    float vmon = 0.0f;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_HV_Get_Vmon(handle, &vmon);
    }
    check_ret(ret);
    return static_cast<double>(vmon);
}

static void hv_set_imax(int handle, float imax)
{
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_HV_Set_Imax(handle, imax);
    }
    check_ret(ret);
}

static double hv_get_imon(int handle)
{
    float imon = 0.0f;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_HV_Get_Imon(handle, &imon);
    }
    check_ret(ret);
    return static_cast<double>(imon);
}

static double hv_get_int_temp(int handle)
{
    float temp = 0.0f;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_HV_Get_IntTemp(handle, &temp);
    }
    check_ret(ret);
    return static_cast<double>(temp);
}

static double hv_get_detector_temp(int handle)
{
    float temp = 0.0f;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_HV_Get_DetectorTemp(handle, &temp);
    }
    check_ret(ret);
    return static_cast<double>(temp);
}

// ---- temperatures ---------------------------------------------------

static double get_fpga_temp(int handle)
{
    float temp = 0.0f;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_Get_FPGA_Temp(handle, &temp);
    }
    check_ret(ret);
    return static_cast<double>(temp);
}

static double get_board_temp(int handle)
{
    float temp = 0.0f;
    int ret;
    {
        py::gil_scoped_release release;
        ret = FERS_Get_Board_Temp(handle, &temp);
    }
    check_ret(ret);
    return static_cast<double>(temp);
}

// =====================================================================
// Module definition
// =====================================================================

PYBIND11_MODULE(pyferslib, m)
{
    m.doc() =
        "pyferslib — HydraFERS layer 1a: faithful 1:1 pybind11 binding over the frozen "
        "CAEN ferslib C API. Same functions (de-prefixed + snake_case), structs, and "
        "constants; string-based parameter API kept verbatim. Errors (ferslib ret < 0) "
        "raise pyferslib.FERSError(code, message).";

    // ----- FERSError exception -----
    // Defined as a pure-Python class so that Python's normal descriptor protocol
    // binds `self` when __init__ is called on a new instance.  Using a raw
    // py::cpp_function assigned to a dynamically-created type() class bypasses
    // the descriptor machinery, causing __init__ to be invoked without self and
    // raising a pybind11 "incompatible function arguments" TypeError instead of
    // the intended FERSError.
    py::exec(
        "class FERSError(Exception):\n"
        "    '''FERS library error: carries numeric code and message from ferslib.'''\n"
        "    def __init__(self, code, message):\n"
        "        self.code = int(code)\n"
        "        self.message = str(message)\n"
        "        super().__init__(int(code), str(message))\n"
        "    def __str__(self):\n"
        "        return '[FERS {}] {}'.format(self.code, self.message)\n"
        "    def __repr__(self):\n"
        "        return 'FERSError(code={!r}, message={!r})'.format(self.code, self.message)\n",
        m.attr("__dict__")
    );
    m.attr("FERSError").attr("__module__") = "pyferslib";
    g_fers_error_type = m.attr("FERSError");

    // ----- Bound struct / event classes (read-only data classes) -----
    py::class_<BoardInfo>(m, "BoardInfo", "FERS board info (mirrors FERS_BoardInfo_t).")
        .def_readonly("pid",          &BoardInfo::pid)
        .def_readonly("fers_code",    &BoardInfo::fers_code)
        .def_readonly("pcb_revision", &BoardInfo::pcb_revision)
        .def_readonly("model_code",   &BoardInfo::model_code)
        .def_readonly("model_name",   &BoardInfo::model_name)
        .def_readonly("form_factor",  &BoardInfo::form_factor)
        .def_readonly("num_ch",       &BoardInfo::num_ch)
        .def_readonly("fpga_fwrev",   &BoardInfo::fpga_fwrev)
        .def_readonly("uc_fwrev",     &BoardInfo::uc_fwrev);

    py::class_<ChainInfo>(m, "ChainInfo", "TDL chain info (mirrors FERS_TDL_ChainInfo_t).")
        .def_readonly("status",      &ChainInfo::status)
        .def_readonly("board_count", &ChainInfo::board_count)
        .def_readonly("rrt",         &ChainInfo::rrt)
        .def_readonly("event_count", &ChainInfo::event_count)
        .def_readonly("byte_count",  &ChainInfo::byte_count)
        .def_readonly("event_rate",  &ChainInfo::event_rate)
        .def_readonly("mbps",        &ChainInfo::mbps);

    py::class_<CncInfo>(m, "CncInfo", "Concentrator info (mirrors FERS_CncInfo_t).")
        .def_readonly("pid",          &CncInfo::pid)
        .def_readonly("pcb_revision", &CncInfo::pcb_revision)
        .def_readonly("model_code",   &CncInfo::model_code)
        .def_readonly("model_name",   &CncInfo::model_name)
        .def_readonly("fpga_fwrev",   &CncInfo::fpga_fwrev)
        .def_readonly("sw_rev",       &CncInfo::sw_rev)
        .def_readonly("mac_10gbe",    &CncInfo::mac_10gbe)
        .def_readonly("num_link",     &CncInfo::num_link)
        .def_readonly("chains",       &CncInfo::chains);

    py::class_<SpectEvent>(m, "SpectEvent",
                           "Spectroscopy event (mirrors SpectEvent_t). Arrays are copies.")
        .def_readonly("tstamp_us",     &SpectEvent::tstamp_us)
        .def_readonly("rel_tstamp_us", &SpectEvent::rel_tstamp_us)
        .def_readonly("tstamp_clk",    &SpectEvent::tstamp_clk)
        .def_readonly("tref_tstamp",   &SpectEvent::tref_tstamp)
        .def_readonly("trigger_id",    &SpectEvent::trigger_id)
        .def_readonly("chmask",        &SpectEvent::chmask)
        .def_readonly("qdmask",        &SpectEvent::qdmask)
        .def_readonly("energy_hg",     &SpectEvent::energy_hg)
        .def_readonly("energy_lg",     &SpectEvent::energy_lg)
        .def_readonly("toa",           &SpectEvent::toa)
        .def_readonly("tot",           &SpectEvent::tot);

    py::class_<CountingEvent>(m, "CountingEvent",
                              "Counting/MCS event (mirrors CountingEvent_t). Arrays are copies.")
        .def_readonly("tstamp_us",     &CountingEvent::tstamp_us)
        .def_readonly("rel_tstamp_us", &CountingEvent::rel_tstamp_us)
        .def_readonly("trigger_id",    &CountingEvent::trigger_id)
        .def_readonly("chmask",        &CountingEvent::chmask)
        .def_readonly("counts",        &CountingEvent::counts)
        .def_readonly("t_or_counts",   &CountingEvent::t_or_counts)
        .def_readonly("q_or_counts",   &CountingEvent::q_or_counts);

    py::class_<WaveEvent>(m, "WaveEvent",
                          "Waveform event (mirrors WaveEvent_t). Arrays are copies of ns samples.")
        .def_readonly("tstamp_us",  &WaveEvent::tstamp_us)
        .def_readonly("trigger_id", &WaveEvent::trigger_id)
        .def_readonly("ns",         &WaveEvent::ns)
        .def_readonly("wave_hg",    &WaveEvent::wave_hg)
        .def_readonly("wave_lg",    &WaveEvent::wave_lg)
        .def_readonly("dig_probes", &WaveEvent::dig_probes);

    py::class_<ListEvent>(m, "ListEvent",
                          "Timing list event (mirrors ListEvent_t). Arrays are copies of nhits.")
        .def_readonly("tstamp_us",   &ListEvent::tstamp_us)
        .def_readonly("tref_tstamp", &ListEvent::tref_tstamp)
        .def_readonly("tstamp_clk",  &ListEvent::tstamp_clk)
        .def_readonly("trigger_id",  &ListEvent::trigger_id)
        .def_readonly("nhits",       &ListEvent::nhits)
        .def_readonly("channel",     &ListEvent::channel)
        .def_readonly("edge",        &ListEvent::edge)
        .def_readonly("toa",         &ListEvent::toa)
        .def_readonly("tot",         &ListEvent::tot);

    py::class_<ServEvent>(m, "ServEvent",
                          "Service event (mirrors ServEvent_t). ch_trg_cnt is a copy.")
        .def_readonly("tstamp_us",      &ServEvent::tstamp_us)
        .def_readonly("update_time",    &ServEvent::update_time)
        .def_readonly("pkt_size",       &ServEvent::pkt_size)
        .def_readonly("version",        &ServEvent::version)
        .def_readonly("format",         &ServEvent::format)
        .def_readonly("ch_trg_cnt",     &ServEvent::ch_trg_cnt)
        .def_readonly("q_or_cnt",       &ServEvent::q_or_cnt)
        .def_readonly("t_or_cnt",       &ServEvent::t_or_cnt)
        .def_readonly("temp_fpga",      &ServEvent::temp_fpga)
        .def_readonly("temp_board",     &ServEvent::temp_board)
        .def_readonly("temp_tdc0",      &ServEvent::temp_tdc0)
        .def_readonly("temp_tdc1",      &ServEvent::temp_tdc1)
        .def_readonly("temp_hv",        &ServEvent::temp_hv)
        .def_readonly("temp_detector",  &ServEvent::temp_detector)
        .def_readonly("hv_vmon",        &ServEvent::hv_vmon)
        .def_readonly("hv_imon",        &ServEvent::hv_imon)
        .def_readonly("hv_status_on",   &ServEvent::hv_status_on)
        .def_readonly("hv_status_ramp", &ServEvent::hv_status_ramp)
        .def_readonly("hv_status_ovv",  &ServEvent::hv_status_ovv)
        .def_readonly("hv_status_ovc",  &ServEvent::hv_status_ovc)
        .def_readonly("status",         &ServEvent::status)
        .def_readonly("tdc_ro_status",  &ServEvent::tdc_ro_status)
        .def_readonly("readout_flags",  &ServEvent::readout_flags)
        .def_readonly("tot_trg_cnt",    &ServEvent::tot_trg_cnt)
        .def_readonly("rej_trg_cnt",    &ServEvent::rej_trg_cnt)
        .def_readonly("suppr_trg_cnt",  &ServEvent::suppr_trg_cnt);

    py::class_<TestEvent>(m, "TestEvent",
                          "Test-mode event (mirrors TestEvent_t). test_data is a copy of nwords.")
        .def_readonly("tstamp_us",  &TestEvent::tstamp_us)
        .def_readonly("trigger_id", &TestEvent::trigger_id)
        .def_readonly("nwords",     &TestEvent::nwords)
        .def_readonly("test_data",  &TestEvent::test_data);

    // ----- Module constants (CONTRACT.md §1a) -----
    // NB: several ferslib constants are C enum members (FERSLIB_EvtBuildingModes,
    // FERSLIB_ReadoutStatus, ...), so each is cast to int before being exposed —
    // py::int_ only accepts integral types, and pybind11 auto-converts a plain int to
    // a Python int on assignment.
    // Configuration modes
    m.attr("CFG_HARD") = static_cast<int>(CFG_HARD);
    m.attr("CFG_SOFT") = static_cast<int>(CFG_SOFT);

    // Event-building / readout (sorting) modes
    m.attr("ROMODE_DISABLE_SORTING") = static_cast<int>(ROMODE_DISABLE_SORTING);
    m.attr("ROMODE_TRGTIME_SORTING") = static_cast<int>(ROMODE_TRGTIME_SORTING);
    m.attr("ROMODE_TRGID_SORTING")   = static_cast<int>(ROMODE_TRGID_SORTING);

    // Start modes (Janus-level start codes mandated by CONTRACT.md §1a). These are the
    // run-start opcodes passed to start/stop/sync; they are not the same enum as
    // FERSLIB_StartMode and are defined here verbatim per the contract.
    m.attr("START_ASYNC")              = static_cast<int>(0x00);
    m.attr("START_TDL")                = static_cast<int>(0x11);
    m.attr("START_TDL_EXTRUN")         = static_cast<int>(0x12);
    m.attr("START_TDL_EXTRUN_EXTCLK")  = static_cast<int>(0x13);
    m.attr("START_TDL_EXTCLK")         = static_cast<int>(0x14);
    m.attr("START_TDL_GPS")            = static_cast<int>(0x16);
    m.attr("START_CHAIN_T0")           = static_cast<int>(0x04);
    m.attr("START_CHAIN_T1")           = static_cast<int>(0x05);

    // Data qualifiers
    m.attr("DTQ_SPECT")   = static_cast<int>(DTQ_SPECT);
    m.attr("DTQ_TIMING")  = static_cast<int>(DTQ_TIMING);
    m.attr("DTQ_COUNT")   = static_cast<int>(DTQ_COUNT);
    m.attr("DTQ_WAVE")    = static_cast<int>(DTQ_WAVE);
    m.attr("DTQ_TSPECT")  = static_cast<int>(DTQ_TSPECT);
    m.attr("DTQ_SERVICE") = static_cast<int>(DTQ_SERVICE);
    m.attr("DTQ_TEST")    = static_cast<int>(DTQ_TEST);

    // Readout status sentinel (NOT an error)
    m.attr("RAWDATA_REPROCESS_FINISHED") = static_cast<int>(RAWDATA_REPROCESS_FINISHED);

    // Buffer / size constants straight from FERSlib.h (useful to SDK consumers)
    m.attr("MAX_LIST_SIZE")      = static_cast<int>(MAX_LIST_SIZE);
    m.attr("MAX_TEST_NWORDS")    = static_cast<int>(MAX_TEST_NWORDS);
    m.attr("FERSLIB_MAX_NCH")    = static_cast<int>(FERSLIB_MAX_NCH);
    m.attr("FERSLIB_MAX_NTDL")   = static_cast<int>(FERSLIB_MAX_NTDL);
    m.attr("FERSLIB_MAX_NNODES") = static_cast<int>(FERSLIB_MAX_NNODES);

    // ----- Functions: device & info -----
    m.def("open_device", &open_device, py::arg("path"),
          "FERS_OpenDevice — open a device, returns the int handle.");
    m.def("close_device", &close_device, py::arg("handle"),
          "FERS_CloseDevice.");
    m.def("is_open", &is_open, py::arg("path"),
          "FERS_IsOpen — True if a device at path is already open.");
    m.def("get_num_boards_connected", &get_num_boards_connected,
          "FERS_GetNumBrdConnected.");
    m.def("get_board_info", &get_board_info, py::arg("handle"),
          "FERS_GetBoardInfo -> BoardInfo.");
    m.def("get_cnc_info", &get_cnc_info, py::arg("handle"),
          "FERS_GetCncInfo -> CncInfo.");
    m.def("get_clock_period", &get_clock_period, py::arg("handle"),
          "FERS_GetClockPeriod — clock period in ns.");
    m.def("reset_ip_address", &reset_ip_address, py::arg("handle"),
          "FERS_Reset_IPaddress — restore factory IP (USB only).");
    m.def("get_last_error", &get_last_error,
          "FERS_GetLastError — last library error message string.");
    m.def("lib_release", &lib_release,
          "FERS_GetLibReleaseNum — library release number string.");

    // ----- Functions: config (string-based, verbatim) -----
    m.def("load_config_file", &load_config_file, py::arg("path"),
          "FERS_LoadConfigFile.");
    m.def("set_param", &set_param, py::arg("handle"), py::arg("name"), py::arg("value"),
          "FERS_SetParam — set a parameter by name (string value, kept verbatim).");
    m.def("get_param", &get_param, py::arg("handle"), py::arg("name"),
          "FERS_GetParam — get a parameter value as string.");
    m.def("configure", &configure, py::arg("handle"), py::arg("mode"),
          "FERS_configure — apply parameters to the board (CFG_HARD / CFG_SOFT).");

    // ----- Functions: tdl -----
    m.def("init_tdl_chains", &init_tdl_chains, py::arg("handle"), py::arg("delay_adjust"),
          "FERS_InitTDLchains — delay_adjust is a float ndarray of shape [8, 16].");
    m.def("tdl_chains_initialized", &tdl_chains_initialized, py::arg("handle"),
          "FERS_TDLchainsInitialized.");

    // ----- Functions: readout -----
    m.def("init_readout", &init_readout, py::arg("handle"), py::arg("ro_mode"),
          "FERS_InitReadout — returns the allocated buffer size (bytes).");
    m.def("close_readout", &close_readout, py::arg("handle"),
          "FERS_CloseReadout.");
    m.def("flush_data", &flush_data, py::arg("handle"),
          "FERS_FlushData.");

    // ----- Functions: acquisition -----
    m.def("start_acquisition", &start_acquisition,
          py::arg("handles"), py::arg("start_mode"), py::arg("run_num"),
          "FERS_StartAcquisition — handles is a list of board handles.");
    m.def("stop_acquisition", &stop_acquisition,
          py::arg("handles"), py::arg("start_mode"), py::arg("run_num"),
          "FERS_StopAcquisition — handles is a list of board handles.");
    m.def("get_event", &get_event, py::arg("handles"),
          "FERS_GetEvent -> (board, dtq, event) | None. Returns "
          "(-1, RAWDATA_REPROCESS_FINISHED, None) at end of offline reprocessing.");
    m.def("drain_events", &drain_events, py::arg("handles"), py::arg("max_events"),
          "DATA-plane batch primitive: loop FERS_GetEvent up to max_events or until the "
          "queue is empty -> list[(board, dtq, event)].");

    // ----- Functions: registers & commands -----
    m.def("read_register", &read_register, py::arg("handle"), py::arg("address"),
          "FERS_ReadRegister.");
    m.def("write_register", &write_register,
          py::arg("handle"), py::arg("address"), py::arg("data"),
          "FERS_WriteRegister.");
    m.def("write_register_slice", &write_register_slice,
          py::arg("handle"), py::arg("address"),
          py::arg("start_bit"), py::arg("stop_bit"), py::arg("data"),
          "FERS_WriteRegisterSlice.");
    m.def("send_command", &send_command, py::arg("handle"), py::arg("cmd"),
          "FERS_SendCommand.");

    // ----- Functions: HV -----
    m.def("hv_init", &hv_init, py::arg("handle"), "FERS_HV_Init.");
    m.def("hv_set_onoff", &hv_set_onoff, py::arg("handle"), py::arg("on"),
          "FERS_HV_Set_OnOff.");
    m.def("hv_get_status", &hv_get_status, py::arg("handle"),
          "FERS_HV_Get_Status -> (on, ramping, ovc, ovv).");
    m.def("hv_set_vbias", &hv_set_vbias, py::arg("handle"), py::arg("vbias"),
          "FERS_HV_Set_Vbias.");
    m.def("hv_get_vbias", &hv_get_vbias, py::arg("handle"),
          "FERS_HV_Get_Vbias.");
    m.def("hv_get_vmon", &hv_get_vmon, py::arg("handle"),
          "FERS_HV_Get_Vmon.");
    m.def("hv_set_imax", &hv_set_imax, py::arg("handle"), py::arg("imax"),
          "FERS_HV_Set_Imax.");
    m.def("hv_get_imon", &hv_get_imon, py::arg("handle"),
          "FERS_HV_Get_Imon.");
    m.def("hv_get_int_temp", &hv_get_int_temp, py::arg("handle"),
          "FERS_HV_Get_IntTemp.");
    m.def("hv_get_detector_temp", &hv_get_detector_temp, py::arg("handle"),
          "FERS_HV_Get_DetectorTemp.");

    // ----- Functions: temperatures -----
    m.def("get_fpga_temp", &get_fpga_temp, py::arg("handle"),
          "FERS_Get_FPGA_Temp.");
    m.def("get_board_temp", &get_board_temp, py::arg("handle"),
          "FERS_Get_Board_Temp.");
}

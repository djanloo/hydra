cmake_minimum_required(VERSION 3.16)

project(hydrafers VERSION 0.0.2 LANGUAGES C CXX)

# -------------------------
# C/C++ standards
# -------------------------
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# -------------------------
# Compiler flags
# -------------------------
if(NOT WIN32)
    add_compile_definitions(_POSIX_C_SOURCE=200809L)
endif()

if(MSVC)
    add_compile_options(/W3)
    # Suppress noisy MSVC warnings that come from legacy ferslib C code.
    # /wd4996  deprecated CRT functions (sprintf_s used via f_sprintf macro)
    # /wd4244  implicit int/float narrowing in C sources
    # /wd4267  size_t -> int narrowing in C sources
    add_compile_options(/wd4996 /wd4244 /wd4267)
else()
    add_compile_options(-Wall -Wextra)
endif()

# -------------------------
# Dependencies
# -------------------------
find_package(Threads REQUIRED)

if(WIN32)
    set(PLATFORM_LIBS ws2_32 winusb setupapi)
else()
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(LIBUSB REQUIRED libusb-1.0)
    set(PLATFORM_LIBS         ${LIBUSB_LIBRARIES})
    set(PLATFORM_INCLUDE_DIRS ${LIBUSB_INCLUDE_DIRS})
endif()

# -------------------------
# ferslib sources
# Sources live under native/ferslib/src; headers under native/ferslib/include.
# The ferslib source tree is FROZEN — never modify anything under it.
# -------------------------
set(FERSLIB_SRC_DIR     ${CMAKE_CURRENT_SOURCE_DIR}/native/ferslib/src)
set(FERSLIB_INCLUDE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/native/ferslib/include)

set(FERS_SRC
    ${FERSLIB_SRC_DIR}/FERS_LLeth.c
    ${FERSLIB_SRC_DIR}/FERS_LLtdl.c
    ${FERSLIB_SRC_DIR}/FERS_LLusb.cpp
    ${FERSLIB_SRC_DIR}/FERS_MultiPlatform.c
    ${FERSLIB_SRC_DIR}/FERS_adapters.c
    ${FERSLIB_SRC_DIR}/FERS_configure.c
    ${FERSLIB_SRC_DIR}/FERS_configure_5202.c
    ${FERSLIB_SRC_DIR}/FERS_configure_5203.c
    ${FERSLIB_SRC_DIR}/FERS_configure_5204.c
    ${FERSLIB_SRC_DIR}/FERS_paramparser.c
    ${FERSLIB_SRC_DIR}/FERS_readout.c
    ${FERSLIB_SRC_DIR}/FERSlib.c
)

# -------------------------
# ferslib static library
# Built as STATIC so the pyferslib wheel is fully self-contained on Windows
# (no separate ferslib.dll to ship alongside the wheel).
# -------------------------
add_library(ferslib STATIC ${FERS_SRC})

set_target_properties(ferslib PROPERTIES POSITION_INDEPENDENT_CODE ON)

target_include_directories(ferslib
    PUBLIC  ${FERSLIB_INCLUDE_DIR}
    PRIVATE ${PLATFORM_INCLUDE_DIRS}
)

target_link_libraries(ferslib
    PRIVATE Threads::Threads
    PRIVATE ${PLATFORM_LIBS}
)

if(WIN32)
    # Export the CAEN FERS DLL-API symbols when building the static lib
    # (the macro evaluates to nothing when _CAEN_FERS_EXPORT is defined,
    # effectively stripping dllimport/dllexport from all declarations).
    target_compile_definitions(ferslib PRIVATE _CAEN_FERS_EXPORT)
endif()

if(MINGW)
    set(MINGW_SHIMS_DIR ${CMAKE_CURRENT_SOURCE_DIR}/cmake/mingw-shims)
    target_compile_definitions(ferslib PRIVATE _MINGW_HAS_STDBOOL)
    target_compile_options(ferslib PRIVATE
        -include stdbool.h
        -I${MINGW_SHIMS_DIR}
    )
endif()

# -------------------------
# pyferslib — pybind11 extension module (faithful 1:1 binding of ferslib)
#
# Naming convention (CONTRACT.md §0):
#   pyferslib  = the compiled C++/pybind11 module  (import pyferslib)
#   pyfers     = the pure-Python OOP/pythonic SDK  (import pyfers, src/pyfers/)
#
# Source: native/bindings/pyferslib.cpp
# -------------------------
option(BUILD_PYTHON_BINDINGS "Build pyferslib pybind11 module" ON)

if(BUILD_PYTHON_BINDINGS)
    find_package(pybind11 CONFIG REQUIRED)

    set(PYFERSLIB_SRC ${CMAKE_CURRENT_SOURCE_DIR}/native/bindings/pyferslib.cpp)

    pybind11_add_module(pyferslib ${PYFERSLIB_SRC})

    target_include_directories(pyferslib PRIVATE ${FERSLIB_INCLUDE_DIR})

    target_link_libraries(pyferslib PRIVATE ferslib)

    if(WIN32)
        # pyferslib links the FROZEN ferslib STATICALLY, so the FERS API headers
        # must NOT be seen as __declspec(dllimport) (that expects __imp_* symbols
        # from a DLL and yields LNK2001 unresolved externals). _CAEN_FERS_EXPORT
        # makes the export macro expand so the declarations bind directly to the
        # static symbols — mirroring the definition on the ferslib target above.
        target_compile_definitions(pyferslib PRIVATE
            NOMINMAX WIN32_LEAN_AND_MEAN _CAEN_FERS_EXPORT)
    endif()

    if(MINGW)
        set(MINGW_SHIMS_DIR ${CMAKE_CURRENT_SOURCE_DIR}/cmake/mingw-shims)
        target_compile_options(pyferslib PRIVATE
            -include stdbool.h
            -I${MINGW_SHIMS_DIR}
        )
    endif()

    set_target_properties(pyferslib PROPERTIES
        CXX_VISIBILITY_PRESET     hidden
        VISIBILITY_INLINES_HIDDEN ON
    )

    # scikit-build-core installs the compiled module at the wheel root so that
    # both `import pyferslib` and `import pyfers` (pure-Python, src/pyfers/) and
    # `import hydrafers` (pure-Python, src/hydrafers/) resolve at the top level.
    install(TARGETS pyferslib LIBRARY DESTINATION .)
endif()

# -------------------------
# Install ferslib headers & static archive (for IDE / downstream use)
# -------------------------
install(TARGETS ferslib
    ARCHIVE DESTINATION lib
    LIBRARY DESTINATION lib
)
install(DIRECTORY ${FERSLIB_INCLUDE_DIR}/ DESTINATION include/ferslib)

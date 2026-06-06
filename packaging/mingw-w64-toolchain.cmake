# CMake toolchain for cross-compiling to 64-bit Windows with mingw-w64 on Linux.
# This is BUILD CONFIGURATION ONLY — it does not touch any project source.
#
# Usage (see packaging/cross_build_windows.sh for the full recipe):
#   cmake -S . -B build-win -G Ninja \
#       -DCMAKE_TOOLCHAIN_FILE=packaging/mingw-w64-toolchain.cmake ...
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)

set(TOOLCHAIN_PREFIX x86_64-w64-mingw32)
set(CMAKE_C_COMPILER   ${TOOLCHAIN_PREFIX}-gcc)
set(CMAKE_CXX_COMPILER ${TOOLCHAIN_PREFIX}-g++)
set(CMAKE_RC_COMPILER  ${TOOLCHAIN_PREFIX}-windres)

set(CMAKE_FIND_ROOT_PATH /usr/${TOOLCHAIN_PREFIX})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE BOTH)

# Produce a self-contained .pyd: statically link the GCC/C++ runtimes so the
# result doesn't need libgcc/libstdc++ DLLs alongside it on the target.
set(CMAKE_CXX_STANDARD_LIBRARIES "-static-libgcc -static-libstdc++ -static -lpthread")

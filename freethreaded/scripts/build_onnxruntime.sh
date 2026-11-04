#!/usr/bin/env bash
# Build onnxruntime 1.31.1 (CPU) for free-threaded CPython 3.15t. PyPI has cp313t/cp314t wheels
# but no cp315t yet; pymupdf.layout needs onnxruntime.
#
# usage: scripts/build_onnxruntime.sh /path/to/python3.15t [WORKDIR] [JOBS]
# result: WORKDIR/build/Release/dist/onnxruntime-1.31.1-cp315-cp315t-linux_x86_64.whl
#
# About 55 minutes on 6 cores. Built on Debian trixie (glibc 2.41, GCC 14.2): the wheel is tagged
# linux_x86_64 and needs glibc >= 2.38 and GCC 13+ libstdc++ at runtime.
# The only source change is the 3.15 packaging subset of upstream PR #33359 (microsoft/onnxruntime);
# the build detects the free-threaded interpreter by itself and the module keeps the GIL off.
set -euo pipefail

PY=${1:?usage: build_onnxruntime.sh /path/to/python3.15t [WORKDIR] [JOBS]}
KIT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mkdir -p "${2:-$PWD/work-ort}" && cd "${2:-$PWD/work-ort}" && pwd)
JOBS=${3:-6}
ORT_TAG=v1.31.1
ORT_COMMIT=6af1a932e2286d5c58166085d24c68783033edee

"$PY" -c 'import sysconfig; assert sysconfig.get_config_var("Py_GIL_DISABLED"), "need python3.15t"'
cd "$WORK"
if [ ! -d src ]; then
    git clone -q --depth 1 --branch "$ORT_TAG" --recursive --shallow-submodules \
        https://github.com/microsoft/onnxruntime.git src
fi
test "$(git -C src rev-parse HEAD)" = "$ORT_COMMIT"

# Python 3.15 packaging (subset of upstream PR #33359): patches/onnxruntime-0001. Skipped if already applied.
if git -C src apply --check "$KIT/patches/onnxruntime-0001-python-3.15-packaging.patch" 2>/dev/null; then
    git -C src apply "$KIT/patches/onnxruntime-0001-python-3.15-packaging.patch"
fi

"$PY" -m venv --clear venv-build
venv-build/bin/python -m pip install -q --upgrade pip
venv-build/bin/python -m pip install -q cmake ninja numpy packaging protobuf flatbuffers wheel setuptools sympy

PATH="$WORK/venv-build/bin:$PATH" venv-build/bin/python src/tools/ci_build/build.py \
    --build_dir "$WORK/build" --config Release \
    --update --build --build_wheel \
    --parallel "$JOBS" \
    --skip_tests --skip_submodule_sync --skip_pip_install \
    --compile_no_warning_as_error \
    --cmake_generator Ninja \
    --cmake_extra_defines onnxruntime_BUILD_UNIT_TESTS=OFF
ls -l "$WORK"/build/Release/dist/onnxruntime-*-cp315-cp315t-*.whl

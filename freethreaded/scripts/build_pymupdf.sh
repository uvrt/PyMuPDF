#!/usr/bin/env bash
# Build the full PyMuPDF wheel (core + layout + pymupdf4llm + _features + _tgif) for free-threaded
# CPython 3.15t from this checkout, plus pinned, checksummed MuPDF, pymupdf_layout and pymupdf4llm
# sources with the patches in ../patches.
#
# usage: freethreaded/scripts/build_pymupdf.sh /path/to/python3.15t [WORKDIR]
#   PYMUPDF_FT_ATOMIC_REFCOUNTS=1 also applies patches/mupdf-0002-atomic-refcounts.patch.
# result: WORKDIR/dist/pymupdf-2.1+ft315t.<commit>-cp315-cp315t-linux_x86_64.whl
#
# Needs: git, curl, patch, a C/C++ toolchain (gcc/g++ 13+, make), python3.15t with venv.
# A clean build takes about 10 minutes (most of it MuPDF); swig comes from the build-isolation
# environment that PyMuPDF's pipcl creates.
set -euo pipefail

PY=${1:?usage: build_pymupdf.sh /path/to/python3.15t [WORKDIR]}
FT=$(cd "$(dirname "$0")/.." && pwd)
REPO=$(cd "$FT/.." && pwd)
WORK=$(mkdir -p "${2:-$PWD/work}" && cd "${2:-$PWD/work}" && pwd)

# --- Pinned sources -------------------------------------------------------------------------
MUPDF_VERSION=1.28.6
MUPDF_URL=https://mupdf.com/downloads/archive/mupdf-1.28.6-source.tar.gz
MUPDF_SHA256=dc85000640a45d90ca9b77b061f6ca67cce0c4d4fbecf8819647baf573eef101
LAYOUT_REPO=https://github.com/ArtifexSoftware/pymupdf_layout.git
LAYOUT_COMMIT=df5af7f65ae5d9a3561c4c35d8836c15f89ace12   # tag 2.1; the git_sha in the official wheel's pymupdf/layout/_build.py
LLM_REPO=https://github.com/pymupdf/pymupdf4llm.git
LLM_COMMIT=030a6b0ac449266a67b79675272fb877a34a87ab     # the git_sha in the official wheel's pymupdf4llm/_build.py

"$PY" -c 'import sys, sysconfig; assert sysconfig.get_config_var("Py_GIL_DISABLED"), "need a free-threaded (3.15t) interpreter"; assert sys.version_info[:2] == (3, 15), sys.version'

sha256() { if command -v sha256sum >/dev/null; then sha256sum -c -; else shasum -a 256 -c -; fi; }
fetch() {  # url sha256 file
    if [ ! -f "$3" ]; then curl -fsSL --retry 5 --retry-delay 15 --retry-all-errors -o "$3.part" "$1" && mv "$3.part" "$3"; fi
    echo "$2  $3" | sha256
}
checkout() {  # repo commit dir patch
    if [ ! -d "$3/.git" ]; then
        git init -q "$3"
        git -C "$3" remote add origin "$1"
    fi
    git -C "$3" fetch -q --depth 1 origin "$2"
    git -C "$3" checkout -q --force "$2"
    git -C "$3" clean -qfdx
    git -C "$3" apply "$4"
}

cd "$WORK"
fetch "$MUPDF_URL" "$MUPDF_SHA256" "mupdf-$MUPDF_VERSION-source.tar.gz"

# MuPDF + free-threading patch: optional independent context per thread (MUPDF_indep_ctx=1),
# warning/error callbacks on every thread's context.
rm -rf "mupdf-$MUPDF_VERSION-source"
tar xzf "mupdf-$MUPDF_VERSION-source.tar.gz"
patch -d "mupdf-$MUPDF_VERSION-source" -p1 < "$FT/patches/mupdf-0001-free-threading.patch"
if [ "${PYMUPDF_FT_ATOMIC_REFCOUNTS:-0}" = 1 ]; then
    patch -d "mupdf-$MUPDF_VERSION-source" -p1 < "$FT/patches/mupdf-0002-atomic-refcounts.patch"
fi

# pymupdf_layout + pymupdf4llm, patched for free threading: a layout model per thread, thread-safe
# shared state, onnxruntime thread pools sized for parallel threads.
checkout "$LAYOUT_REPO" "$LAYOUT_COMMIT" pymupdf_layout "$FT/patches/layout-0001-free-threading.patch"
checkout "$LLM_REPO" "$LLM_COMMIT" pymupdf4llm "$FT/patches/pymupdf4llm-0001-free-threading.patch"

# Build from a clean copy of the checkout so build products don't land in the repo.
rm -rf pymupdf-src
git -C "$REPO" archive --format=tar --prefix=pymupdf-src/ HEAD | tar xf -
if ! git -C "$REPO" diff --quiet HEAD -- src setup.py; then
    echo "warning: uncommitted changes in src/ or setup.py are not in the build" >&2
fi

"$PY" -m venv --clear venv-build
venv-build/bin/python -m pip install -q --upgrade pip

export PYMUPDF_SETUP_FAKE_NOGIL=1            # swig -nogil: every extension declares Py_MOD_GIL_NOT_USED
export PYMUPDF_SETUP_SWIG_PIP=${PYMUPDF_SETUP_SWIG_PIP:-swig==4.5.1}   # setup.py otherwise takes the latest swig
export PYMUPDF_SETUP_PY_LIMITED_API=0        # the limited API and free threading don't mix (PEP 803)
export PYMUPDF_SETUP_REQUIRE_LAYOUT_4LLM=0   # don't depend on the empty pymupdf_layout/pymupdf4llm packages
export PYMUPDF_SETUP_MUPDF_BUILD="$WORK/mupdf-$MUPDF_VERSION-source"
export PYMUPDF_SETUP_PATH_LAYOUT="$WORK/pymupdf_layout"   # builds _features and _tgif, embeds pymupdf.layout
export PYMUPDF_SETUP_PATH_4LLM="$WORK/pymupdf4llm"       # embeds pymupdf4llm
# Package version 2.1+ft315t.<commit>: never mistaken for upstream 2.1 (pymupdf.__version__ stays 2.1).
export PYMUPDF_SETUP_VERSION_LOCAL=${PYMUPDF_SETUP_VERSION_LOCAL:-ft315t.$(git -C "$REPO" rev-parse --short=7 HEAD)}
mkdir -p dist
venv-build/bin/python -m pip wheel --no-deps ./pymupdf-src -w dist
ls -l dist/pymupdf-*-cp315-cp315t-*.whl

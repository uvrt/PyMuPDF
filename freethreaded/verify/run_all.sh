#!/usr/bin/env bash
# Verify a 3.15t PyMuPDF build against the official PyMuPDF wheel on regular 3.15.
#
# usage: verify/run_all.sh OFFICIAL_PY OURS_PY [WORKDIR [DOCSDIR]]
#   OFFICIAL_PY  python 3.14 or 3.15 (GIL build) with the official PyMuPDF 2.1 wheel (+ onnxruntime)
#   OURS_PY      python 3.15t with our wheel installed (+ onnxruntime cp315t, numpy, pyyaml,
#                networkx, psutil, tabulate)
#
# Steps, all on generated PDFs (no real documents):
#   1. corpus: 80 development PDFs and 60 held-out PDFs (seeded, reproducible)
#   2. record every _features call and the reference markdown with the official build
#   3. features bit-exact on all fields, development and held-out
#   4. features thread stress at 1/4/8 threads, MUPDF_indep_ctx 0 and 1
#   5. rendering (RGB/GRAY/CMYK) + text extraction thread stress at 1/4/8 threads, MUPDF_indep_ctx 0 and 1
#   (No OCR: keep Tesseract off the machine. If PyMuPDF finds it, pymupdf4llm OCRs pages and
#    the recorded reference no longer matches the replay.)
#   6. to_markdown byte-identical, one layout model per thread (built in), 1/4/8 threads x 3 rounds,
#      plus once with PYMUPDF_LAYOUT_PER_THREAD=0 (shared model behind the lock)
#   7. with DOCSDIR (real-world PDFs, see fetch_docs.py): steps 5 and 6 on the first pages of each
# Every script runs from WORKDIR with absolute script paths, so nothing shadows a module.
set -euo pipefail
OFF=${1:?OFFICIAL_PY}; OURS=${2:?OURS_PY}
V=$(cd "$(dirname "$0")" && pwd)
W=$(mkdir -p "${3:-$PWD/verify-work}" && cd "${3:-$PWD/verify-work}" && pwd)
cd "$W"
export PYTHONPATH="$V"   # for verify/common.py

"$OURS" -c 'import sys, pymupdf, pymupdf.layout, pymupdf4llm, pymupdf.features; assert not sys._is_gil_enabled(), "GIL turned on"; print("ours: GIL off,", pymupdf.__version__)'

"$OFF" -I "$V/gen_corpus.py" corpus/dev 0 80
"$OFF" -I "$V/gen_corpus.py" corpus/heldout 1000 1060

"$OFF" "$V/record.py" corpus/dev rec_dev.pkl
"$OFF" "$V/record.py" corpus/heldout rec_held.pkl --md md_ref

"$OURS" "$V/compare_features.py" rec_dev.pkl corpus/dev
"$OURS" "$V/compare_features.py" rec_held.pkl corpus/heldout

for indep in 0 1; do
    MUPDF_indep_ctx=$indep "$OURS" "$V/stress_features.py" rec_dev.pkl corpus/dev 8 3
done

for indep in 0 1; do
    MUPDF_indep_ctx=$indep "$OURS" "$V/stress_render.py" corpus/dev 1,4,8 3
done

for indep in 0 1; do
    MUPDF_indep_ctx=$indep "$OURS" "$V/md_check.py" corpus/heldout md_ref 1,4,8 3 perthread
done
"$OURS" "$V/md_check.py" corpus/heldout md_ref 4 1 shipped

if [ -n "${4:-}" ]; then
    D=$(cd "$4" && pwd)
    MAX_PAGES=12 "$OFF" "$V/record.py" "$D" rec_docs.pkl --md md_ref_docs
    for indep in 0 1; do
        MAX_PAGES=6 MUPDF_indep_ctx=$indep "$OURS" "$V/stress_render.py" "$D" 1,4 1
    done
    MAX_PAGES=12 "$OURS" "$V/md_check.py" "$D" md_ref_docs 1,4 2 perthread
fi
echo "ALL CHECKS PASSED"

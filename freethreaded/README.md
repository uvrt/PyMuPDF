# PyMuPDF 2.1 for free-threaded Python 3.15t

This branch (`python-3.15t`, based on tag `2.1`) builds the **full** PyMuPDF 2.1 (core,
`pymupdf.layout` with its compiled `_features` and `_tgif`, and `pymupdf4llm`) as one wheel for
**CPython 3.15t**. Every extension module declares that it runs without the GIL, and threads run
in parallel. It also builds the onnxruntime wheel that the layout model needs.

Upstream ships the full PyMuPDF only as `cp311-abi3`, which a free-threaded interpreter cannot
load. Their free-threaded build, `pymupdf-lite`, is core-only and turns the GIL back on at import
(see [PyMuPDF #5170](https://github.com/pymupdf/PyMuPDF/issues/5170)). PyPI has onnxruntime for
cp313t and cp314t, but not for cp315 or cp315t.

Linux x86_64 only. Started from the uvrt 3.15t build kit (4 November 2026).

## What this branch changes

### In this repository

| File | Change | Why |
|---|---|---|
| `src/__init__.py` | Skip `mupdf.reinit_singlethreaded()` when `Py_GIL_DISABLED` (module flag `_free_threaded`). | Otherwise every thread shares one `fz_context` and one error stack. With the GIL off, 4–8 threads crashed every run. MuPDF's C++ binding already gives each thread its own context. |
| `src/__init__.py` | On free-threaded builds, `Colorspace(CS_RGB/GRAY/CMYK)`, so also `csRGB`, `csGRAY` and `csCMYK`, resolves `.this` to the calling thread's device colorspace. | Device colorspaces belong to a context (`fz_device_rgb(ctx)` returns `ctx->colorspace->rgb`), and keeping or dropping one takes that context's allocation lock. With `MUPDF_indep_ctx=1`, worker contexts are made by `fz_new_context(NULL, NULL, …)`, with no-op locks, so threads changed the main context's colorspace refcounts with no lock at all. That race is the likely cause of the rare rendering crash the kit saw with `MUPDF_indep_ctx=1`. GIL builds keep the old behaviour. |
| `src/__init__.py` | New `_get_layout_per_thread` flag. | Set by `pymupdf.layout`, read by pymupdf4llm (below). |
| `setup.py` | Don't add `pymupdf-layout==2.1` to the requirements when layout is embedded. | It pulled in the empty placeholder package. |
| `.github/workflows/freethreaded_315t.yml` | Builds both wheels and runs `freethreaded/verify` on every push to this branch. | |

### Patches applied at build time (`freethreaded/patches/`)

| Patch | Applies to | Why |
|---|---|---|
| `mupdf-0001-optional-independent-context-per-thread` | MuPDF 1.28.6 `scripts/wrap/cpp.py` | Optional. With `MUPDF_indep_ctx=1`, each thread gets a fully independent `fz_context` instead of a clone. Clones share one allocation lock, taken on every allocation and every font/object refcount change; with 8 threads, half the time went to waiting on it. This file generates C++ wrapper code, so check the hunk on every MuPDF upgrade. |
| `layout-0001-per-thread-model-without-gil` | pymupdf_layout 2.1 `layout/__init__.py` | On free-threaded builds, `activate()` gives each thread its own layout model, created on first use. The main thread reuses the model made at import. Opt out with `PYMUPDF_LAYOUT_PER_THREAD=0`. Sets `pymupdf._get_layout_per_thread`. |
| `pymupdf4llm-0001-skip-layout-lock-with-per-thread-models` | pymupdf4llm `helpers/document_layout.py` | `get_layout_locked` skips `_LAYOUT_LOCK` when `pymupdf._get_layout_per_thread` is set. Without this, threads take turns on layout inference. |
| `onnxruntime-0001-python-3.15-packaging` | onnxruntime 1.31.1 | The 3.15 subset of upstream PR #33359: a classifier, and a numpy pin for unit-test builds (inert here). |

The two layout patches replace the kit's `examples/per_thread_layout.py`, which monkeypatched the
private names `pymupdf._get_layout` and `document_layout._LAYOUT_LOCK`. Parallel `to_markdown` now
needs no setup (`examples/parallel_markdown.py`).

The layout C code (`features.c`, `features.i`, tgif) needed no changes.

## Pinned sources

| Component | Source | Pin |
|---|---|---|
| PyMuPDF | this branch (tag `2.1`, identical to the PyPI sdist apart from `PKG-INFO`) | |
| MuPDF | `https://mupdf.com/downloads/archive/mupdf-1.28.6-source.tar.gz` | sha256 `dc85000640a45d90ca9b77b061f6ca67cce0c4d4fbecf8819647baf573eef101` |
| layout, `_features`, tgif | [ArtifexSoftware/pymupdf_layout](https://github.com/ArtifexSoftware/pymupdf_layout), tag `2.1` | `df5af7f65ae5d9a3561c4c35d8836c15f89ace12` |
| pymupdf4llm | [pymupdf/pymupdf4llm](https://github.com/pymupdf/pymupdf4llm) | `030a6b0ac449266a67b79675272fb877a34a87ab` |
| onnxruntime | [microsoft/onnxruntime](https://github.com/microsoft/onnxruntime), tag `v1.31.1` | `6af1a932e2286d5c58166085d24c68783033edee` |
| CPython (CI) | python-build-standalone `cpython-3.15.2+20261026` freethreaded | sha256 `8da46423…f06d98181` |

The layout and pymupdf4llm commits are the `git_sha` values recorded in the official 2.1 wheel's
`_build.py` files.

## Build

Requirements: Linux x86_64, git, curl, patch, gcc/g++ 13+, make, and a CPython 3.15t with `venv`.

```bash
freethreaded/scripts/build_pymupdf.sh /path/to/python3.15t work-pymupdf
#   -> work-pymupdf/dist/pymupdf-2.1-cp315-cp315t-linux_x86_64.whl  (about 10 minutes)
freethreaded/scripts/build_onnxruntime.sh /path/to/python3.15t work-ort 6
#   -> work-ort/build/Release/dist/onnxruntime-1.31.1-cp315-cp315t-linux_x86_64.whl  (about 55 minutes on 6 cores)
```

`build_pymupdf.sh` builds from `git archive HEAD`, so commit your changes first. It sets
`PYMUPDF_SETUP_FAKE_NOGIL=1` (swig `-nogil`, so the modules declare `Py_MOD_GIL_NOT_USED`),
`PYMUPDF_SETUP_PY_LIMITED_API=0` and `PYMUPDF_SETUP_REQUIRE_LAYOUT_4LLM=0`, and points
`PYMUPDF_SETUP_MUPDF_BUILD`, `PYMUPDF_SETUP_PATH_LAYOUT` and `PYMUPDF_SETUP_PATH_4LLM` at the
patched MuPDF tree and the two patched checkouts.

Install into a 3.15t environment:

```bash
pip install --find-links work-ort/build/Release/dist work-pymupdf/dist/pymupdf-2.1-cp315-cp315t-linux_x86_64.whl
python -c "import sys, pymupdf, pymupdf.layout, pymupdf4llm; print(sys._is_gil_enabled(), pymupdf._get_layout_per_thread)"   # False True
```

The CI workflow uploads both wheels as artifacts (`pymupdf-cp315t`, `onnxruntime-cp315t`).

## Performance knobs

| Setting | Default on 3.15t | Effect |
|---|---|---|
| One layout model per thread | on | `to_markdown` runs in parallel threads. About 20 MB per thread. `PYMUPDF_LAYOUT_PER_THREAD=0` turns it off. |
| `MUPDF_indep_ctx=1` | off | No shared MuPDF allocation lock between threads. Needed for rendering and plain text extraction to scale. Objects made on one thread must stay on it. |
| onnxruntime threads | onnxruntime default | With many worker threads, cap each session at 1 intra-op thread (as `verify/bench_md.py` does), or the thread pools oversubscribe the CPU. |

Two-thirds of `to_markdown` time is ONNX inference, so MuPDF-level speedups barely move it. Kit
measurements (12-core laptop, 2 performance cores; `verify/bench_md.py`): 8 threads gave 0.55
docs/s at 2.3 GB, against 0.61 docs/s at 2.9 GB for 8 processes on the official wheel.

## Verify

```bash
freethreaded/verify/run_all.sh /path/to/python-with-official-pymupdf-2.1 /path/to/python3.15t-with-ours verify-work
```

It generates 80 development and 60 held-out PDFs (seeded; text from small word lists), records
every `_features` call and the reference markdown with the official wheel, then checks ours:

1. `_features` bit-exact on all 112 fields;
2. `_features` thread stress at 8 threads × 3 rounds, `MUPDF_indep_ctx` 0 and 1;
3. rendering in RGB/GRAY/CMYK plus text extraction at 1/4/8 threads, a new thread pool per round,
   `MUPDF_indep_ctx` 0 and 1, hashes equal to the sequential run; prints the speedup;
4. `to_markdown` byte-identical with the built-in per-thread models at 1/4/8 threads × 3 rounds,
   `MUPDF_indep_ctx` 0 and 1, and once with `PYMUPDF_LAYOUT_PER_THREAD=0`.

It prints `ALL CHECKS PASSED` at the end. CI uses the official wheel on Python 3.14 as the
reference, because PyPI has no onnxruntime for 3.15. `results/` holds the kit's original logs.

## Thread-safety rules

- A Document and its TextPages stay with one thread. Each `fz_features_for_region` call modifies
  the text page and keeps/drops references on the page and its fonts. pymupdf4llm already works
  this way.
- `_features` and tgif have no mutable global state: tgif's only global is read-only model
  weights, its tensors are allocated per call, and everything uses the calling thread's context.
- With `MUPDF_indep_ctx=1`, never pass a MuPDF object made on one thread to another. Threads
  don't share a store or locks. `csRGB`, `csGRAY` and `csCMYK` are safe on this branch.
- Upstream says PyMuPDF does not support multithreaded use (FAQ). This build is ours to support.

## Keeping it current

On each new PyMuPDF / MuPDF / layout / pymupdf4llm / onnxruntime release:

1. Rebase this branch on the new PyMuPDF tag. The `src/__init__.py` and `setup.py` changes are
   small.
2. Update the pins in `scripts/build_pymupdf.sh`, `scripts/build_onnxruntime.sh` and the
   workflow (read the layout and pymupdf4llm commits from the new official wheel's `_build.py`).
3. Re-apply the patches. The MuPDF patch edits a code generator, so re-check its hunk. Drop the
   onnxruntime patch once onnxruntime supports 3.15 upstream, and drop the onnxruntime build once
   PyPI has cp315t wheels.
4. Check that `reinit_singlethreaded()`, `activate()` in `pymupdf.layout` and
   `get_layout_locked` in pymupdf4llm still exist and behave the same.
5. Push; the workflow must end with `ALL CHECKS PASSED`.

## Known gaps

- Tested on generated PDFs only. Run the markdown comparison on real documents before production.
- Linux x86_64 only.

## License

PyMuPDF, MuPDF, pymupdf_layout and pymupdf4llm are AGPL-3.0 (or Artifex commercial licences).
Anyone distributing wheels built from this branch must offer the corresponding source: this
branch plus the pinned sources. onnxruntime is MIT.

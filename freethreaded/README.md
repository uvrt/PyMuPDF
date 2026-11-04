# PyMuPDF 2.1 for free-threaded Python 3.15t

This branch (`python-3.15t`, based on tag `2.1`) builds the **full** PyMuPDF 2.1 (core,
`pymupdf.layout` with its compiled `_features` and `_tgif`, and `pymupdf4llm`) as one wheel for
**CPython 3.15t**. Every extension module declares that it runs without the GIL, threads run in
parallel, and shared state is made thread-safe. It also builds the onnxruntime wheel that the
layout model needs.

Upstream ships the full PyMuPDF only as `cp311-abi3`, which a free-threaded interpreter cannot
load. Their free-threaded build, `pymupdf-lite`, is core-only and turns the GIL back on at import
(see [PyMuPDF #5170](https://github.com/pymupdf/PyMuPDF/issues/5170)). PyPI has onnxruntime for
cp313t and cp314t, but not for cp315 or cp315t, so CI rebuilds it.

Linux x86_64 only. Started from the uvrt 3.15t build kit (4 November 2026).

## What this branch changes

### Parallelism: where threads were serialised

| Where | Before | Now |
|---|---|---|
| MuPDF allocator (`memory.c`) | Every `fz_malloc`/`fz_realloc`/`fz_free` held `FZ_LOCK_ALLOC`, which all threads' contexts share, **around the system malloc call itself**. | The default allocator is called without the lock; the lock is only taken to scavenge the store when an allocation fails. Custom allocators are still locked. |
| Layout model | One model behind pymupdf4llm's `_LAYOUT_LOCK`. | One model per thread on free-threaded builds (opt out: `PYMUPDF_LAYOUT_PER_THREAD=0`). The lock is skipped, including for the first wave of threads. |
| onnxruntime sessions | Each model's 3 sessions got a spinning thread pool the size of the machine, so N worker threads ran N × cores ONNX threads. | Models made on worker threads use `PYMUPDF_LAYOUT_ORT_THREADS` (default 1) threads per session, no spinning. A main-thread model keeps onnxruntime's defaults for single-threaded use. `PYMUPDF_LAYOUT_ORT_THREADS=0` restores the defaults everywhere. |
| MuPDF glyph cache (`draw-glyph.c`) | On a cache miss, FreeType rasterised the glyph while holding `FZ_LOCK_GLYPHCACHE`, blocking every other thread's cache lookups. | Rendered outside the lock, as MuPDF already does for Type 3 glyphs; a glyph rendered twice meanwhile is inserted once. |
| MuPDF context | `reinit_singlethreaded()`: one context for all threads. | Each thread keeps its own cloned context. |

Still shared in clone mode: refcount changes (`fz_keep_*` / `fz_drop_*`, twice per extracted
character, and every `pdf_obj` keep/drop) under `FZ_LOCK_ALLOC`, and `FZ_LOCK_FREETYPE`, one lock
for all FreeType faces. The optional `patches/mupdf-0002-atomic-refcounts.patch`
(`PYMUPDF_FT_ATOMIC_REFCOUNTS=1` for `build_pymupdf.sh`) makes the `fz_keep_imp*`/`fz_drop_imp*`
counts atomic (compare-and-swap; counts ≤ 0 still mark static objects). Those counts are written
only through these functions; storable objects, whose counts `store.c` changes together with the
store, keep the lock. CI builds, verifies and profiles both variants (`base` and `atomic`).

### Thread-safety fixes

| Where | Race | Fix |
|---|---|---|
| `table.py` `find_tables()`, `Table.header` | Changed the process-wide small-glyph-heights and quad-correction settings and restored them afterwards: other threads' text extraction used the wrong settings, and overlapping calls could leave a setting changed for good. | Per-thread overrides in Python and in `extra.i` (C `thread_local`); the process-wide values are untouched. |
| `JM_image_reporter()` (`get_image_info`, called by the layout model on every page) | Collected results in module globals: concurrent calls lost or mixed up images. | Thread-local. |
| `csRGB`, `csGRAY`, `csCMYK` | Made on the importing thread's context and refcounted from all threads. With `MUPDF_indep_ctx=1` that context's locks are no-ops. | Resolved to the calling thread's device colorspace on free-threaded builds. |
| MuPDF warning/error callbacks | Installed on the importing thread's context only: other threads printed to stderr, ignored `TOOLS.mupdf_display_*`, never filled `TOOLS.mupdf_warnings()`, and `page.rect` could raise IndexError on pages with an invalid mediabox. | Installed on the base context that new threads' contexts are copied from, and copied into independent contexts. A no-op callback is installed before a thread's context is dropped, so flushing warnings never calls Python from a finished thread. |
| `Document()` | Hid errors by setting a global and restoring it, so concurrent opens could leave errors hidden for good. | Hidden per thread. |
| `page.rect`, `convert_to_pdf` | Read the last or new warnings from the store shared by all threads. | Per-thread warning list. |
| `_optional_import()` | Restored only the Python copy of the quad-correction setting after the lazy pymupdf4llm import (also a single-threaded bug); concurrent first imports raced. | Restores both copies; first import under a lock. |
| `TOOLS.gen_id()` | Unlocked `+= 1`. | Locked. |
| MuPDF font caches (`font.c`) | Glyph bbox and encoding cache rows were published before they were filled: another thread using the same font could read uninitialised memory as a glyph bbox or glyph id. | Filled, then published with compare-and-swap. |
| pymupdf4llm OCR decision model | Lazily created session; another thread could use it before its input name was set and fail. | Locked; published complete. |
| pymupdf4llm `INFO_MESSAGES` | One StringIO for all documents: messages mixed, and earlier documents' messages leaked into later output (also single-threaded). | One buffer per thread, cleared after each document. |
| pymupdf4llm RapidOCR engine, CJK OCR font | Shared by all threads, created lazily without a lock. | One per thread. |
| pymupdf_layout `GlobalConfig` | Singleton published before its config was loaded. | Loaded, then published, under a lock. |

### Files

| File | Change |
|---|---|
| `src/__init__.py`, `src/table.py`, `src/extra.i` | The changes above; `_free_threaded` and `_get_layout_per_thread` flags. |
| `setup.py` | Don't add `pymupdf-layout==2.1` to the requirements when layout is embedded (it pulled in the empty placeholder package). |
| `freethreaded/patches/mupdf-0001-free-threading.patch` | MuPDF 1.28.6: allocator fast path, glyph rendering outside the glyph cache lock, font cache publishing, warning/error callbacks for all threads, optional `MUPDF_indep_ctx=1`. Edits `scripts/wrap/cpp.py` and `swig.py` (code generators), so re-check on every MuPDF upgrade. |
| `freethreaded/patches/mupdf-0002-atomic-refcounts.patch` | Optional (see above): atomic `fz_keep_imp*`/`fz_drop_imp*` in `include/mupdf/fitz/context.h`. |
| `freethreaded/patches/layout-0001-free-threading.patch` | pymupdf_layout 2.1: per-thread models, onnxruntime thread settings, `GlobalConfig`. |
| `freethreaded/patches/pymupdf4llm-0001-free-threading.patch` | pymupdf4llm: lock skipped with per-thread models, OCR and message fixes. |
| `freethreaded/patches/onnxruntime-0001-python-3.15-packaging.patch` | onnxruntime 1.31.1: the 3.15 subset of upstream PR #33359 (classifier, numpy pin for unit-test builds). |
| `freethreaded/testdocs/manifest.json` | 45 real-world PDFs (public domain, CC0, CC BY), with licence evidence and attribution. Downloaded by CI, not stored here. |
| `.github/workflows/freethreaded_315t.yml` | Builds both wheels, runs `freethreaded/verify`, and profiles thread scaling. |

The layout C code (`features.c`, `features.i`, tgif) needed no changes: it has no mutable global
state, and tgif's static model tables are never written.

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
| `PYMUPDF_LAYOUT_PER_THREAD` | `1` | One layout model per thread (about 20 MB each). `0`: one shared model behind `_LAYOUT_LOCK`. |
| `PYMUPDF_LAYOUT_ORT_THREADS` | `1` | onnxruntime intra-op threads per session for models made on worker threads. `0`: onnxruntime's defaults. With few worker threads on a big machine, 2–4 can help. |
| `MUPDF_indep_ctx` | `0` | **Experimental, benchmarking only.** `1` gives each thread a fully independent MuPDF context with no locks. It is not safe in general (see below). |

Two-thirds of `to_markdown` time is ONNX inference on the kit's corpus, so MuPDF-level speedups
move it less than they move rendering or plain text extraction. `freethreaded/verify/profile_md.py`
shows per-stage wall and CPU time at several thread counts; the CI `profile` artifact has its
output, plus `perf` reports of on-CPU and blocking call stacks.

## Verify

```bash
python -I freethreaded/verify/fetch_docs.py freethreaded/testdocs/manifest.json docs
freethreaded/verify/run_all.sh /path/to/python-with-official-pymupdf-2.1 /path/to/python3.15t-with-ours verify-work docs
```

It generates 80 development and 60 held-out PDFs (seeded; text from small word lists), records
every `_features` call and the reference markdown with the official wheel, then checks ours:

1. `_features` bit-exact on all 112 fields;
2. `_features` thread stress at 8 threads × 3 rounds, `MUPDF_indep_ctx` 0 and 1;
3. at 1/4/8 threads, with a new thread pool per round and `MUPDF_indep_ctx` 0 and 1:
   rendering in RGB/GRAY/CMYK, text, image info, and either `rawdict` character boxes or
   `find_tables()` (so both run at once); hashes must equal the sequential run;
4. `to_markdown` byte-identical with the built-in per-thread models at 1/4/8 threads × 3 rounds,
   `MUPDF_indep_ctx` 0 and 1, and once with `PYMUPDF_LAYOUT_PER_THREAD=0`;
5. with the real-world PDFs: step 3 on the first 6 pages and step 4 on the first 12 pages of each.

It prints `ALL CHECKS PASSED` at the end. CI uses the official wheel on Python 3.14 as the
reference, because PyPI has no onnxruntime for 3.15. `results/` holds the kit's original logs.

The real-world set (`testdocs/manifest.json`) has two-column papers (arXiv, PLOS, eLife,
Frontiers, JOSS, Copernicus), US government reports and forms (IRS, NIST, GPO, Census, Federal
Reserve), long documents, Chinese, Russian, Korean, Arabic, Hebrew, Greek and Japanese, scans
(one without a text layer), NASA slide decks and brochures, an encrypted form that opens with an
empty password, and a Federal Register issue with rotated pages. Four URLs serve the current
edition (`"pinned": false`), so their hashes are not enforced.

## Thread-safety rules

- A Document and its pages, TextPages and Pixmaps stay with one thread. Each
  `fz_features_for_region` call modifies the text page.
- Process-wide settings (`TOOLS.set_small_glyph_heights`, `unset_quad_corrections`,
  `set_subset_fontnames`, `mupdf_display_errors`, `set_messages`, …) are meant to be set once,
  before threads start. `TOOLS.set_aa_level`, `set_graphics_min_line_width` and `set_icc` act on
  the calling thread's context only.
- Set warning/error callbacks (`mupdf.fz_set_warning_callback`) only before starting threads;
  replacing one frees the previous callback object while other threads' contexts may still use
  it.
- **`MUPDF_indep_ctx=1` is not safe for general use.** Independent contexts have no locks, so any
  MuPDF object released on a thread other than its own corrupts refcounts, and Python's garbage
  collector can run finalisers on any thread. Also, HarfBuzz (HTML/Story/EPUB layout), OpenJPEG
  (JPX images) and Leptonica (OCR) keep one process-wide context pointer that MuPDF protects only
  with those (now no-op) locks. And an independent context is dropped when its thread exits, so
  objects it made must not outlive the thread. It is kept for measuring lock contention.
- Upstream says PyMuPDF does not support multithreaded use (FAQ). This build is ours to support.

## Keeping it current

On each new PyMuPDF / MuPDF / layout / pymupdf4llm / onnxruntime release:

1. Rebase this branch on the new PyMuPDF tag.
2. Update the pins in `scripts/build_pymupdf.sh`, `scripts/build_onnxruntime.sh` and the
   workflow (read the layout and pymupdf4llm commits from the new official wheel's `_build.py`).
3. Re-apply the patches. The MuPDF patch edits code generators (`scripts/wrap`), so re-check
   those hunks. Drop the
   onnxruntime patch once onnxruntime supports 3.15 upstream, and drop the onnxruntime build once
   PyPI has cp315t wheels.
4. Check that `reinit_singlethreaded()`, `activate()` and `make_session()` in `pymupdf.layout`,
   and `get_layout_locked` in pymupdf4llm still exist and behave the same, and look for new
   module-level state in the same places the audit covered (module globals written per call,
   settings changed and restored around a call, lazily created shared objects).
5. Push; the workflow must end with `ALL CHECKS PASSED`.

## Known gaps

- Linux x86_64 only.
- SWIG calls never detach from the interpreter, so a free-threaded garbage collection (which
  stops all threads) waits for the longest MuPDF call in progress. SWIG's `-threads` on the
  `mupdf` module would fix that; not done yet.
- Minor MuPDF races not fixed: hyphenation dictionaries load lazily without a lock (HTML with
  hyphenation), and lcms warnings from all threads go to the base context.
- With `MUPDF_indep_ctx=1`: see the thread-safety rules.
- The real-world test set has no CC BY slide decks or brochures from outside the US government.

## License

PyMuPDF, MuPDF, pymupdf_layout and pymupdf4llm are AGPL-3.0 (or Artifex commercial licences).
Anyone distributing wheels built from this branch must offer the corresponding source: this
branch plus the pinned sources. onnxruntime is MIT.

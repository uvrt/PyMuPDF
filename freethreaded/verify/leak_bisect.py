"""Which stage of to_markdown leaks? Runs each stage alone over the first page of every PDF in
PDFDIR, ROUNDS times after a warm-up round, and reports the growth of memory that glibc malloc
has handed out and not got back (mallinfo2: uordblks + hblkhd) per call. A stage that leaks
shows a steady positive figure; caches settle during warm-up. Run on our build and on the
official wheel to tell our leaks from upstream ones.
usage: python leak_bisect.py PDFDIR ROUNDS [THREADS]"""
import ctypes, gc, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import pymupdf, pymupdf.layout, pymupdf4llm  # noqa: F401
import pymupdf.features as F
from common import textpage

pdfdir, ROUNDS = sys.argv[1], int(sys.argv[2])
THREADS = int(sys.argv[3]) if len(sys.argv) > 3 else 1
files = sorted(os.path.join(pdfdir, f) for f in os.listdir(pdfdir) if f.endswith(".pdf"))


class _MallInfo2(ctypes.Structure):
    _fields_ = [(n, ctypes.c_size_t) for n in
                ("arena", "ordblks", "smblks", "hblks", "hblkhd", "usmblks", "fsmblks", "uordblks", "fordblks", "keepcost")]


_libc = ctypes.CDLL("libc.so.6")
_libc.mallinfo2.restype = _MallInfo2


def in_use():
    gc.collect()
    m = _libc.mallinfo2()
    return m.uordblks + m.hblkhd


def on_page(fn):
    def run(path):
        doc = pymupdf.open(path)
        try:
            fn(doc[0])
        finally:
            doc.close()
    return run


STAGES = {
    "open+close": lambda path: pymupdf.open(path).close(),
    "textpage": on_page(lambda p: textpage(p)),
    "features": on_page(lambda p: F.fz_features_for_region(textpage(p), pymupdf.mupdf.FzRect(*p.rect), 0)),
    "dict": on_page(lambda p: p.get_text("dict")),
    "image_info": on_page(lambda p: p.get_image_info()),
    "drawings": on_page(lambda p: p.get_drawings()),
    "tables": on_page(lambda p: p.find_tables(use_layout=False)),
    "pixmap": on_page(lambda p: p.get_pixmap(dpi=100)),
    "get_layout": on_page(lambda p: p.get_layout()),
    "to_markdown": lambda path: pymupdf4llm.to_markdown(path, pages=[0], write_images=False, show_progress=False),
}
only = os.environ.get("STAGES")
print(f"# pymupdf {pymupdf.__version__} python {sys.version.split()[0]} gil={getattr(sys, '_is_gil_enabled', lambda: True)()} "
      f"files={len(files)} rounds={ROUNDS} threads={THREADS}", flush=True)
for name, fn in STAGES.items():
    if only and name not in only.split(","):
        continue
    jobs = list(files)
    with ThreadPoolExecutor(THREADS) as ex:
        list(ex.map(fn, jobs))                      # warm-up: caches, models, lazy imports
        list(ex.map(fn, jobs))
        m0, t0 = in_use(), time.perf_counter()
        for _ in range(ROUNDS):
            list(ex.map(fn, jobs))
        m1 = in_use()
    calls = ROUNDS * len(jobs)
    print(f"{name:12s} calls={calls:5d} growth={(m1 - m0) / 2**20:8.2f} MB  per call={(m1 - m0) / calls / 1024:8.1f} KB  "
          f"time={time.perf_counter() - t0:6.1f}s", flush=True)

"""How long does a garbage collection take while other threads run long MuPDF calls?
On free-threaded CPython a collection stops the world and must wait for every thread to reach a
safepoint; a thread inside a long call into MuPDF that stays attached delays it. WORKERS threads
loop over the most vector-heavy pages of PDFDIR running OP (get_drawings, get_text_dict,
get_textpage or get_pixmap); the main thread runs gc.collect() every 0.2 s and reports the
pause distribution. Compare with OP=none (no workers) for the baseline.
PDFDIR "synthetic:N" uses one generated page with N line segments instead (a heavy vector
page, such as a map or CAD drawing, where one call takes long).
usage: python gc_pause.py PDFDIR OP [WORKERS] [SECONDS]"""
import gc, os, sys, threading, time
import pymupdf

pdfdir, OP = sys.argv[1], sys.argv[2]
WORKERS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
SECONDS = float(sys.argv[4]) if len(sys.argv) > 4 else 20

OPS = {
    "get_drawings": lambda p: p.get_drawings(),
    "get_text_dict": lambda p: p.get_text("dict"),
    "get_textpage": lambda p: p.get_textpage(),
    "get_pixmap": lambda p: p.get_pixmap(dpi=150),
}


def synthetic(n):
    """One page with n separate stroked paths (one device callback each)."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=1000)
    shape = page.new_shape()
    for i in range(n):
        x, y = (i * 37) % 1000, (i * 53) % 1000
        shape.draw_line((x, y), ((x + 13) % 1000, (y + 29) % 1000))
        shape.finish(color=(0, 0, 0), width=0.3)
    shape.commit()
    return doc.tobytes()


SYNTHETIC = pdfdir.startswith("synthetic:")
if SYNTHETIC:
    data = synthetic(int(pdfdir.split(":", 1)[1]))
    pages = [(len(pymupdf.open(stream=data)[0].get_cdrawings()), "synthetic", 0)]
else:
    # The pages with the most drawing commands, so each call is long.
    pages = []
    for f in sorted(os.listdir(pdfdir)):
        if f.endswith(".pdf"):
            doc = pymupdf.open(os.path.join(pdfdir, f))
            for pno in range(min(doc.page_count, 4)):
                pages.append((len(doc[pno].get_cdrawings()), f, pno))
            doc.close()
    pages = sorted(pages, reverse=True)[:8]
stop = time.monotonic() + SECONDS
calls = [0]


def worker(k):
    f, pno = pages[k % len(pages)][1:]
    doc = pymupdf.open(stream=data) if SYNTHETIC else pymupdf.open(os.path.join(pdfdir, f))
    page = doc[pno]
    while time.monotonic() < stop:
        OPS[OP](page)
        calls[0] += 1
    doc.close()


threads = [] if OP == "none" else [threading.Thread(target=worker, args=(k,)) for k in range(WORKERS)]
for t in threads:
    t.start()
time.sleep(1)
pauses = []
while time.monotonic() < stop:
    t0 = time.perf_counter()
    gc.collect()
    pauses.append((time.perf_counter() - t0) * 1000)
    time.sleep(0.2)
for t in threads:
    t.join()
pauses.sort()
n = len(pauses)
print(f"gc_pause op={OP} workers={len(threads)} gil={sys._is_gil_enabled()} collections={n} calls={calls[0]} "
      f"largest pages: {pages[0][0]} drawings; pause ms p50={pauses[n // 2]:.1f} p90={pauses[int(n * 0.9)]:.1f} "
      f"max={pauses[-1]:.1f}", flush=True)

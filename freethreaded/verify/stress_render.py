"""Thread stress and throughput for rendering and text extraction (no layout model).
Each job opens its own document; per page it renders in RGB, GRAY and CMYK (the module-level
csRGB/csGRAY/csCMYK colorspaces), extracts text and image info, and then either character boxes
(rawdict) or tables (find_tables), so both run at once in different threads. Every hash must
equal the sequential run.
A fresh thread pool per round makes threads start and exit, which drops thread-local objects.
usage: python stress_render.py PDFDIR THREADS[,..] ROUNDS
Run with MUPDF_indep_ctx=0 and 1."""
import hashlib, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import pymupdf
from common import page_numbers
pdfdir = sys.argv[1]; NS = [int(x) for x in sys.argv[2].split(",")]; ROUNDS = int(sys.argv[3])
files = sorted(os.path.join(pdfdir, f) for f in os.listdir(pdfdir) if f.endswith(".pdf"))
def job(i):
    # Jobs alternate between two mixes, so that find_tables() (which changes text-extraction
    # settings for its own thread) runs while other threads extract character boxes.
    k = i % len(files); h = hashlib.sha1()
    doc = pymupdf.open(files[k])
    for pno in page_numbers(doc) or range(doc.page_count):
        page = doc[pno]
        h.update(repr(page.rect).encode())
        for cs in (pymupdf.csRGB, pymupdf.csGRAY, pymupdf.csCMYK):
            h.update(page.get_pixmap(colorspace=cs, dpi=72).samples)
        h.update(page.get_text("text").encode())
        h.update(repr(page.get_image_info()).encode())
        if (i // len(files)) % 2 == 0:
            h.update(repr(page.get_text("rawdict")).encode())
        else:
            h.update(repr([t.extract() for t in page.find_tables(use_layout=False)]).encode())
    doc.close()
    return i, h.hexdigest()
t0 = time.perf_counter()
ref = dict(job(i) for i in range(2 * len(files)))  # both mixes
seq = time.perf_counter() - t0
print(f"indep_ctx={os.environ.get('MUPDF_indep_ctx', '0')} gil={sys._is_gil_enabled()} files={len(files)} sequential={seq:.2f}s", flush=True)
failed = False
for n in NS:
    t0 = time.perf_counter(); bad = 0; jobs = 0
    for _ in range(ROUNDS):
        with ThreadPoolExecutor(n) as ex:
            for k, h in ex.map(job, range(2 * len(files))):
                bad += h != ref[k]; jobs += 1
    wall = time.perf_counter() - t0
    failed |= bad > 0
    print(f"threads={n} jobs={jobs} mismatched={bad} wall={wall:.2f}s docs/s={jobs / wall:.1f} speedup={seq * ROUNDS / wall:.2f}x", flush=True)
sys.exit(1 if failed else 0)

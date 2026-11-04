"""End-to-end: pymupdf4llm.to_markdown (layout on) for every PDF in PDFDIR, compared byte-for-byte with
reference markdown REFDIR/<name>.md (made by record.py --md on official 3.15).
usage: python md_check.py PDFDIR REFDIR THREADS[,..] ROUNDS [perthread|shipped]
perthread = the built-in default on 3.15t: one layout model per thread, no _LAYOUT_LOCK.
shipped = PYMUPDF_LAYOUT_PER_THREAD=0: one shared model behind _LAYOUT_LOCK."""
import sys, os, time
from concurrent.futures import ThreadPoolExecutor
VARIANT = sys.argv[5] if len(sys.argv) > 5 else "perthread"
if VARIANT == "shipped":
    os.environ["PYMUPDF_LAYOUT_PER_THREAD"] = "0"
import pymupdf, pymupdf.layout, pymupdf4llm
assert pymupdf._get_layout_per_thread == (VARIANT == "perthread"), VARIANT
pdfdir, refdir = sys.argv[1], sys.argv[2]
NS = [int(x) for x in sys.argv[3].split(",")]; ROUNDS = int(sys.argv[4])
files = sorted(f for f in os.listdir(pdfdir) if f.endswith(".pdf"))
ref = {f: open(os.path.join(refdir, f[:-4] + ".md")).read() for f in files}
def job(i):
    f = files[i % len(files)]
    doc = pymupdf.open(os.path.join(pdfdir, f))
    md = pymupdf4llm.to_markdown(doc, show_progress=False)
    doc.close()
    return f, md == ref[f]
for n in NS:
    t0 = time.perf_counter()
    with ThreadPoolExecutor(n) as ex:
        res = list(ex.map(job, range(ROUNDS * len(files))))
    bad = sorted({f for f, ok in res if not ok})
    print(f"{VARIANT} threads={n} gil={getattr(sys,'_is_gil_enabled',lambda:True)()} jobs={len(res)} identical={sum(ok for _, ok in res)} "
          f"different={len(res)-sum(ok for _, ok in res)} wall={time.perf_counter()-t0:.1f}s {bad[:5]}", flush=True)

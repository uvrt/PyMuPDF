"""Thread stress for to_markdown with layout (onnxruntime), self-referenced: every threaded
result must equal this build's sequential result. For sanitizer runs, where no official
reference is available. Exit 1 on any difference.
usage: python stress_md.py PDFDIR THREADS ROUNDS"""
import os, sys, time
from concurrent.futures import ThreadPoolExecutor
import pymupdf, pymupdf.layout, pymupdf4llm  # noqa: F401
from common import page_numbers

pdfdir, N, ROUNDS = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
files = sorted(os.path.join(pdfdir, f) for f in os.listdir(pdfdir) if f.endswith(".pdf"))


def md(path):
    doc = pymupdf.open(path)
    out = pymupdf4llm.to_markdown(doc, pages=page_numbers(doc), write_images=False, show_progress=False)
    doc.close()
    return out


t0 = time.perf_counter()
ref = {f: md(f) for f in files}
seq = time.perf_counter() - t0
t0 = time.perf_counter()
with ThreadPoolExecutor(N) as ex:
    res = list(ex.map(lambda i: (files[i % len(files)], md(files[i % len(files)])), range(ROUNDS * len(files))))
bad = sorted({os.path.basename(f) for f, m in res if m != ref[f]})
print(f"stress_md threads={N} gil={sys._is_gil_enabled()} files={len(files)} jobs={len(res)} "
      f"different={len(bad)} sequential={seq:.1f}s threaded={time.perf_counter() - t0:.1f}s {bad[:5]}", flush=True)
sys.exit(1 if bad else 0)

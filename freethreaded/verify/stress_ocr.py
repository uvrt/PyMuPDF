"""Thread stress for OCR (Tesseract + Leptonica, built into MuPDF).
Each job opens its own document and OCRs its first page (full page, 100 dpi). Every text must
equal the sequential run. Before the free-threading patch, two threads starting OCR at once
raised "Attempt to use Leptonica from 2 threads at once!".
usage: python stress_ocr.py PDFDIR THREADS[,..] ROUNDS [TESSDATA]"""
import hashlib, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import pymupdf
pdfdir = sys.argv[1]; NS = [int(x) for x in sys.argv[2].split(",")]; ROUNDS = int(sys.argv[3])
TESSDATA = sys.argv[4] if len(sys.argv) > 4 else None
files = sorted(os.path.join(pdfdir, f) for f in os.listdir(pdfdir) if f.endswith(".pdf"))[:16]
def job(i):
    doc = pymupdf.open(files[i % len(files)])
    tp = doc[0].get_textpage_ocr(dpi=100, full=True, tessdata=TESSDATA)
    text = doc[0].get_text("text", textpage=tp)
    doc.close()
    return i, hashlib.sha1(text.encode()).hexdigest()
t0 = time.perf_counter()
ref = dict(job(i) for i in range(len(files)))
seq = time.perf_counter() - t0
print(f"ocr gil={sys._is_gil_enabled()} files={len(files)} sequential={seq:.2f}s", flush=True)
failed = False
for n in NS:
    t0 = time.perf_counter(); bad = 0; jobs = 0
    for _ in range(ROUNDS):
        with ThreadPoolExecutor(n) as ex:
            for k, h in ex.map(job, range(len(files))):
                bad += h != ref[k]; jobs += 1
    wall = time.perf_counter() - t0
    failed |= bad > 0
    print(f"ocr threads={n} jobs={jobs} mismatched={bad} wall={wall:.2f}s speedup={seq * ROUNDS / wall:.2f}x", flush=True)
sys.exit(1 if failed else 0)

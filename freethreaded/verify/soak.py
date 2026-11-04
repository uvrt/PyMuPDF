"""Soak test: THREADS threads run a mixed workload (to_markdown with layout, rendering in
three colorspaces, text, rawdict, tables) for MINUTES, each result checked against a
sequential reference; the process RSS is sampled every 30 s.
Fails on any wrong result, or when memory keeps growing: the RSS slope over the second half
of the run (after caches have filled) must stay under MAX_MB_PER_HOUR (default 50).
usage: python soak.py PDFDIR THREADS MINUTES [OUT.csv]"""
import hashlib, os, sys, threading, time
import psutil
import pymupdf, pymupdf.layout, pymupdf4llm  # noqa: F401
from common import page_numbers

pdfdir, N, MINUTES = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
OUT = sys.argv[4] if len(sys.argv) > 4 else None
MAX_SLOPE = float(os.environ.get("MAX_MB_PER_HOUR", "50"))
files = sorted(os.path.join(pdfdir, f) for f in os.listdir(pdfdir) if f.endswith(".pdf"))


def work(k):
    path = files[k % len(files)]
    h = hashlib.sha1()
    doc = pymupdf.open(path)
    pages = page_numbers(doc) or range(doc.page_count)
    if (k // len(files)) % 2 == 0:
        h.update(pymupdf4llm.to_markdown(doc, pages=list(pages), write_images=False, show_progress=False).encode())
    else:
        for pno in pages:
            page = doc[pno]
            for cs in (pymupdf.csRGB, pymupdf.csGRAY, pymupdf.csCMYK):
                h.update(page.get_pixmap(colorspace=cs, dpi=72).samples)
            h.update(page.get_text("text").encode())
            h.update(repr(page.get_text("rawdict")).encode())
            h.update(repr([t.extract() for t in page.find_tables(use_layout=False)]).encode())
    doc.close()
    return h.hexdigest()


ref = {k: work(k) for k in range(2 * len(files))}
proc = psutil.Process()
stop = time.monotonic() + MINUTES * 60
lock = threading.Lock()
stats = {"jobs": 0, "bad": 0}
next_job = [0]


def worker():
    while time.monotonic() < stop:
        with lock:
            k = next_job[0] % (2 * len(files)); next_job[0] += 1
        ok = work(k) == ref[k]
        with lock:
            stats["jobs"] += 1; stats["bad"] += not ok


threads = [threading.Thread(target=worker) for _ in range(N)]
t0 = time.monotonic()
for t in threads:
    t.start()
samples = []
while any(t.is_alive() for t in threads):
    samples.append((time.monotonic() - t0, proc.memory_info().rss / 2**20, stats["jobs"]))
    print(f"t={samples[-1][0]:7.0f}s rss={samples[-1][1]:8.1f} MB jobs={samples[-1][2]}", flush=True)
    for _ in range(30):
        if not any(t.is_alive() for t in threads):
            break
        time.sleep(1)
for t in threads:
    t.join()

half = [s for s in samples if s[0] >= samples[-1][0] / 2]
n = len(half)
if n >= 3:
    mx = sum(s[0] for s in half) / n; my = sum(s[1] for s in half) / n
    slope = sum((s[0] - mx) * (s[1] - my) for s in half) / max(sum((s[0] - mx) ** 2 for s in half), 1e-9) * 3600
else:
    slope = 0.0
if OUT:
    with open(OUT, "w") as f:
        f.write("seconds,rss_mb,jobs\n" + "".join(f"{a:.0f},{b:.1f},{c}\n" for a, b, c in samples))
peak = max(s[1] for s in samples)
print(f"soak threads={N} minutes={MINUTES:g} jobs={stats['jobs']} wrong={stats['bad']} peak_rss={peak:.0f} MB "
      f"second-half slope={slope:+.1f} MB/hour (limit {MAX_SLOPE:g})", flush=True)
sys.exit(1 if stats["bad"] or slope > MAX_SLOPE else 0)

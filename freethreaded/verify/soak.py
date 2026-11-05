"""Soak test: THREADS threads run a mixed workload (to_markdown with layout, rendering in
three colorspaces, text, rawdict, tables) for MINUTES, each result checked against a
sequential reference; the process RSS is sampled every 30 s.
Fails on any wrong result, or when memory keeps growing. Memory is compared by quarters, after
caches have filled: the mean of the last quarter may exceed the mean of the second quarter by
at most 10% (and at least 100 MB), both for glibc's bytes in use (a leak) and for RSS. Swings
of a few hundred MB, as large pages come and go, don't trip it; a steady leak does (checked on
the runs before and after the layout font leak fix: +400..785 MB vs +10..76 MB).
Each sample also records, to tell a leak from fragmentation: glibc's bytes in use and heap
reserved (mallinfo2) and Python's live objects (sys.getallocatedblocks);
at the end, the object types whose count grew most.
SOAK_MODE: mix (default), md (to_markdown only) or render (rendering and text only).
usage: python soak.py PDFDIR THREADS MINUTES [OUT.csv]"""
import collections, ctypes, gc, hashlib, os, sys, threading, time
import psutil
import pymupdf, pymupdf.layout, pymupdf4llm  # noqa: F401
from common import page_numbers

pdfdir, N, MINUTES = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
OUT = sys.argv[4] if len(sys.argv) > 4 else None
MODE = os.environ.get("SOAK_MODE", "mix")


class _MallInfo2(ctypes.Structure):
    _fields_ = [(n, ctypes.c_size_t) for n in
                ("arena", "ordblks", "smblks", "hblks", "hblkhd", "usmblks", "fsmblks", "uordblks", "fordblks", "keepcost")]


try:
    _libc = ctypes.CDLL("libc.so.6")
    _libc.mallinfo2.restype = _MallInfo2
except (OSError, AttributeError):
    _libc = None


def malloc_mb():
    """(in use, reserved) by glibc malloc, MB: uordblks + hblkhd, arena + hblkhd."""
    if _libc is None:
        return float("nan"), float("nan")
    m = _libc.mallinfo2()
    return (m.uordblks + m.hblkhd) / 2**20, (m.arena + m.hblkhd) / 2**20


def type_counts():
    return collections.Counter(type(o).__qualname__ for o in gc.get_objects())


files = sorted(os.path.join(pdfdir, f) for f in os.listdir(pdfdir) if f.endswith(".pdf"))


def work(k):
    path = files[k % len(files)]
    h = hashlib.sha1()
    doc = pymupdf.open(path)
    pages = page_numbers(doc) or range(doc.page_count)
    if MODE == "md" or (MODE == "mix" and (k // len(files)) % 2 == 0):
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


gc.collect()
types0 = type_counts()
threads = [threading.Thread(target=worker) for _ in range(N)]
t0 = time.monotonic()
for t in threads:
    t.start()
samples = []
while any(t.is_alive() for t in threads):
    used, reserved = malloc_mb()
    samples.append((time.monotonic() - t0, proc.memory_info().rss / 2**20, stats["jobs"], used, reserved,
                    sys.getallocatedblocks()))
    print(f"t={samples[-1][0]:7.0f}s rss={samples[-1][1]:8.1f} MB jobs={samples[-1][2]} malloc_used={used:8.1f} MB "
          f"malloc_reserved={reserved:8.1f} MB py_blocks={samples[-1][5]}", flush=True)
    for _ in range(30):
        if not any(t.is_alive() for t in threads):
            break
        time.sleep(1)
for t in threads:
    t.join()

half = [s for s in samples if s[0] >= samples[-1][0] / 2]


def slope(col):
    """Least-squares slope of column col over the second half, per hour."""
    n = len(half)
    if n < 3:
        return 0.0
    mx = sum(s[0] for s in half) / n; my = sum(s[col] for s in half) / n
    return sum((s[0] - mx) * (s[col] - my) for s in half) / max(sum((s[0] - mx) ** 2 for s in half), 1e-9) * 3600


def quarter_growth(col):
    """(mean of the second quarter, mean of the last quarter, allowed growth), in MB."""
    end = samples[-1][0]
    q2 = [s[col] for s in samples if end / 4 <= s[0] < end / 2]
    q4 = [s[col] for s in samples if s[0] >= 3 * end / 4]
    if not q2 or not q4:
        return 0.0, 0.0, float("inf")
    m2, m4 = sum(q2) / len(q2), sum(q4) / len(q4)
    return m2, m4, max(100.0, 0.10 * m2)


rss_q = quarter_growth(1)
used_q = quarter_growth(3)
if OUT:
    with open(OUT, "w") as f:
        f.write("seconds,rss_mb,jobs,malloc_used_mb,malloc_reserved_mb,py_blocks\n"
                + "".join(",".join(f"{v:.1f}" if isinstance(v, float) else str(v) for v in s) + "\n" for s in samples))
gc.collect()
grown = (type_counts() - types0).most_common(12)
peak = max(s[1] for s in samples)
print(f"soak mode={MODE} threads={N} minutes={MINUTES:g} jobs={stats['jobs']} wrong={stats['bad']} peak_rss={peak:.0f} MB "
      f"MALLOC_ARENA_MAX={os.environ.get('MALLOC_ARENA_MAX', '-')}", flush=True)
print(f"second-half slopes per hour (information): rss {slope(1):+.1f} MB, malloc in use {slope(3):+.1f} MB, "
      f"malloc reserved {slope(4):+.1f} MB, python blocks {slope(5):+.0f}", flush=True)
grew = [f"{name}: {q[0]:.0f} -> {q[1]:.0f} MB (allowed +{q[2]:.0f})" for name, q in (("malloc in use", used_q), ("rss", rss_q))]
leak = used_q[1] - used_q[0] > used_q[2] or rss_q[1] - rss_q[0] > rss_q[2]
print("memory, second quarter -> last quarter: " + "; ".join(grew) + (" GROWING" if leak else " flat"), flush=True)
print("python object types grown since start:", ", ".join(f"{t} +{n}" for t, n in grown) or "none", flush=True)
sys.exit(1 if stats["bad"] or leak else 0)

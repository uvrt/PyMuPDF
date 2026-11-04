"""bench_md.py PDFDIR JOBS KIND N1,N2,.. VARIANT [OUTJSON]
KIND=thread|process; VARIANT=shipped (PYMUPDF_LAYOUT_PER_THREAD=0: one model + _LAYOUT_LOCK) | perthread (built-in default on 3.15t).
Workload = our production call: pymupdf.layout active, pymupdf4llm.to_markdown(doc, write_images=False).
onnxruntime capped to 1 intra-op / 1 inter-op thread per session (as apps.common.pdf_pool does)."""
import sys, os, time, hashlib, json, resource
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import multiprocessing as mp
pdfdir, JOBS, KIND, NS, VARIANT = sys.argv[1], int(sys.argv[2]), sys.argv[3], [int(x) for x in sys.argv[4].split(",")], sys.argv[5]
OUT = sys.argv[6] if len(sys.argv) > 6 else None
FILES = sorted(os.path.join(pdfdir, f) for f in os.listdir(pdfdir) if f.endswith(".pdf"))
_DATA = None
_SETUP = False
def setup():
    global _SETUP, _DATA
    if _SETUP: return
    import onnxruntime as ort
    base = ort.InferenceSession
    class InferenceSession(base):
        def __init__(self, p, sess_options=None, *a, **k):
            o = sess_options if sess_options is not None else ort.SessionOptions()
            if not o.intra_op_num_threads: o.intra_op_num_threads = 1
            if not o.inter_op_num_threads: o.inter_op_num_threads = 1
            super().__init__(p, o, *a, **k)
    ort.InferenceSession = InferenceSession
    if VARIANT == "shipped":
        os.environ["PYMUPDF_LAYOUT_PER_THREAD"] = "0"
    import pymupdf, pymupdf.layout, pymupdf4llm
    if getattr(sys, "_is_gil_enabled", lambda: True)() is False:
        assert pymupdf._get_layout_per_thread == (VARIANT == "perthread"), VARIANT
    _DATA = [open(f, "rb").read() for f in FILES]
    _SETUP = True
def job(i):
    setup()
    import pymupdf, pymupdf4llm
    c0, w0 = time.thread_time(), time.perf_counter()
    k = i % len(FILES)
    doc = pymupdf.open(stream=_DATA[k], filetype="pdf")
    md = pymupdf4llm.to_markdown(doc, write_images=False, show_progress=False)
    doc.close()
    return k, hashlib.sha1(md.encode()).hexdigest(), time.thread_time() - c0, time.perf_counter() - w0
def warm(_=None):
    setup(); return os.getpid()
def rss_mb():
    me = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    ch = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    return me, ch
def cur_rss_mb(pids):
    tot = 0
    for p in pids:
        try:
            for l in open(f"/proc/{p}/status"):
                if l.startswith("VmHWM:"): tot += int(l.split()[1]) / 1024
        except OSError: pass
    return tot
if __name__ == "__main__":
    setup()
    import pymupdf
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    ref = {}
    for i in range(len(FILES)):
        k, h, c, w = job(i); ref[k] = h
    print(f"# {sys.version.split()[0]} gil={gil} kind={KIND} variant={VARIANT} jobs={JOBS} files={len(FILES)} pages/file={pymupdf.open(FILES[0]).page_count} last-1job={w:.2f}s", flush=True)
    results = {"ref": ref, "runs": []}
    for n in NS:
        if KIND == "thread":
            ex = ThreadPoolExecutor(n); pids = [os.getpid()]
        else:
            ex = ProcessPoolExecutor(n, mp_context=mp.get_context("spawn"))
            pids = set(ex.map(warm, range(n * 3)))
        list(ex.map(warm, range(n)))
        p0 = time.process_time(); t0 = time.perf_counter()
        res = list(ex.map(job, range(JOBS)))
        wall = time.perf_counter() - t0; pcpu = time.process_time() - p0
        peak = cur_rss_mb(pids if KIND == "process" else [os.getpid()])
        ex.shutdown()
        bad = sum(ref[k] != h for k, h, _, _ in res)
        cpu = sum(r[2] for r in res); jw = sum(r[3] for r in res)
        line = dict(kind=KIND, variant=VARIANT, n=n, wall=round(wall, 2), docs_per_s=round(JOBS / wall, 3), sum_job_cpu=round(cpu, 1), sum_job_wall=round(jw, 1), peak_rss_mb=round(peak), mismatches_vs_own_seq=bad, hashes=sorted(set(h for _, h, _, _ in res)))
        results["runs"].append(line)
        print(f"{KIND:7s} {VARIANT:9s} n={n} wall={wall:7.2f}s docs/s={JOBS/wall:5.2f} sum_job_cpu={cpu:7.1f}s sum_job_wall={jw:7.1f}s peakRSS={peak:6.0f}MB mismatches={bad}", flush=True)
    if OUT: json.dump(results, open(OUT, "w"), indent=1)

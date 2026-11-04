"""Where does to_markdown time go, and which stages slow down when threads run in parallel?

usage: python profile_md.py PDFDIR JOBS THREADS[,..] [OUTJSON]

Runs JOBS to_markdown jobs (one Document per job) at each thread count and times every call to
the main stages per thread: wall time (perf_counter) and CPU time (thread_time). Per job, compared
with 1 thread:
- wall grows, CPU flat  -> the stage waits (a lock, or too few cores);
- wall and CPU grow     -> spinning, oversubscription or cache/memory contention;
- both flat             -> the stage scales.
"python" is to_markdown time outside the instrumented stages.
"gc" is time inside cyclic garbage collections (gc.callbacks, all threads; free-threaded collections
stop the world, so every other thread waits as well). PROFILE_GC=off disables the collector.
"""
import gc, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

import onnxruntime as ort
import pymupdf, pymupdf.layout, pymupdf.features, pymupdf4llm
from common import page_numbers

pdfdir, JOBS = sys.argv[1], int(sys.argv[2])
NS = [int(x) for x in sys.argv[3].split(",")]
OUT = sys.argv[4] if len(sys.argv) > 4 else None
files = sorted(os.path.join(pdfdir, f) for f in os.listdir(pdfdir) if f.endswith(".pdf"))
data = [open(f, "rb").read() for f in files]

_tl = threading.local()
_all = []
_all_lock = threading.Lock()


def _stats():
    s = getattr(_tl, "s", None)
    if s is None:
        s = _tl.s = {}
        with _all_lock:
            _all.append(s)
    return s


def _wrap(owner, name, stage):
    orig = getattr(owner, name)

    def wrapper(*a, **k):
        s = _stats()
        depth = getattr(_tl, "depth", 0)
        if depth:  # nested in another stage: count once, in the outer stage
            return orig(*a, **k)
        _tl.depth = 1
        w0, c0 = time.perf_counter(), time.thread_time()
        try:
            return orig(*a, **k)
        finally:
            _tl.depth = 0
            e = s.setdefault(stage, [0, 0.0, 0.0])
            e[0] += 1; e[1] += time.perf_counter() - w0; e[2] += time.thread_time() - c0

    setattr(owner, name, wrapper)


_gc = {"n": 0, "secs": 0.0, "t0": 0.0}


def _gc_cb(phase, info):
    if phase == "start":
        _gc["t0"] = time.perf_counter()
    else:
        _gc["n"] += 1; _gc["secs"] += time.perf_counter() - _gc["t0"]


gc.callbacks.append(_gc_cb)
if os.environ.get("PROFILE_GC") == "off":
    gc.disable()

_wrap(ort.InferenceSession, "run", "onnx")
_wrap(pymupdf.Page, "get_textpage", "stext")
_wrap(pymupdf.features, "fz_features_for_region", "features")
_wrap(pymupdf.Page, "get_image_info", "image_info")
_wrap(pymupdf.Page, "get_drawings", "drawings")
_wrap(pymupdf.Page, "find_tables", "tables")
_wrap(pymupdf.Page, "get_pixmap", "pixmap")


def job(i):
    w0, c0 = time.perf_counter(), time.thread_time()
    doc = pymupdf.open(stream=data[i % len(data)], filetype="pdf")
    pymupdf4llm.to_markdown(doc, pages=page_numbers(doc), write_images=False, show_progress=False)
    doc.close()
    e = _stats().setdefault("total", [0, 0.0, 0.0])
    e[0] += 1; e[1] += time.perf_counter() - w0; e[2] += time.thread_time() - c0


print(f"# python={sys.version.split()[0]} gil={sys._is_gil_enabled()} cpus={os.cpu_count()} "
      f"indep_ctx={os.environ.get('MUPDF_indep_ctx', '0')} per_thread_model={pymupdf._get_layout_per_thread} "
      f"ort_threads={os.environ.get('PYMUPDF_LAYOUT_ORT_THREADS', '1')} gc={'on' if gc.isenabled() else 'off'} "
      f"files={len(files)} jobs={JOBS}", flush=True)
job(0)  # warm up the importing thread's model
results = []
base = None
for n in NS:
    with ThreadPoolExecutor(n) as ex:
        list(ex.map(lambda _: job(0), range(n)))  # warm up each worker's model
        with _all_lock:
            for s in _all:  # threads keep their dict: empty it, don't drop it
                s.clear()
        _gc.update(n=0, secs=0.0)
        p0, t0 = time.process_time(), time.perf_counter()
        list(ex.map(job, range(JOBS)))
        wall, cpu = time.perf_counter() - t0, time.process_time() - p0
    tot = {}
    for s in _all:
        for k, (c, w, t) in s.items():
            e = tot.setdefault(k, [0, 0.0, 0.0]); e[0] += c; e[1] += w; e[2] += t
    stages = {k: v for k, v in tot.items() if k != "total"}
    tw, tc = tot["total"][1], tot["total"][2]
    stages["python"] = [0, tw - sum(v[1] for v in stages.values()), tc - sum(v[2] for v in stages.values())]
    per_job = {k: (v[1] / JOBS, v[2] / JOBS) for k, v in stages.items()}
    if base is None:
        base = per_job
    print(f"threads={n} wall={wall:.2f}s docs/s={JOBS / wall:.2f} cpu_util={cpu / wall:.2f}/{n} "
          f"job_wall={tw / JOBS:.3f}s job_cpu={tc / JOBS:.3f}s gc={_gc['n']}x/{_gc['secs']:.2f}s", flush=True)
    for k in sorted(per_job, key=lambda k: -per_job[k][0]):
        w, c = per_job[k]
        bw, bc = base.get(k, (w, c))
        print(f"    {k:11s} wall/job={w * 1000:8.1f}ms ({w / bw if bw else 0:4.2f}x)  "
              f"cpu/job={c * 1000:8.1f}ms ({c / bc if bc else 0:4.2f}x)  share={w / (tw / JOBS):5.1%}", flush=True)
    results.append(dict(threads=n, wall=wall, docs_per_s=JOBS / wall, cpu=cpu, stages=stages, total=tot["total"],
                        gc_collections=_gc["n"], gc_secs=_gc["secs"]))
if OUT:
    json.dump(results, open(OUT, "w"), indent=1)

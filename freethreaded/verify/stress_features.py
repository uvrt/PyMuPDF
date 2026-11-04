"""Thread stress for pymupdf.features: N threads, each opens its own document per job, builds the text
page and replays the recorded calls; every result must equal the official recording.
usage: python stress_features.py REC.pkl PDFDIR THREADS ROUNDS"""
import pickle, sys, struct, threading, time
from concurrent.futures import ThreadPoolExecutor
import pymupdf, pymupdf.features as F
from common import textpage
rec = pickle.load(open(sys.argv[1], "rb")); pdfdir = sys.argv[2]; N = int(sys.argv[3]); R = int(sys.argv[4])
keys = sorted(rec)
def same(a, b):
    return struct.pack("<d", a) == struct.pack("<d", b) if isinstance(a, float) else a == b
def job(i):
    name, pno = keys[i % len(keys)]
    doc = pymupdf.open(f"{pdfdir}/{name}"); tp = textpage(doc[pno]); bad = 0
    for bb, fl, exp in rec[(name, pno)]:
        r = F.fz_features_for_region(tp, pymupdf.mupdf.FzRect(*bb), fl)
        bad += any(not same(getattr(r, k), v) for k, v in exp.items())
    doc.close()
    return len(rec[(name, pno)]), bad
t0 = time.perf_counter()
with ThreadPoolExecutor(N) as ex:
    res = list(ex.map(job, range(R * len(keys))))
print(f"threads={N} gil={sys._is_gil_enabled()} jobs={len(res)} calls={sum(r[0] for r in res)} mismatched={sum(r[1] for r in res)} wall={time.perf_counter()-t0:.1f}s")

import pickle, sys, time, pymupdf, pymupdf.features as F
from common import textpage
rec = pickle.load(open(sys.argv[1], "rb")); pdfdir = sys.argv[2]; n = 0; t = 0.0
for (name, pno), calls in sorted(rec.items()):
    tp = textpage(pymupdf.open(f"{pdfdir}/{name}")[pno])
    regs = [pymupdf.mupdf.FzRect(*bb) for bb, _, _ in calls]
    t0 = time.perf_counter()
    for r in regs: F.fz_features_for_region(tp, r, 0)
    t += time.perf_counter() - t0; n += len(regs)
print(f"{sys.version.split()[0]} gil={getattr(sys,'_is_gil_enabled',lambda:True)()} calls={n} total={t:.3f}s per_call={t/n*1e6:.0f}us")

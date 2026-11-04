"""Replay every recorded official fz_features_for_region call (from record.py) with the locally
importable pymupdf.features on a fresh text page and compare all fields bit-exactly.
usage: python compare_features.py REC.pkl PDFDIR"""
import pickle, sys, math, struct, pymupdf, pymupdf.features as F
from common import textpage
rec = pickle.load(open(sys.argv[1], "rb")); pdfdir = sys.argv[2]
def same(a, b):
    if isinstance(a, float): return struct.pack("<d", a) == struct.pack("<d", b)
    return a == b
n = bad = 0; badfeat = {}
for (name, pno), calls in sorted(rec.items()):
    page = pymupdf.open(f"{pdfdir}/{name}")[pno]
    tp = textpage(page)
    for bb, fl, exp in calls:
        r = F.fz_features_for_region(tp, pymupdf.mupdf.FzRect(*bb), fl)
        n += 1; diff = [k for k, v in exp.items() if not same(getattr(r, k), v)]
        if diff:
            bad += 1
            for k in diff: badfeat[k] = badfeat.get(k, 0) + 1
print(f"python={sys.version.split()[0]} gil={getattr(sys,'_is_gil_enabled',lambda:True)()} pages={len(rec)} calls={n} "
      f"fields/call={len(exp)} exact={n-bad} mismatched={bad} {badfeat}")
sys.exit(1 if bad or not n else 0)

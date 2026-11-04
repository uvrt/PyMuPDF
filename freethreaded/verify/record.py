"""Record every fz_features_for_region call made by pymupdf4llm.to_markdown (layout on) with the
official closed-source module, on regular CPython 3.15.

usage: /usr/local/bin/python record.py PDFDIR OUT.pkl [--md MDDIR]
Record format: {(pdf_name, page_no): [(bbox(4 floats), flags, {feature: value}), ...]} in call order.
With --md, the markdown of each PDF is written to MDDIR/<name>.md (reference for end-to-end checks).
"""
import sys, os, glob, pickle, time
import pymupdf
import pymupdf.layout  # noqa: F401  (activates layout)
import pymupdf.features as real
import pymupdf4llm

SKIP = ("this", "thisown", "last_char_rect")
NAMES = [n for n in dir(real.fz_feature_stats) if not n.startswith("_") and n not in SKIP]

REC = {}
STATS = {"calls": 0, "secs": 0.0}
_orig = real.fz_features_for_region


def wrapped(stext_page, region, flags):
    t = time.perf_counter()
    res = _orig(stext_page, region, flags)
    STATS["secs"] += time.perf_counter() - t
    STATS["calls"] += 1
    page = stext_page.parent
    key = (os.path.basename(page.parent.name), page.number)
    REC.setdefault(key, []).append(((region.x0, region.y0, region.x1, region.y1), flags,
                                    {n: getattr(res, n) for n in NAMES}))
    return res


real.fz_features_for_region = wrapped


def main():
    pdfdir, out = sys.argv[1], sys.argv[2]
    mddir = sys.argv[sys.argv.index("--md") + 1] if "--md" in sys.argv else None
    if mddir:
        os.makedirs(mddir, exist_ok=True)
    t0 = time.perf_counter()
    for f in sorted(glob.glob(os.path.join(pdfdir, "*.pdf"))):
        doc = pymupdf.open(f)
        md = pymupdf4llm.to_markdown(doc, show_progress=False)
        if mddir:
            with open(os.path.join(mddir, os.path.basename(f)[:-4] + ".md"), "w") as fh:
                fh.write(md)
    total = time.perf_counter() - t0
    pickle.dump(REC, open(out, "wb"))
    print(f"pages={len(REC)} calls={STATS['calls']} features_secs={STATS['secs']:.3f} total_secs={total:.2f}")


if __name__ == "__main__":
    main()

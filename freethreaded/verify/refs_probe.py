"""Reference counts around the layout calls that leak_bisect.py shows growing (features about
245 KB per call, get_layout about 87 KB, the same on the official wheel): if a call leaves the
text page's or a font's count higher than it found it, that object is never freed.
usage: python refs_probe.py PDFDIR [N]"""
import os, sys
import pymupdf, pymupdf.layout  # noqa: F401
import pymupdf.features as F
from common import textpage

pdfdir = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 5
files = sorted(os.path.join(pdfdir, f) for f in os.listdir(pdfdir) if f.endswith(".pdf"))[:N]


def refs(tp):
    return tp.this.m_internal.refs


def first_font_refs(tp):
    """refs of the font of the first character, or None (also if the bindings can't walk it)."""
    try:
        return _first_font_refs(tp)
    except Exception as e:
        return f"n/a ({type(e).__name__})"


def _first_font_refs(tp):
    for block in tp.this:
        if block.m_internal.type != pymupdf.mupdf.FZ_STEXT_BLOCK_TEXT:
            continue
        for line in block:
            for ch in line:
                return ch.m_internal.font.refs
    return None


print(f"# pymupdf {pymupdf.__version__} python {sys.version.split()[0]}", flush=True)
for path in files:
    doc = pymupdf.open(path)
    page = doc[0]
    tp = textpage(page)
    r0, f0 = refs(tp), first_font_refs(tp)
    for _ in range(3):
        F.fz_features_for_region(tp, pymupdf.mupdf.FzRect(*page.rect), 0)
    r1, f1 = refs(tp), first_font_refs(tp)
    print(f"{os.path.basename(path)[:40]:40s} features x3: page refs {r0} -> {r1}, first font refs {f0} -> {f1}", flush=True)
    del tp
    tp2 = textpage(page)
    g0 = refs(tp2)
    page.get_layout()
    print(f"{'':40s} get_layout: other text page refs {g0} -> {refs(tp2)}", flush=True)
    del tp2
    doc.close()

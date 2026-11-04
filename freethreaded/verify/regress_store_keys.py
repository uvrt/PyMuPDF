"""Regression test: MuPDF's resource store must not hand one document a resource cached for
another (fixed by patches/mupdf-0001, pdf_cmp_key; the bug is in upstream MuPDF too).

Two one-page PDFs are identical except for object 5, a colour function: red in A, green in B.
Each page paints a shading whose /Function is a *direct* dictionary,
<< /FunctionType 3 /Functions [5 0 R] ... >>. Upstream compares such store keys with
pdf_objcmp, which matches "5 0 R" by number only, so once A's function is cached, B gets it
and paints red. Checked sequentially (A and B both open) and from several threads at once.
usage: python regress_store_keys.py [THREADS]   (exit 1 on failure)"""
import sys
from concurrent.futures import ThreadPoolExecutor
import pymupdf

THREADS = int(sys.argv[1]) if len(sys.argv) > 1 else 4


def make_pdf(rgb):
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 40 40] /Resources << /Shading << /Sh0 6 0 R >> >> /Contents 4 0 R >>",
        None,  # 4: content stream
        b"<< /FunctionType 2 /Domain [0 1] /C0 [%g %g %g] /C1 [%g %g %g] /N 1 >>" % (rgb + rgb),
        b"<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [0 0 40 0] /Extend [true true]"
        b" /Function << /FunctionType 3 /Domain [0 1] /Functions [5 0 R] /Bounds [] /Encode [0 1] >> >>",
    ]
    content = b"/Sh0 sh"
    objs[3] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content)
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


PDF = {"A": make_pdf((1, 0, 0)), "B": make_pdf((0, 1, 0))}
EXPECT = {"A": (255, 0, 0), "B": (0, 255, 0)}


def centre(doc):
    pix = doc[0].get_pixmap(colorspace=pymupdf.csRGB)
    return tuple(pix.pixel(pix.width // 2, pix.height // 2))[:3]


failures = []
# Sequential: A rendered and still open, then B.
a = pymupdf.open(stream=PDF["A"], filetype="pdf")
b = pymupdf.open(stream=PDF["B"], filetype="pdf")
for name, doc in (("A", a), ("B", b)):
    got = centre(doc)
    if got != EXPECT[name]:
        failures.append(f"sequential {name}: centre pixel {got}, expected {EXPECT[name]}")
a.close(); b.close()


def job(i):
    name = "AB"[i % 2]
    doc = pymupdf.open(stream=PDF[name], filetype="pdf")
    got = centre(doc)
    doc.close()
    return name, got


with ThreadPoolExecutor(THREADS) as ex:
    bad = [(n, g) for n, g in ex.map(job, range(200)) if g != EXPECT[n]]
if bad:
    failures.append(f"threads={THREADS}: {len(bad)} of 200 renders wrong, e.g. {bad[0]}")

print(f"regress_store_keys: pymupdf {pymupdf.__version__} gil={getattr(sys, '_is_gil_enabled', lambda: True)()} "
      + ("FAIL\n  " + "\n  ".join(failures) if failures else "ok"), flush=True)
sys.exit(1 if failures else 0)

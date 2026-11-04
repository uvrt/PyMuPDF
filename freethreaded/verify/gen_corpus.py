"""Reproducible synthetic PDF corpus for black-box characterisation of pymupdf._features.

usage: python gen.py OUTDIR SEED_START SEED_END
Each seed produces one PDF (1-4 pages) mixing several page "recipes". No client data:
all text is generated from small word lists.
"""
import os, random, sys, io
import pymupdf

FONTDIR = "/usr/share/fonts/truetype"
TTF = {
    "dejavu": f"{FONTDIR}/dejavu/DejaVuSans.ttf",
    "dejavub": f"{FONTDIR}/dejavu/DejaVuSans-Bold.ttf",
    "dejavuserif": f"{FONTDIR}/dejavu/DejaVuSerif.ttf",
    "libsans": f"{FONTDIR}/liberation/LiberationSans-Regular.ttf",
    "libserif_i": f"{FONTDIR}/liberation/LiberationSerif-Italic.ttf",
    "carlito_b": f"{FONTDIR}/crosextra/Carlito-Bold.ttf",
    "wqy": f"{FONTDIR}/wqy/wqy-zenhei.ttc",
}
TTF = {k: v for k, v in TTF.items() if os.path.exists(v)}
BASE14 = ["helv", "hebo", "heit", "hebi", "tiro", "tibo", "tiit", "cour", "cobo"]
W = ("security control policy asset risk management access incident response supplier network data "
     "protection monitoring governance audit evidence maturity assessment requirement implementation "
     "the of and to in for is on with as by be are this that from").split()
CYR = "защита данных сеть управление риск политика контроль аудит".split()
GRK = "ασφάλεια δεδομένα δίκτυο έλεγχος πολιτική κίνδυνος".split()
CJK = ["信息安全", "风险管理", "访问控制", "数据保护", "事件响应"]
BULLETS = ["•", "-", "*", "▪", "1.", "a)", "(i)", "–", "o"]


def words(r, n, pool=W):
    return " ".join(r.choice(pool) for _ in range(n))


def sentence(r, n):
    s = words(r, n)
    if r.random() < 0.3:
        s += f" {r.randint(1, 9999)}"
    if r.random() < 0.15:
        s += f" {r.randint(1, 99)}.{r.randint(0, 99):02d}%"
    return s.capitalize() + "."


def page_story(doc, r):
    """HTML story: headings, paragraphs, lists, tables, 1-3 columns."""
    parts = []
    for s in range(r.randint(2, 5)):
        h = r.choice(["h1", "h2", "h3", "h4"])
        parts.append(f"<{h}>{r.randint(1,9)}.{r.randint(1,9)} {words(r, r.randint(2,6)).title()}</{h}>")
        for _ in range(r.randint(1, 3)):
            fam = r.choice(["sans-serif", "serif", "monospace"])
            fs = r.choice([7, 8, 9, 10, 10, 11, 12, 14])
            al = r.choice(["left", "left", "justify", "center", "right"])
            extra = ""
            if r.random() < 0.4:
                extra += f" <b>{words(r,3)}</b>"
            if r.random() < 0.3:
                extra += f" <i>{words(r,3)}</i>"
            if r.random() < 0.25:
                extra += f" <u>{words(r,2)}</u>"
            if r.random() < 0.15:
                extra += f" <sup>{r.randint(1,9)}</sup>"
            parts.append(f"<p style='font-family:{fam};font-size:{fs}px;text-align:{al};"
                         f"text-indent:{r.choice([0,0,12,20])}px'>{sentence(r, r.randint(5,80))}{extra}</p>")
        k = r.random()
        if k < 0.3:
            tag = r.choice(["ul", "ol"])
            parts.append(f"<{tag}>" + "".join(f"<li>{sentence(r, r.randint(3,25))}</li>" for _ in range(r.randint(2,6))) + f"</{tag}>")
        elif k < 0.55:
            border = r.choice(["1", "0"])
            ncol = r.randint(2, 5)
            rows = [f"<tr>" + "".join(f"<th>{words(r,1).title()}</th>" for _ in range(ncol)) + "</tr>"]
            for _ in range(r.randint(2, 9)):
                rows.append("<tr>" + "".join(
                    f"<td>{r.choice([str(r.randint(0,99999)), words(r, r.randint(1,6)), f'{r.random()*100:.2f}'])}</td>"
                    for _ in range(ncol)) + "</tr>")
            parts.append(f"<table border='{border}' style='border-collapse:collapse'>{''.join(rows)}</table>")
    story = pymupdf.Story(html="\n".join(parts))
    rect = doc[-1].rect if len(doc) else pymupdf.paper_rect("a4")
    mb = r.choice([36, 50, 72])
    ncols = r.choice([1, 1, 2, 3])
    page_rect = pymupdf.paper_rect(r.choice(["a4", "letter"]))
    if r.random() < 0.1:
        page_rect = pymupdf.paper_rect("a4-l")
    colw = (page_rect.width - 2 * mb - (ncols - 1) * 18) / ncols
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    dev = writer.begin_page(page_rect)
    for c in range(ncols):
        x0 = mb + c * (colw + 18)
        more, _ = story.place(pymupdf.Rect(x0, mb + 30, x0 + colw, page_rect.height - mb - 30))
        story.draw(dev)
        if not more:
            break
    writer.end_page()
    writer.close()
    src = pymupdf.open("pdf", buf.getvalue())
    doc.insert_pdf(src)
    return doc[-1]


def add_header_footer(page, r):
    w, h = page.rect.width, page.rect.height
    fs = r.choice([7, 8, 9])
    page.insert_text((40, 25), f"{words(r,3).title()} - Report {r.randint(1,50)}", fontsize=fs, fontname=r.choice(BASE14))
    t = f"Page {r.randint(1,200)} of {r.randint(200,400)}"
    tl = pymupdf.get_text_length(t, fontsize=fs)
    page.insert_text(((w - tl) / 2 if r.random() < 0.5 else w - 40 - tl, h - 20), t, fontsize=fs)
    if r.random() < 0.5:
        page.draw_line((40, 30), (w - 40, 30), width=r.choice([0.5, 1]))


def page_freeform(doc, r):
    """insert_text based: varied fonts, bullets, rotated text, invisible text, rules, rects, images."""
    page = doc.new_page(width=r.choice([595, 612, 842]), height=r.choice([842, 792, 595]))
    w, h = page.rect.width, page.rect.height
    fonts = {}
    for k, path in TTF.items():
        if r.random() < 0.5:
            try:
                page.insert_font(fontname=k, fontfile=path)
                fonts[k] = path
            except Exception:
                pass
    y = r.uniform(40, 90)
    x0 = r.choice([36, 50, 72, 90])
    while y < h - 60:
        kind = r.random()
        fs = r.choice([6, 8, 9, 10, 10, 11, 12, 14, 18, 24])
        fn = r.choice(BASE14 + list(fonts))
        pool = W
        if fn == "wqy":
            pool = CJK
        elif fn.startswith("dejavu") and r.random() < 0.5:
            pool = r.choice([CYR, GRK])
        ox = x0 + r.choice([0, 0, 0, 10, 20, 36])
        if kind < 0.12:  # bullets list
            b = r.choice(BULLETS)
            for i in range(r.randint(2, 5)):
                bb = b if b not in ("1.", "a)") else (f"{i+1}." if b == "1." else f"{chr(97+i)})")
                page.insert_text((ox, y), bb, fontsize=fs, fontname="helv" if not b.startswith("•") else (fn if fn in fonts else "helv"))
                page.insert_text((ox + fs * 1.5, y), words(r, r.randint(2, 12), pool), fontsize=fs, fontname=fn)
                y += fs * r.choice([1.2, 1.4, 1.6])
        elif kind < 0.2:  # rotated text
            rot = r.choice([90, 270, 180])
            try:
                page.insert_text((ox + r.uniform(0, 300), y + 60), words(r, 4, pool), fontsize=fs, fontname=fn, rotate=rot)
            except Exception:
                pass
            y += fs * 2
        elif kind < 0.27:  # image
            iw, ih = r.randint(20, 200), r.randint(20, 150)
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), 0)
            pix.set_rect(pix.irect, (r.randint(0,255), r.randint(0,255), r.randint(0,255)))
            rect = pymupdf.Rect(ox, y, min(ox + iw, w - 20), y + ih)
            page.insert_image(rect, pixmap=pix)
            if r.random() < 0.5:
                page.insert_text((ox, rect.y1 + fs + 2), "Figure " + str(r.randint(1, 9)) + ": " + words(r, 5), fontsize=max(6, fs - 2), fontname=fn)
                y += fs + 2
            y += ih + 8
        elif kind < 0.35:  # boxed / shaded region with text (rafts)
            bh = r.randint(30, 120)
            rect = pymupdf.Rect(ox - 4, y, w - x0 + 4, y + bh)
            page.draw_rect(rect, color=r.choice([None, (0, 0, 0)]), fill=r.choice([None, (0.9, 0.9, 0.95), (0.8, 1, 0.8)]), width=0.8)
            yy = y + fs + 4
            while yy < y + bh - 4:
                page.insert_text((ox + 4, yy), words(r, r.randint(3, 10), pool), fontsize=min(fs, 12), fontname=fn)
                yy += min(fs, 12) * 1.3
            y += bh + 10
        elif kind < 0.43:  # grid table drawn with lines
            nr, nc = r.randint(2, 7), r.randint(2, 5)
            cw = (w - 2 * x0) / nc
            rh = fs * r.choice([1.5, 2, 2.5])
            lines = r.random() < 0.7
            for i in range(nr + 1):
                if lines:
                    page.draw_line((x0, y + i * rh), (x0 + nc * cw, y + i * rh), width=0.5)
            for j in range(nc + 1):
                if lines and r.random() < 0.8:
                    page.draw_line((x0 + j * cw, y), (x0 + j * cw, y + nr * rh), width=0.5)
            for i in range(nr):
                for j in range(nc):
                    if r.random() < 0.9:
                        t = r.choice([str(r.randint(0, 9999)), words(r, r.randint(1, 3), pool), f"{r.random()*1000:.1f}"])
                        tl = pymupdf.get_text_length(t, fontsize=fs) if fn in BASE14 else 0
                        xx = x0 + j * cw + 3
                        if r.random() < 0.3 and tl:
                            xx = x0 + (j + 1) * cw - 3 - tl
                        page.insert_text((xx, y + i * rh + rh * 0.7), t, fontsize=fs, fontname=fn)
            y += nr * rh + 12
        elif kind < 0.47:  # invisible text (render mode 3) or white text
            tw = pymupdf.TextWriter(page.rect)
            tw.append((ox, y), words(r, 6), fontsize=fs)
            tw.write_text(page, render_mode=3 if r.random() < 0.7 else 0, color=(1, 1, 1) if r.random() < 0.5 else None)
            y += fs * 1.5
        elif kind < 0.52:  # underlined (drawn line) text / hr
            t = words(r, r.randint(2, 6), pool)
            page.insert_text((ox, y), t, fontsize=fs, fontname=fn)
            if fn in BASE14:
                tl = pymupdf.get_text_length(t, fontname=fn, fontsize=fs)
                page.draw_line((ox, y + 1.5), (ox + tl, y + 1.5), width=0.6)
            y += fs * 1.6
        elif kind < 0.58:  # two text items on the same line (label: value), right aligned numbers
            t1 = words(r, 2).title() + ":"
            page.insert_text((ox, y), t1, fontsize=fs, fontname=fn)
            t2 = f"{r.randint(0, 999999):,}"
            tl = pymupdf.get_text_length(t2, fontsize=fs)
            page.insert_text((w - x0 - tl, y), t2, fontsize=fs)
            y += fs * 1.4
        elif kind < 0.62:  # centred title
            t = words(r, r.randint(2, 6)).title()
            tl = pymupdf.get_text_length(t, fontname="hebo", fontsize=fs + 4)
            page.insert_text(((w - tl) / 2, y + fs), t, fontsize=fs + 4, fontname="hebo")
            y += fs * 2.5
        elif kind < 0.66:  # textbox with alignment
            rect = pymupdf.Rect(ox, y, w - x0, y + fs * 6)
            try:
                page.insert_textbox(rect, sentence(r, r.randint(10, 40)), fontsize=fs, fontname=fn if fn in BASE14 else "helv",
                                    align=r.choice([0, 1, 2, 3]))
            except Exception:
                pass
            y += fs * 6.5
        else:  # paragraph of lines, ragged
            n = r.randint(1, 6)
            ls = r.choice([1.1, 1.2, 1.3, 1.5, 2.0])
            for i in range(n):
                xi = ox + (r.choice([0, 15]) if i == 0 else 0)
                page.insert_text((xi, y), words(r, r.randint(3, 14) if i < n - 1 else r.randint(1, 6), pool), fontsize=fs, fontname=fn)
                y += fs * ls
            y += fs * r.choice([0.3, 0.8, 1.5])
    if r.random() < 0.5:
        add_header_footer(page, r)
    if r.random() < 0.2:  # sidebar vertical rule
        page.draw_line((w / 2, 40), (w / 2, h - 40), width=0.5)
    if r.random() < 0.1:  # full-page white fill underlay
        page.draw_rect(page.rect, fill=(1, 1, 1), overlay=False)
    return page


def page_htmlbox(doc, r):
    page = doc.new_page()
    w, h = page.rect.width, page.rect.height
    y = 50
    for _ in range(r.randint(3, 8)):
        hh = r.randint(40, 160)
        rect = pymupdf.Rect(r.choice([40, 60, 300]), y, r.choice([290, 400, 555]), y + hh)
        if rect.x1 <= rect.x0 + 40:
            rect.x1 = rect.x0 + 200
        html = f"<p style='font-size:{r.choice([8,9,10,11,13])}px'>{sentence(r, r.randint(5, 50))}"
        if r.random() < 0.4:
            html += f" <b>{words(r,4)}</b> {r.randint(10,999)} <span style='color:red'>{words(r,3)}</span>"
        html += "</p>"
        try:
            page.insert_htmlbox(rect, html, rotate=r.choice([0, 0, 0, 0, 90]))
        except Exception:
            pass
        y += hh + r.choice([2, 10, 30])
        if y > h - 100:
            break
    return page


def page_empty_ish(doc, r):
    page = doc.new_page()
    if r.random() < 0.5:
        page.draw_rect(pymupdf.Rect(100, 100, 400, 300), color=(0, 0, 0), width=2)
    if r.random() < 0.5:
        page.insert_text((300, 420), str(r.randint(1, 99)), fontsize=10)
    return page


def make(seed, out):
    r = random.Random(seed)
    doc = pymupdf.open()
    for _ in range(r.randint(1, 4)):
        k = r.random()
        if k < 0.4:
            page_story(doc, r)
            if r.random() < 0.4:
                add_header_footer(doc[-1], r)
        elif k < 0.85:
            page_freeform(doc, r)
        elif k < 0.95:
            page_htmlbox(doc, r)
        else:
            page_empty_ish(doc, r)
    doc.set_metadata({"producer": "corpus-gen", "creator": "corpus-gen", "creationDate": "", "modDate": ""})
    doc.save(os.path.join(out, f"s{seed:05d}.pdf"), garbage=3, deflate=True, no_new_id=True)


if __name__ == "__main__":
    out, a, b = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    os.makedirs(out, exist_ok=True)
    for s in range(a, b):
        make(s, out)

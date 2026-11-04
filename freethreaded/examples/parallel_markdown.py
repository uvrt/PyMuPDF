"""pymupdf4llm.to_markdown in parallel threads on free-threaded Python 3.15t.

On this build pymupdf.layout gives each thread its own layout model (created on the thread's
first page, about 20 MB of ONNX sessions each) and pymupdf4llm skips its _LAYOUT_LOCK, so no
setup is needed. Set PYMUPDF_LAYOUT_PER_THREAD=0 to share one model behind the lock instead.

Rules:
- one Document (and its TextPages) per thread; never share them across threads;
- optionally MUPDF_indep_ctx=1, so threads don't contend on MuPDF's shared allocation lock;
  it speeds up rendering and text extraction, and matters little for to_markdown.

usage: python parallel_markdown.py FILE.pdf [FILE.pdf ...]
"""

import sys
from concurrent.futures import ThreadPoolExecutor

import pymupdf
import pymupdf.layout  # noqa: F401 -- activates the layout analyzer
import pymupdf4llm


def convert(path):
    with pymupdf.open(path) as doc:
        return pymupdf4llm.to_markdown(doc, write_images=False, show_progress=False)


if __name__ == "__main__":
    with ThreadPoolExecutor(4) as pool:
        for path, md in zip(sys.argv[1:], pool.map(convert, sys.argv[1:])):
            print(f"{path}: {len(md)} characters")
    print("GIL enabled:", sys._is_gil_enabled(), "| model per thread:", pymupdf._get_layout_per_thread)

"""Shared helpers: stext flags identical to pymupdf.layout.pymupdf_util_base.extract_base_elements."""
import pymupdf

STEXT_FLAGS = (pymupdf.TEXT_PRESERVE_IMAGES | pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES
               | pymupdf.TEXT_ACCURATE_BBOXES | pymupdf.TEXT_COLLECT_VECTORS | pymupdf.TEXT_COLLECT_STYLES
               | pymupdf.TEXT_SEGMENT | pymupdf.TEXT_PARAGRAPH_BREAK | pymupdf.TEXT_COLLECT_STRUCTURE
               | pymupdf.TEXT_TABLE_HUNT | pymupdf.TEXT_LAZY_VECTORS | pymupdf.TEXT_CLIP | pymupdf.TEXT_FUZZY_VECTORS)


def textpage(page):
    return page.get_textpage(flags=STEXT_FLAGS)


def page_numbers(doc):
    """Pages to process: all, or the first $MAX_PAGES (for long real-world documents)."""
    import os
    n = int(os.environ.get("MAX_PAGES", "0"))
    return list(range(min(n, doc.page_count))) if n > 0 else None

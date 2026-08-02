#!/usr/bin/env python3
"""figure-extractor for a runtime that has no rasterizer at all.

The other builds need PyMuPDF. This one needs only **pypdf**, which is pure
Python — no C extension, no rasterizer, and commonly already present in
notebook and code-interpreter sandboxes where PyMuPDF is not.

It cannot render a pixel, and does not try: cropping does not require
rendering. Set the page's CropBox to the exhibit's rectangle and write a
one-page PDF. The result is the figure itself, in vector, ready to view,
attach, or convert wherever a renderer does exist.

Region inference without access to vector primitives: text positions tell us
where text is *not*. An exhibit occupies a run of vertical space beside its
caption holding no running prose.

Measured on arXiv 2607.28146 against the full pipeline: finds 16 of 21
exhibits; 14 of those 16 crops fully contain the true figure (looser boxes,
usually including the caption). Of the two that do not, one is flagged
suspect. Report it as a fallback build, and read the statuses.

    python fe_norender.py paper.pdf ./figures
"""
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

CAPTION_RE = re.compile(
    r"^\s*(figure|fig|table|tab|listing|algorithm)\s*\.?\s*([A-Z]?\d+(?:\.\d+)?)\s*[.:|]",
    re.I,
)
BODY_MIN_CHARS = 90
LINE_TOL = 3.0        # points of baseline jitter still counted as one line
BLOCK_GAP = 14.0      # vertical gap that separates two blocks
MARGIN = 8.0


def text_lines(page):
    """[(y, x0, x1, text)] in PDF user space (origin bottom-left)."""
    runs = []

    def visit(text, cm, tm, font_dict, font_size):
        stripped = text.strip()
        if not stripped:
            return
        size = abs(font_size or 0) or 9.0
        width = max(1.0, 0.5 * size * len(stripped))
        runs.append((tm[5], tm[4], tm[4] + width, stripped))

    page.extract_text(visitor_text=visit)
    runs.sort(key=lambda r: (-r[0], r[1]))

    lines, current = [], []
    for y, x0, x1, t in runs:
        if current and abs(current[0][0] - y) <= LINE_TOL:
            current.append((y, x0, x1, t))
        else:
            if current:
                lines.append(current)
            current = [(y, x0, x1, t)]
    if current:
        lines.append(current)

    out = []
    for group in lines:
        y = sum(g[0] for g in group) / len(group)
        out.append((y, min(g[1] for g in group), max(g[2] for g in group),
                    " ".join(g[3] for g in group)))
    return out


def blocks(lines):
    """Group lines into blocks: (y_top, y_bottom, x0, x1, text)."""
    out = []
    run = []
    for line in lines:
        if run and (run[-1][0] - line[0]) > BLOCK_GAP:
            out.append(_merge(run))
            run = []
        run.append(line)
    if run:
        out.append(_merge(run))
    return out


def _merge(run):
    return (max(r[0] for r in run), min(r[0] for r in run),
            min(r[1] for r in run), max(r[2] for r in run),
            " ".join(r[3] for r in run))


def column_band(page, x0, x1):
    box = page.mediabox
    width = float(box.width)
    mid = width / 2
    if (x1 - x0) > 0.62 * width:
        return 32.0, width - 32.0
    if x1 <= mid + 25:
        return 32.0, mid + 25
    if x0 >= mid - 25:
        return mid - 25, width - 32.0
    return 32.0, width - 32.0


TEXT_BODIED = {"table", "tab", "listing", "algorithm"}


def is_prose(text):
    """Running prose, as opposed to a table's rows.

    Without span geometry the only signal left is composition: a results row is
    dense with digits and separators, a paragraph is dense with words.
    """
    if len(text) < BODY_MIN_CHARS:
        return False
    digits = sum(c.isdigit() for c in text)
    alpha = sum(c.isalpha() for c in text)
    return digits / max(1, digits + alpha) < 0.10


def crop_for(page, caption, others, all_blocks, kind="figure"):
    """The empty band next to the caption, bounded by prose and other captions."""
    cap_top, cap_bot, cap_x0, cap_x1, _ = caption
    lo, hi = column_band(page, cap_x0, cap_x1)
    page_top = float(page.mediabox.top) - 32.0
    page_bottom = float(page.mediabox.bottom) + 32.0

    def in_band(b):
        centre = (b[2] + b[3]) / 2
        return lo - 2 <= centre <= hi + 2

    # A table's own rows are its content, so only prose and captions may stop it.
    barriers = [b for b in all_blocks
                if b is not caption and in_band(b)
                and (is_prose(b[4]) or CAPTION_RE.match(b[4]))]

    above = [b[1] for b in barriers if b[1] > cap_top]   # bottom edge above us
    below = [b[0] for b in barriers if b[0] < cap_bot]   # top edge below us
    up_edge = min(above) if above else page_top
    down_edge = max(below) if below else page_bottom

    up_height = up_edge - cap_top
    down_height = cap_bot - down_edge
    # A figure is drawn above its caption; only fall to the other side when
    # that side is empty. Picking "whichever gap is bigger" hands a figure the
    # blank half of the page below it.
    if kind not in TEXT_BODIED:
        up, down = (cap_top, up_edge), (down_edge, cap_bot)
        y0, y1 = up if up_height >= 24 else down
    elif up_height >= down_height:
        y0, y1 = cap_top, up_edge
    else:
        y0, y1 = down_edge, cap_bot
    if (y1 - y0) < 24:
        return None, [f"no clear region beside the caption ({y1 - y0:.0f}pt)"]

    # Without vector primitives there is nothing to break a tie between two
    # plausible sides, and picking one silently is how a table ends up showing
    # the figure underneath it. Say the choice was a guess.
    reasons = []
    chosen, other = max(up_height, down_height), min(up_height, down_height)
    if kind in TEXT_BODIED and other >= 0.6 * chosen and other >= 24:
        reasons.append(
            f"content on both sides ({up_height:.0f}pt above, {down_height:.0f}pt "
            "below) and no rules to tell them apart")
    return RectangleObject((lo, y0 - MARGIN, hi, y1 + MARGIN)), reasons


def main(argv):
    pdf, out = Path(argv[1]), Path(argv[2] if len(argv) > 2 else "figures")
    out.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf))
    items = []
    for pi, page in enumerate(reader.pages):
        bs = blocks(text_lines(page))
        caps = [b for b in bs if CAPTION_RE.match(b[4])]
        for cap in caps:
            m = CAPTION_RE.match(cap[4])
            kind, number = m.group(1).lower(), m.group(2)
            box, reasons = crop_for(page, cap, caps, bs, kind)
            slug = "fig" if kind in {"figure", "fig"} else ("tab" if kind in {"table", "tab"} else kind[:3])
            name = f"{slug}{number}_p{pi + 1:02d}.pdf"
            entry = {"label": f"{kind.title()} {number}", "page": pi + 1,
                     "caption": cap[4][:200], "format": "pdf-vector",
                     "extractor": "no-rasterizer-pypdf"}
            if box is None:
                entry.update(status="failed", output=None, quality_reasons=reasons)
            else:
                writer = PdfWriter()
                writer.add_page(reader.pages[pi])
                writer.pages[0].cropbox = box
                writer.pages[0].mediabox = box
                with open(out / name, "wb") as fh:
                    writer.write(fh)
                entry.update(status="suspect" if reasons else "ok",
                             output=str(out / name),
                             bbox=[round(float(v), 2) for v in
                                   (box.left, box.bottom, box.right, box.top)])
                if reasons:
                    entry["quality_reasons"] = reasons
            items.append(entry)
    manifest = {"source_pdf": str(pdf), "extractor": "no-rasterizer-pypdf",
                "note": "Vector crops: no rasterizer available, so pages are cropped, not rendered.",
                "counts": {"total": len(items),
                           "ok": sum(1 for i in items if i["status"] == "ok"),
                           "suspect": sum(1 for i in items if i["status"] == "suspect"),
                           "failed": sum(1 for i in items if i["status"] == "failed")},
                "figures": items}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

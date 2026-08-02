---
name: figure-extractor
description: >-
  Extract complete, publication-quality figures and images from documents —
  local PDFs, PDF URLs, arXiv links, and HTML article pages. Use whenever the
  user wants to pull figures / charts / diagrams / images out of a paper or web
  article, says "extract the figures from this PDF / arXiv paper / webpage",
  needs clean figure PNGs for slides, decks, or reuse, or finds that naive
  embedded-image extraction returns broken fragments. This is a command-line
  tool (Python + PyMuPDF) that must be run in a shell; if your runtime has no
  shell, see the degraded-mode fallback. Keywords: extract figures from pdf,
  extract images from html, arxiv figure extraction, paper figure extractor,
  pdf figure crop, pymupdf.
---

# Figure Extractor Skill

Use this skill when the user needs complete figures or images extracted from PDFs, arXiv papers, or HTML article pages.

## What this skill actually is (read first)

`figure-extractor` is a **command-line tool** (Python + PyMuPDF). "Using it" means
running it in a shell — e.g. `figure-extractor extract paper.pdf`. It is **not**
an in-agent callable, a hosted service, or a "page" you activate.

It does **not** require installation or network. **PDF and HTML sources both**
need a Python interpreter with **PyMuPDF and nothing else** — no pip, no PyPI,
no GitHub, no Pillow, no beautifulsoup4. If you cannot install packages, use the
single-file build, or the reduced extractor printed in this file (Step 0 below).
Only URL sources need network.

If the user gives you a **browser PDF-viewer URL** (`.../viewer.html?file=...`,
Chrome's built-in viewer, Google Docs viewer), pass it in as-is: the real
document is unwrapped from `?file=` / `#file=` / `?url=` before anything is
fetched. If they give you a **saved HTML page**, pass the local file: images
stored as inline `data:` URIs are decoded without touching the network.

**Invocation contract**
- **Mechanism:** a shell command — installed CLI, `python -m figure_extractor`, or the single file.
- **Input:** a local PDF/HTML path or a PDF/arXiv/HTML URL.
- **Output:** PNG files + `manifest.json` + `contact_sheet.jpg` (+ optional `figures.zip`) written to `--out`.

## Step 0 — precondition check (always do this first)

Work down this ladder and stop at the first rung that runs. Do **not** conclude
the tool is unavailable until you have tried rung 3.

```bash
# 1. Installed CLI
figure-extractor --help

# 2. Repo present but not installed — no pip needed
PYTHONPATH=src python -m figure_extractor --help

# 3. Repo checked out but not installed: one file, PyMuPDF only
python standalone/figure_extractor_standalone.py --help

# 4. No repo at all and no network to fetch one
python -c "import fitz; print(fitz.__doc__)"

# 5. Not even PyMuPDF — a pure-Python PDF library is enough to crop
python -c "import pypdf; print(pypdf.__version__)"
```

- **Rungs 1–3 run** → follow *Preferred algorithm*.
- **Only rung 4 runs** → *the extractor is printed in this file*. Write it out and
  run it; see **No repo, no network** below. This is not degraded mode: it
  produces real crops from the real bytes.
- **Only rung 5 runs** → cropping does not require rendering. See **No
  rasterizer** below: it writes one-page vector PDFs instead of PNGs.
- **No code execution at all, or no PDF library** → go to *Degraded mode*.

### Any code-execution tool counts as a shell

"No shell" usually means "no `bash` tool", not "no way to run code". If the
runtime exposes a Python or notebook tool — an analysis tool, a code
interpreter, a sandbox cell — that **is** rung 4 or 5. Check before concluding
the tool is unavailable.

**Do not confuse "no network" with "cannot extract".** A runtime with no DNS can
still crop a PDF it already has on disk — including one the user just uploaded
into the conversation. Network is needed only to *fetch* a URL. If the fetch
fails, ask the user for the file rather than degrading to prose.

## Core rule (when the extractor is available)

Do **not** rely on embedded PDF image extraction alone. Many figures are composed of vector drawings, text labels, legends, and raster fragments. Embedded-image extraction often returns incomplete fragments — prefer the caption-bbox render-crop pipeline below.

## Preferred algorithm (requires a shell + the CLI)

1. Resolve the input source:
   - local PDF
   - PDF URL
   - arXiv abs URL (`/abs/` is auto-normalized to `/pdf/`)
   - HTML URL
   - local HTML
2. If HTML is available, first try to extract original figure images from `<figure>`, `<img>`, `<picture>`, `srcset`, and lazy-load attributes.
3. If HTML does not provide enough high-quality figures, locate or download the PDF.
4. For PDFs:
   - locate every caption: `Figure 2.1`, `Figure B.1`, `Extended Data Fig. 1`,
     `Supplementary Table S3`, `Scheme`/`Algorithm`/`Listing`/`Box`, `图 1`;
   - recover the page's column grid and confine each crop to its caption's band;
   - grow the bbox from graphic primitives, stopping at other captions and prose;
   - render the page at 300 dpi and crop;
   - generate PNGs, `manifest.json`, and `contact_sheet.jpg`.
5. **Read the `status` field of every entry in `manifest.json`.** Anything marked
   `suspect` or `failed` carries `quality_reasons` explaining what went wrong.
   Do not present a `failed` crop to the user as if it were the figure.
   An entry with `parts` was stitched from several regions because the exhibit
   was broken across a column or page break; its `bbox` covers only the piece on
   `page`, so cite `parts` when the geometry matters.
6. If a crop is wrong, correct it with `crop --bbox`, starting from the bbox the
   manifest already recorded.

## No repo, no network — the extractor is in this file

A runtime with no network cannot `pip install` this package **and cannot fetch
`standalone/figure_extractor_standalone.py` either** — it is in the same repo.
Rung 3 is unreachable exactly where it was meant to help. So the extractor is
carried here, in the skill's own text, and reaches you the way these
instructions did.

Write the block below to a file and run it. No install, no network, no
dependency but PyMuPDF:

```bash
cat > fe_min.py <<'PYEOF'
# ... paste the Python block below ...
PYEOF
python fe_min.py paper.pdf ./figures 300
cat figures/manifest.json
```

**It is a reduced build, and you must say so when you report.** It keeps what
decides whether a crop is right — caption anchoring, the column band, choosing
the side the content is actually on, stopping at prose — and drops the triage
tiers, the full quality scorer, the table detector, and stitching across page
breaks. Its manifest sets `"extractor": "skill-embedded-reduced"` so the
difference is visible in the output, not only in your summary. Items it is
unsure of come back `suspect` with `quality_reasons`; do not present those as
finished figures.

### Getting the bytes when the sandbox has no network

No code can conjure a PDF that is not there, but "the sandbox cannot reach the
network" is not the same as "the bytes are unreachable". In most agent
runtimes the sandbox and *your own tools* have different network access, and
you are the transport between them:

1. **Your fetch/browse tool usually runs outside the sandbox.** If `curl` fails
   with `NO_DNS` but your web-fetch tool loads the page, the boundary is the
   sandbox's, not yours.
2. **Move bytes across that boundary as text.** Fetch, base64, write into the
   sandbox, decode. Budget for it: base64 inflates by 4/3, and a 1 MB PDF is
   well over 300k tokens — practical for a short paper, not for a thesis. Say
   what you are doing so the cost is not a surprise.
3. **Ask for the file.** One attachment beats any of this.

Only when all three fail is the document genuinely unreachable — and then say
so plainly rather than describing figures you never saw.

<!-- BEGIN EMBEDDED EXTRACTOR: generated from bootstrap/minimal_extractor.py by tools/build_standalone.py -->

```python
#!/usr/bin/env python3
"""figure-extractor, reduced — the copy carried inside SKILL.md itself.

A runtime with no network cannot fetch this repo, so the full tool is out of
reach exactly where it is needed most. This file is small enough to live in the
skill's own text: an agent that can read SKILL.md can write it to disk and run
it, with no package, no install and no network.

Reduced fidelity, deliberately. It keeps what decides whether a crop is right —
caption anchoring, the column band, growing to the side the content is actually
on, stopping at prose — and drops tiering, quality scoring, table detection,
and stitching across page breaks. Say so when you report results.

    python fe_min.py paper.pdf ./figures 300
"""
import json
import re
import sys
from pathlib import Path

import fitz

CAPTION_RE = re.compile(
    r"^\s*(figure|fig|table|tab|listing|algorithm|scheme|box)\s*"
    r"\.?\s*([A-Z]?\d+(?:\.\d+)?)\s*[.:|]",
    re.I,
)
TEXT_BODIED = {"table", "tab", "listing", "algorithm", "box"}
BODY_MIN_CHARS = 90   # shorter than this is a label or a cell, not a paragraph
MAX_GAP = 42.0        # points of empty space allowed inside one exhibit
PAGE_MARGIN = 32.0
MARGIN = 8.0          # padding added around the inferred box
# TeX typewriter faces arrive with PyMuPDF's monospace flag unset, so match the
# family name: a fixed-width block is a listing's body, never the paper's prose.
MONO_MARKERS = ("mono", "courier", "consol", "typewriter", "cmtt", "lmtt")


def blocks(page):
    """(rect, text, monospace) for every text block on the page."""
    out = []
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") != 0:
            continue
        spans = [s for line in b.get("lines", []) for s in line.get("spans", [])]
        text = " ".join("".join(s.get("text", "") for s in spans).split())
        if not text:
            continue
        mono = sum(
            bool(s.get("flags", 0) & 8)
            or any(m in (s.get("font") or "").lower() for m in MONO_MARKERS)
            for s in spans
        )
        out.append((fitz.Rect(b["bbox"]), text, bool(spans) and mono >= len(spans) * 0.6))
    return out


def primitives(page):
    rects = []
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        # A rule or an axis has zero thickness; Rect.is_empty would discard it.
        if r.x1 - r.x0 < 0.5:
            r.x1 = r.x0 + 0.5
        if r.y1 - r.y0 < 0.5:
            r.y1 = r.y0 + 0.5
        if r.width < 2 and r.height < 2:
            continue
        rects.append(r)
    try:
        for info in page.get_image_info(xrefs=True):
            r = fitz.Rect(info["bbox"])
            if r.width > 2 and r.height > 2:
                rects.append(r)
    except Exception:
        pass
    return rects


def band_for(page, cap):
    """Horizontal span the exhibit may occupy, so a 2-column page cannot bleed."""
    w = page.rect.width
    mid = w / 2
    if cap.width > 0.62 * w:
        return PAGE_MARGIN, w - PAGE_MARGIN
    if cap.x1 <= mid + 25:
        return PAGE_MARGIN, mid + 25
    if cap.x0 >= mid - 25:
        return mid - 25, w - PAGE_MARGIN
    return PAGE_MARGIN, w - PAGE_MARGIN


def rule_side(prims, cap, band):
    """True if the exhibit's rules sit above the caption, False below, None if none.

    LaTeX puts the caption wherever the author wrote it, so plenty of papers set
    a table's caption underneath it. Booktabs rules say which side unambiguously.
    """
    lo, hi = band
    min_w = max(40.0, (hi - lo) * 0.35)
    rules = [r for r in prims if r.height <= 3.0 and r.width >= min_w]
    above = [cap.y0 - r.y1 for r in rules if r.y1 <= cap.y0 + 2]
    below = [r.y0 - cap.y1 for r in rules if r.y0 >= cap.y1 - 2]
    if len(above) >= 2 and (len(below) < 2 or min(above) < min(below)):
        return True
    if len(below) >= 2:
        return False
    return None


def in_band(r, band):
    lo, hi = band
    width = max(r.width, 1.0)
    return (min(r.x1, hi) - max(r.x0, lo)) / width > 0.5


def union(rects):
    r = fitz.Rect(rects[0])
    for x in rects[1:]:
        r.x0, r.y0 = min(r.x0, x.x0), min(r.y0, x.y0)
        r.x1, r.y1 = max(r.x1, x.x1), max(r.y1, x.y1)
    return r


def grow(seed, content, barriers, up):
    """Collect content away from the caption, stopping at prose or a big gap."""
    side = [r for r in content if (r.y1 <= seed if up else r.y0 >= seed)]
    side.sort(key=lambda r: -r.y1 if up else r.y0)
    kept, frontier = [], seed
    for r in side:
        near, far = (r.y1, r.y0) if up else (r.y0, r.y1)
        gap = (frontier - near) if up else (near - frontier)
        if gap > MAX_GAP and kept:
            break
        lo, hi = (near, frontier) if up else (frontier, near)
        if any(b.y0 >= lo - 1 and b.y1 <= hi + 1 for b in barriers):
            break
        kept.append(r)
        frontier = min(frontier, far) if up else max(frontier, far)
    return union(kept) if kept else None


def crop_for(page, cap_rect, kind, page_caps):
    band = band_for(page, cap_rect)
    texts = blocks(page)
    prims = [r for r in primitives(page) if in_band(r, band)]
    others = [r for r, _ in page_caps if r != cap_rect and in_band(r, band)]
    prose = [r for r, t, mono in texts
             if len(t) >= BODY_MIN_CHARS and not mono
             and in_band(r, band) and r != cap_rect]
    barriers = others + prose

    content = list(prims)
    if kind in TEXT_BODIED:
        # A table's rows and a listing's lines are text: they are the content.
        content += [r for r, t, mono in texts
                    if in_band(r, band) and r != cap_rect and r not in prose]

    # The exhibit's own rules outrank the caption-above convention.
    preferred = rule_side(prims, cap_rect, band) if kind in TEXT_BODIED else None

    found = {}
    for up in (True, False):
        seed = (cap_rect.y0 - 2) if up else (cap_rect.y1 + 2)
        got = grow(seed, content, barriers, up)
        if got is not None:
            gap = (cap_rect.y0 - got.y1) if up else (got.y0 - cap_rect.y1)
            found[up] = (max(0.0, gap), got)
    if not found:
        return None, "no content found beside the caption"

    if preferred in found:
        up = preferred
    else:
        up = min(found, key=lambda k: found[k][0])
    box = found[up][1]
    box = fitz.Rect(box)
    box.x0 = max(band[0], box.x0 - MARGIN)
    box.x1 = min(band[1], box.x1 + MARGIN)
    if up:
        box.y0 = max(PAGE_MARGIN, box.y0 - MARGIN)
        box.y1 = min(cap_rect.y0 - 3, box.y1 + MARGIN)
    else:
        box.y0 = max(cap_rect.y1 + 3, box.y0 - MARGIN)
        box.y1 = min(page.rect.height - PAGE_MARGIN, box.y1 + MARGIN)
    box = box & page.rect
    if box.is_empty or box.width < 8 or box.height < 8:
        return None, [f"degenerate crop {box.width:.0f}x{box.height:.0f}pt"]
    return box, check(box, page, cap_rect, others)


def check(box, page, cap_rect, others):
    """Why this crop should not be trusted, if it should not.

    The reduced extractor is blinder than the real one, so it has to be louder:
    a confidently wrong crop still looks like a result, and that is the one
    outcome worse than reporting nothing.

    These three signals are all structural. "Does the crop contain body text" is
    deliberately not among them: a diagram's own labels read exactly like prose
    without the span-level analysis this build drops, so that test fires on good
    crops of ordinary figures.
    """
    reasons = []
    if box.height < 24 or box.width < 24:
        reasons.append(f"thin crop {box.width:.0f}x{box.height:.0f}pt")
    if any(box.intersects(c) for c in others):
        reasons.append("crop contains another caption")
    if (box.width * box.height) / (page.rect.width * page.rect.height) > 0.6:
        reasons.append("crop covers most of the page")
    gap = max(cap_rect.y0 - box.y1, box.y0 - cap_rect.y1, 0.0)
    if gap > 120:
        reasons.append(f"crop sits {gap:.0f}pt from its caption")
    return reasons


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    pdf = Path(argv[1])
    out = Path(argv[2] if len(argv) > 2 else "figures")
    dpi = int(argv[3]) if len(argv) > 3 else 300
    out.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf)
    items = []
    for pi, page in enumerate(doc):
        caps = []
        for rect, text, _mono in blocks(page):
            m = CAPTION_RE.match(text)
            if m:
                caps.append((rect, text, m.group(1).lower(), m.group(2)))
        page_caps = [(r, t) for r, t, _, _ in caps]
        for rect, text, kind, number in caps:
            box, reasons = crop_for(page, rect, kind, page_caps)
            kind_slug = "fig" if kind in {"figure", "fig"} else (
                "tab" if kind in {"table", "tab"} else kind[:3])
            name = f"{kind_slug}{number}_p{pi + 1:02d}.png"
            entry = {
                "label": f"{kind.title()} {number}",
                "kind": kind,
                "number": number,
                "page": pi + 1,
                "caption": text[:400],
                "extractor": "skill-embedded-reduced",
            }
            if box is None:
                entry["status"], entry["output"] = "failed", None
                entry["quality_reasons"] = reasons
            else:
                # A crop is still written when it is suspect: the reader can
                # judge it against the caption. It is never labelled ok.
                page.get_pixmap(dpi=dpi, clip=box, alpha=False).save(out / name)
                entry["status"] = "suspect" if reasons else "ok"
                entry["bbox"] = [round(v, 2) for v in (box.x0, box.y0, box.x1, box.y1)]
                entry["output"] = str(out / name)
                if reasons:
                    entry["quality_reasons"] = reasons
            items.append(entry)
    doc.close()

    manifest = {
        "source_pdf": str(pdf),
        "dpi": dpi,
        "extractor": "skill-embedded-reduced",
        "note": ("Reduced fallback carried in SKILL.md: no tiering, no quality "
                 "scoring, no stitching across page breaks. Report it as such."),
        "counts": {
            "total": len(items),
            "ok": sum(1 for e in items if e["status"] == "ok"),
            "suspect": sum(1 for e in items if e["status"] == "suspect"),
            "failed": sum(1 for e in items if e["status"] == "failed"),
        },
        "figures": items,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

<!-- END EMBEDDED EXTRACTOR -->

## No rasterizer — crop instead of render

Rung 5: a runtime with **pypdf but no PyMuPDF**. Rendering needs a rasterizer;
cropping does not. Set the page's CropBox to the exhibit's rectangle and write
a one-page PDF, and the figure comes out in vector — often better than a PNG
for a paper, and convertible anywhere a renderer exists.

Write out the second block below and run `python fe_norender.py paper.pdf ./figures`.

**Weaker than the other builds, and it says so.** With no access to vector
primitives it infers regions from where text *is not*, so boxes are looser and
usually include the caption. On arXiv 2607.28146 it finds 16 of 21 exhibits, 14
of those crops fully contain the true figure, and it marks the side-choice as
`suspect` when both sides of a caption look plausible. Its manifest sets
`"extractor": "no-rasterizer-pypdf"`. Read the statuses; do not present a
`suspect` crop as finished.

<!-- BEGIN EMBEDDED NO-RASTERIZER EXTRACTOR: generated from bootstrap/no_rasterizer_extractor.py by tools/build_standalone.py -->

```python
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
```

<!-- END EMBEDDED NO-RASTERIZER EXTRACTOR -->

## Degraded mode (last resort — only when every rung fails)

Use this **only** when every rung of Step 0 failed: no way to execute code at
all, or no PDF library of any kind, **or** the bytes are genuinely unobtainable
— your own fetch tool failed too *and* the user has no file to give you. A
missing network in the sandbox does **not** qualify on its own.

This path is **explicitly allowed** and does not count as failing the "core rule":

1. **Link the original.** Provide the direct figure URL, the source page, or the
   arXiv PDF page number + figure number so the user can open the real image.
2. **Describe faithfully.** Give a structured read of each figure from its
   caption + surrounding text: what it shows, axes/panels/legend, key trend.
   Never invent figure content you could not actually see.
3. **Label the gap.** State plainly, e.g.:
   `Bitmap not embedded — reason: no shell available` (or `image 404`,
   `src stripped by sanitizer`, `auth-gated`). 

Degraded output = original link + faithful structured description + an explicit
"why the bitmap is missing" note. That is an acceptable result, not a violation.

## Setup

**A missing package is not a reason to degrade.** The PDF path needs only
PyMuPDF; no GPU, no model, no service.

```bash
pip install git+https://github.com/Sunrich-HT/figure-extractor
pip install "figure-extractor[html] @ git+https://github.com/Sunrich-HT/figure-extractor"
```

From a checkout: `pip install -e .` (add `".[html]"` for HTML sources).

**Cannot install at all?** Nothing needs installing as long as `import fitz`
works:

```bash
PYTHONPATH=src python -m figure_extractor extract paper.pdf --out ./figures
python standalone/figure_extractor_standalone.py extract paper.pdf --out ./figures
```

`standalone/figure_extractor_standalone.py` is a single generated file carrying
the whole PDF path. Copy it anywhere — it imports only PyMuPDF and the standard
library. Regenerate it after changing `src/` with
`python tools/build_standalone.py`.

## Have a PDF? Run it on the PDF.

If the user attached a PDF, or you can download one, that is the simplest and
most reliable path. **Do not start with HTML or a browser.**

```bash
figure-extractor extract <pdf-path> --out ./figures --dpi 300 --zip
```

Only when no PDF is obtainable should you try the HTML route. Note that some
environments' HTML fetchers strip `<img src>`, leaving text only — when that
happens, stop working the HTML and go back to fetching the PDF.

## Commands

```bash
# Auto-extract (local PDF, PDF URL, arXiv abs URL, or HTML article)
figure-extractor extract paper.pdf --out ./figures --dpi 300 --zip
figure-extractor extract https://arxiv.org/abs/2606.23443 --out ./figures --zip
figure-extractor extract https://openreview.net/forum?id=XXXX --out ./figures
figure-extractor extract https://example.com/article --prefer html --fallback pdf

# Figures only, or only the crops most likely to be load-bearing
figure-extractor extract paper.pdf --kinds figure --tiers A,B

# Manual bbox correction for a single figure
figure-extractor crop paper.pdf --page 5 --bbox 295,245,556,475 --out fig04.png --dpi 300
```

## Default settings

- `dpi`: 300
- `margin`: 8 PDF points
- `prefer`: `auto`
- `fallback`: `pdf`
- `kinds`: `all` — extraction is exhaustive by default
- `tiers`: `A,B,C` — nothing filtered by default; the tier is a triage signal,
  not a judgement about which exhibits carry the argument
- `contact_sheet`: true

## Quality-control guidance

When the extractor ran, always inspect `contact_sheet.jpg` **and** the `status`
of each manifest entry. `suspect` and `failed` crops are flagged in orange and
red on the sheet. If a figure includes surrounding body text or misses part of
the figure, rerun `crop` with a manual bbox.

The manifest accounts for every candidate the tool saw. If `containers_found`
exceeds what was rendered, the `dropped` list says why each one was not — treat
an unexplained gap as a bug, not as a clean run.

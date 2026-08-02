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

# 4. No repo at all and no network to fetch one — the only hard requirement
python -c "import fitz; print(fitz.__doc__)"
```

- **Rungs 1–3 run** → follow *Preferred algorithm*.
- **Only rung 4 runs** → *the extractor is printed in this file*. Write it out and
  run it; see **No repo, no network** below. This is not degraded mode: it
  produces real crops from the real bytes.
- **No shell at all, or no Python with PyMuPDF** → go to *Degraded mode*.

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

If you still need the PDF itself, that is a separate problem and no code solves
it: ask the user to attach the file. Network is only needed to *fetch* bytes,
never to crop them.

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

## Degraded mode (last resort — only when even rung 4 fails)

Use this **only** when every rung of Step 0 failed: no shell at all, or no Python
with PyMuPDF, **or** the PDF bytes are genuinely unobtainable (no network *and*
the user has no file to give you; HTML strips `<img>` `src`; images 404; page
behind auth). A missing network alone does **not** qualify — ask for the file.

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

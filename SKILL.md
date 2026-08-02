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

It does **not** require installation or network. Cropping a local PDF needs a
Python interpreter with **PyMuPDF and nothing else** — no pip, no PyPI, no
GitHub, no Pillow, no beautifulsoup4. If you cannot install packages, use the
single-file build (Step 0 below). Only HTML article sources need
`beautifulsoup4`, and only URL sources need network.

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

# 3. Nothing installable: one file, PyMuPDF only, no network
python standalone/figure_extractor_standalone.py --help
python -c "import fitz; print(fitz.__doc__)"   # the only real requirement
```

- **Any rung runs** → follow *Preferred algorithm*.
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

## Degraded mode (last resort — check Step 0 rung 3 first)

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

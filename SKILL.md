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
running its CLI in a shell — e.g. `figure-extractor extract paper.pdf`. It is
**not** an in-agent callable, a hosted service, or a "page" you activate, and it
cannot run inside a runtime that has no shell or cannot install Python packages
(e.g. Notion Agent, browser-only agents).

**Invocation contract**
- **Mechanism:** shell command `figure-extractor <subcommand> ...` (installed via `pip install -e .`).
- **Input:** a local PDF/HTML path or a PDF/arXiv/HTML URL.
- **Output:** PNG files + `manifest.json` + `contact_sheet.jpg` (+ optional `figures.zip`) written to `--out`.

## Step 0 — precondition check (always do this first)

Before you promise figure extraction, verify the tool is actually runnable in
this environment:

```bash
figure-extractor --help     # if this errors, or there is no shell, the tool is UNAVAILABLE
```

- **Available** (command runs) → follow *Preferred algorithm*.
- **Unavailable** (no shell / not installed / sandboxed) → go to *Degraded mode*.
  Not having the tool is **not** a failure and **not** a rule violation — degrade
  gracefully and tell the user what you did.

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
   - locate every caption, including `Figure 2.1`, `Figure B.1`, `Table S3`;
   - recover the page's column grid and confine each crop to its caption's band;
   - grow the bbox from graphic primitives, stopping at other captions and prose;
   - render the page at 300 dpi and crop;
   - generate PNGs, `manifest.json`, and `contact_sheet.jpg`.
5. **Read the `status` field of every entry in `manifest.json`.** Anything marked
   `suspect` or `failed` carries `quality_reasons` explaining what went wrong.
   Do not present a `failed` crop to the user as if it were the figure.
6. If a crop is wrong, correct it with `crop --bbox`, starting from the bbox the
   manifest already recorded.

## Degraded mode (no shell / CLI unavailable / bitmaps unreachable)

Use this when you **cannot** run `figure-extractor` (no shell, no Python/pip,
sandboxed runtime), **or** when you can run nothing that retrieves the actual
bitmap (e.g. the HTML strips `<img>` `src`, arXiv image URLs 404, page behind
auth). This path is **explicitly allowed** and does not count as failing the
"core rule":

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

## Setup (shell environments only)

```bash
pip install -e .          # installs the `figure-extractor` CLI
# or, dependencies only:
pip install -r requirements.txt
```

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
- `kinds`: `figure,table`
- `tiers`: `A,B,C` (use `--tiers A,B` to skip the long tail)
- `contact_sheet`: true

## Quality-control guidance

When the extractor ran, always inspect `contact_sheet.jpg` **and** the `status`
of each manifest entry. `suspect` and `failed` crops are flagged in orange and
red on the sheet. If a figure includes surrounding body text or misses part of
the figure, rerun `crop` with a manual bbox.

The manifest accounts for every candidate the tool saw. If `containers_found`
exceeds what was rendered, the `dropped` list says why each one was not — treat
an unexplained gap as a bug, not as a clean run.

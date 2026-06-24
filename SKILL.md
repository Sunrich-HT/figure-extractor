---
name: figure-extractor
description: >-
  Extract complete, publication-quality figures and images from documents —
  local PDFs, PDF URLs, arXiv links, and HTML article pages. Use whenever the
  user wants to pull figures / charts / diagrams / images out of a paper or web
  article, says "extract the figures from this PDF / arXiv paper / webpage",
  needs clean figure PNGs for slides, decks, or reuse, or finds that naive
  embedded-image extraction returns broken fragments. Handles vector + raster +
  text-label composite figures via caption detection and high-DPI page-crop
  rendering, with a contact sheet for QA and a manual bbox-correction mode.
  Keywords: extract figures from pdf, extract images from html, arxiv figure
  extraction, paper figure extractor, pdf figure crop, pymupdf.
---

# Figure Extractor Skill

Use this skill when the user needs complete figures or images extracted from PDFs, arXiv papers, or HTML article pages.

## Core rule

Do **not** rely on embedded PDF image extraction alone. Many figures are composed of vector drawings, text labels, legends, and raster fragments. Embedded-image extraction often returns incomplete fragments.

## Setup

```bash
pip install -e .          # installs the `figure-extractor` CLI
# or, dependencies only:
pip install -r requirements.txt
```

## Preferred algorithm

1. Resolve the input source:
   - local PDF
   - PDF URL
   - arXiv abs URL (`/abs/` is auto-normalized to `/pdf/`)
   - HTML URL
   - local HTML
2. If HTML is available, first try to extract original figure images from `<figure>`, `<img>`, `<picture>`, `srcset`, and lazy-load attributes.
3. If HTML does not provide enough high-quality figures, locate or download the PDF.
4. For PDFs:
   - locate figure captions such as `Figure 1.`, `Fig. 1`, `FIGURE 1`;
   - infer the figure bbox from drawing/image/text primitives above the caption;
   - render the PDF page at 300 dpi by default;
   - crop the rendered page by the inferred bbox;
   - generate PNGs, `manifest.json`, and `contact_sheet.jpg`.
5. If one figure crop is wrong, use manual bbox correction mode.

## Commands

```bash
# Auto-extract (local PDF, PDF URL, arXiv abs URL, or HTML article)
figure-extractor extract paper.pdf --out ./figures --dpi 300 --zip
figure-extractor extract https://arxiv.org/abs/2606.23443 --out ./figures --zip
figure-extractor extract https://example.com/article --prefer html --fallback pdf

# Manual bbox correction for a single figure
figure-extractor crop paper.pdf --page 5 --bbox 295,245,556,475 --out fig04.png --dpi 300
```

## Default settings

- `dpi`: 300
- `margin`: 8 PDF points
- `prefer`: `auto`
- `fallback`: `pdf`
- `contact_sheet`: true

## Quality-control guidance

Always inspect `contact_sheet.jpg`. If a figure includes surrounding body text or misses part of the figure, rerun `crop` with a manual bbox.

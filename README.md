# figure-extractor

**Extract complete figures _and tables_ from PDF, arXiv, OpenReview, ACL and HTML papers.**
A packaged **AI-agent skill** (works with **Claude Code**, **Codex**, **Kimi**, and any
skill-aware coding agent) plus a standalone `figure-extractor` CLI.

> Also known as: *paper figure extractor*, *pdf figure extractor*, *arxiv figure
> extraction*, *extract figures from pdf*, *extract images from html article*.

Built for research reading, where a figure cropped wrong is worse than one that
is missing — a wrong crop still looks like a result.

```bash
pip install -e .
figure-extractor extract https://arxiv.org/abs/1512.03385 --out ./figures --zip
```

## Sources

| Source | Handling |
|---|---|
| Local PDF / HTML file | direct |
| arXiv `/abs/`, `/pdf/` | normalized to the PDF |
| arXiv `/html/` | HTML path, keeps the original figure assets |
| OpenReview `/forum?id=` | normalized to `/pdf?id=` |
| ACL Anthology landing page | normalized to `.pdf` |
| bioRxiv / medRxiv | normalized to `.full.pdf` |
| Any article URL | `<figure>`, `<img>`, `<picture>`, `srcset`, lazy attrs |

Requests are sent with a browser user agent, and a source that cannot be
retrieved reports **why** — an HTTP 403 says it was refused, rather than being
silently reinterpreted as an HTML page.

## What it does

The key design choice is: **do not rely on embedded PDF image extraction alone.**
Many academic figures are vector drawings, text labels, legends and raster
fragments; embedded-image extraction returns pieces. Instead:

1. **Caption detection** — exhaustive by design, because which exhibits matter
   is a reading judgement, not a retrieval filter. Covers `Figure 1.`,
   `Fig. 12:`, chapter-scoped `Figure 2.1`, appendix `Figure B.1`,
   journal prefixes `Extended Data Fig. 1` and `Supplementary Table S3`,
   Nature's `Fig. 1 | Title` separator, kinds beyond figures and tables
   (`Table`, `Algorithm`, `Scheme`, `Chart`, `Listing`, `Box`, `Exhibit`,
   `Panel`, `Plate`, `Movie`), and CJK labels (`图 1`, `表 2`, `図 1`).
   Journal prefixes are part of an exhibit's identity, so `Extended Data Fig. 1`
   never overwrites `Fig. 1`.
2. **Column-aware bbox inference** — the page's column grid is recovered from
   text geometry, and each crop is confined to the band its caption occupies, so
   a right-column figure cannot absorb the left column. A caption that spans the
   gutter marks a full-width figure.
3. **Ownership rules** — a crop may never contain another caption, and content
   belongs to the caption nearest to it.
4. **High-DPI render and crop** with PyMuPDF (300 dpi default).
5. **Quality scoring** — every crop is `ok` / `suspect` / `failed` with reasons.
6. **Contact sheet, manifest, ZIP.**

Tables are first-class: detected structurally, including tables that are pure
text with rules. On the HTML side every container form is handled — `<img>`,
`<picture>`/`srcset`, lazy-load attributes, inline `data:` base64, inline
`<svg>`, and `<object>`/`<embed>`. HTML tables, which have no bitmap to crop,
are exported as Markdown so the numbers survive.

**Extraction is exhaustive; selection is not.** Everything the document labels
comes out. The suggested tier is a signal to help you choose what to read, and
it filters nothing unless you ask it to.

## Measured behaviour

Recall and crop quality on two papers with opposite layouts, checked by eye
against the rendered contact sheets:

| Paper | Layout | Figures | Tables | Crop status |
|---|---|---|---|---|
| ResNet (`1512.03385`) | 2-column CVPR | 7 / 7 | 14 / 14 | 21 ok · 0 suspect · 0 failed |
| Transformer (`1706.03762`) | single column | 5 / 5 | 4 / 4 | 9 ok · 0 suspect · 0 failed |
| KAN (`2404.19756`, arXiv HTML) | HTML | 25 images | 7 text tables | 32 / 32 containers accounted for |

## Use as an agent skill

This repo ships a [`SKILL.md`](SKILL.md) with standard YAML frontmatter, so
skill-aware agents can auto-load it. Point your agent's skill loader at this repo
(or drop it into your skills directory) and it triggers on requests like
"extract the figures from this arXiv paper" or "pull the charts out of this PDF".

## Commands

```bash
# Local PDF, PDF URL, arXiv abs/pdf/html, OpenReview forum, ACL Anthology
figure-extractor extract paper.pdf --out ./figures --dpi 300 --zip
figure-extractor extract https://arxiv.org/abs/2404.19756 --out ./figures
figure-extractor extract https://openreview.net/forum?id=XXXX --out ./figures
figure-extractor extract https://example.com/article --prefer html --fallback pdf

# Only figures, skip tables
figure-extractor extract paper.pdf --kinds figure

# Only the crops most likely to be load-bearing
figure-extractor extract paper.pdf --tiers A

# Manual bbox correction when a crop is wrong
figure-extractor crop paper.pdf --page 5 --bbox 295,245,556,475 --out fig04.png
```

## Output

```
figures/
  fig1_p01.png          named by the paper's own numbering
  fig2-1_p03.png        chapter-scoped numbers keep their identity
  figB-1_p14.png        appendix labels too
  tab3_p06.png
  tab1.md               HTML text tables, exported as Markdown
  contact_sheet.jpg     QA sheet; suspect/failed crops flagged in colour
  manifest.json
  figures.zip           with --zip
```

`manifest.json` records, per item: label, kind, page, caption, bbox, column
layout, how often the body text refers to it, a suggested triage tier, the
quality status, and the reasons behind it.

### Triage tiers

Reading a paper does not require every figure at 300 dpi. Each item gets a
suggested tier from how often the body cites it and whether it is the paper's
opening figure:

- **A** — likely load-bearing: cited repeatedly, or the first figure.
- **B** — supporting evidence worth keeping.
- **C** — rarely cited; a crop is probably not worth reading time.

These come from citation counts alone. Whether a figure carries a paper's
argument depends on the argument, which a counter cannot see — treat the tier as
a starting point for triage, never as a verdict. Nothing is filtered by default;
pass `--tiers A,B` if you explicitly want to skip the long tail.

## Quality control

Always open `contact_sheet.jpg`. Crops marked `suspect` or `failed` are labelled
in orange and red. If one is wrong, fix it with `crop --bbox`; the bbox in
`manifest.json` is your starting point.

`failed` means no graphics were found for that caption, or the box produced was
degenerate — not that the figure does not exist.

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

The suite builds synthetic PDFs and asserts geometry: that a two-column page is
detected as such, that a crop stays inside its column, that stacked figures do
not claim each other's content, and that tables are found at all.

## License

MIT

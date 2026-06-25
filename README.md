# figure-extractor

**Extract complete figures and images from PDF, arXiv, and HTML papers.** A packaged
**AI-agent skill** (works with **Claude Code**, **Codex**, **Kimi**, and any
skill-aware coding agent) plus a standalone `figure-extractor` CLI.

> Also known as: *paper figure extractor*, *pdf figure extractor*, *arxiv figure
> extraction*, *extract figures from pdf*, *extract images from html article*.

It supports:

- Local PDF files
- PDF URLs (including arXiv `/abs/` → `/pdf/` normalization)
- HTML article URLs or local HTML files with embedded `<figure>`, `<img>`, `srcset`, lazy-loaded images

The key design choice is: **do not rely on embedded PDF image extraction alone**. Many academic figures are composed of vector drawings, text labels, legends, and raster fragments. Instead, this tool uses:

1. Figure caption detection (`Figure 1.`, `Fig. 1`, `FIGURE 1`)
2. Figure-region bbox inference from drawing/image/text primitives
3. High-DPI page rendering with PyMuPDF
4. Crop from the rendered page
5. Contact sheet QA
6. Manifest + ZIP output

## Use as an agent skill

This repo ships a [`SKILL.md`](SKILL.md) with standard YAML frontmatter, so
skill-aware agents can auto-load it. Point your agent's skill loader at this repo
(or drop it into your skills directory) and it triggers on requests like
"extract the figures from this arXiv paper" or "pull the charts out of this PDF".

### Requirements & non-shell runtimes

This is a **CLI tool** (Python + PyMuPDF) — "using it" means running the
`figure-extractor` command in a shell. It is **not** an in-agent callable or a
hosted service. It works in shell-capable agents (Claude Code, Codex, Kimi)
after `pip install`. In runtimes with **no shell / no pip** (e.g. Notion Agent,
browser-only agents) the CLI cannot run; `SKILL.md` defines a **precondition
check** (`figure-extractor --help`) and a **degraded fallback** (link the
original figure + faithful structured description + an explicit "bitmap not
embedded, because…" note), which is an acceptable result rather than a failure.

## Install

```bash
pip install -e .
```

or just install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Local PDF

```bash
figure-extractor extract paper.pdf --out ./figures --dpi 300 --zip
```

### PDF URL

```bash
figure-extractor extract https://arxiv.org/pdf/2606.23443 --out ./figures --dpi 300 --zip
```

### arXiv abs URL

```bash
figure-extractor extract https://arxiv.org/abs/2606.23443 --out ./figures --dpi 300 --zip
```

### HTML article URL

```bash
figure-extractor extract https://example.com/article --out ./figures --prefer html --fallback pdf
```

### Manual crop correction

```bash
figure-extractor crop paper.pdf --page 5 --bbox 295,245,556,475 --out fig04.png --dpi 300
```

## Outputs

```text
figures/
├── fig01_p03.png
├── fig02_p04.png
├── ...
├── manifest.json
├── contact_sheet.jpg
└── figures.zip
```

## When to use which mode

- `html`: best when the paper page exposes high-res figure image files.
- `pdf`: best when only a PDF is available.
- `auto`: tries HTML first for HTML URLs, then falls back to PDF if a PDF link is found.
- `manual crop`: use for single figures whose bbox needs correction.

## Known limitations

- Multi-page figures and captions separated from figures may require manual correction.
- Publisher pages behind login or anti-bot protection may need browser/session-based download.
- PDF bbox inference is heuristic; always inspect `contact_sheet.jpg`.

## License

[MIT](LICENSE)

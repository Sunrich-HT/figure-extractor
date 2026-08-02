"""Page layout analysis: text blocks, column detection, content margins.

The single biggest source of bad crops is treating a two-column page as if it
were one column. Everything above a caption gets unioned together, so a figure
in the right column absorbs unrelated content from the left column.

Column structure is not declared anywhere in a PDF, so we recover it from the
geometry of the text blocks: a multi-column page has a vertical *gutter* — a
band of x positions that essentially no text block crosses.
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz


@dataclass(frozen=True)
class Column:
    x0: float
    x1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    def contains(self, rect: fitz.Rect, tolerance: float = 6.0) -> bool:
        return rect.x0 >= self.x0 - tolerance and rect.x1 <= self.x1 + tolerance


@dataclass
class PageLayout:
    page_rect: fitz.Rect
    columns: list[Column]
    content_x0: float
    content_x1: float
    content_y0: float
    content_y1: float

    @property
    def is_multi_column(self) -> bool:
        return len(self.columns) > 1

    def band_for(self, rect: fitz.Rect) -> Column:
        """Which horizontal band an element occupies.

        An element that fits inside one column is constrained to that column. An
        element that spans the gutter is a full-width element and gets the whole
        content width. This is the key signal: **the caption itself tells us how
        wide its figure is allowed to be.**
        """
        for col in self.columns:
            if col.contains(rect):
                return col
        return Column(self.content_x0, self.content_x1)


@dataclass
class Block:
    """A text block plus the structural evidence needed to classify it."""

    rect: fitz.Rect
    text: str
    n_lines: int
    max_spans_per_line: int
    multi_span_lines: int
    median_span_gap: float = 0.0
    rotated: bool = False
    monospace: bool = False

    def __iter__(self):
        # Legacy unpacking support: `for rect, text in blocks`.
        yield self.rect
        yield self.text


# Family-name markers for fixed-width faces, covering the TeX typewriter fonts
# (cmtt, lmtt, Inconsolata) as well as the usual screen and code families.
_MONO_NAME_MARKERS = (
    "mono", "courier", "consol", "typewriter", "cmtt", "lmtt",
    "menlo", "firacode", "jetbrains", "sourcecodepro",
)


def _is_monospace(span: dict) -> bool:
    """Whether a span is set in a fixed-width face.

    PyMuPDF's monospace flag is only as trustworthy as the embedded font
    descriptor, which TeX pipelines routinely leave unset — Inconsolata arrives
    with the bit clear — so fall back to the family name.
    """
    if span.get("flags", 0) & 8:
        return True
    name = (span.get("font") or "").lower()
    return any(marker in name for marker in _MONO_NAME_MARKERS)


def text_blocks(page: fitz.Page) -> list[Block]:
    """Text blocks with line/span structure, skipping image blocks."""
    out: list[Block] = []
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") != 0:
            continue
        lines = b.get("lines", []) or []
        parts = [span.get("text", "") for line in lines for span in line.get("spans", [])]
        text = " ".join("".join(parts).split())
        if not text:
            continue
        span_counts = [len(line.get("spans", []) or []) for line in lines]
        # Largest horizontal hole inside each line. Cell gutters open real gaps;
        # inline italics or math inside a sentence do not.
        line_gaps = []
        for line in lines:
            boxes = sorted(
                (sp.get("bbox") for sp in (line.get("spans", []) or []) if sp.get("bbox")),
                key=lambda b: b[0],
            )
            gaps = [boxes[i + 1][0] - boxes[i][2] for i in range(len(boxes) - 1)]
            line_gaps.append(max(gaps) if gaps else 0.0)
        line_gaps.sort()
        median_gap = line_gaps[len(line_gaps) // 2] if line_gaps else 0.0
        # Preprint servers stamp a vertical identifier down the edge of page 1.
        # It is text, but it is not part of the column grid, and letting it vote
        # on the page geometry corrupts every measurement downstream.
        dirs = [tuple(line.get("dir", (1, 0))) for line in lines]
        rotated = bool(dirs) and all(abs(dx) < 0.7 for dx, _ in dirs)
        spans = [sp for line in lines for sp in (line.get("spans", []) or [])]
        mono = bool(spans) and sum(_is_monospace(sp) for sp in spans) >= len(spans) * 0.6
        out.append(
            Block(
                rect=fitz.Rect(b["bbox"]),
                text=text,
                n_lines=len(lines),
                max_spans_per_line=max(span_counts) if span_counts else 0,
                multi_span_lines=sum(1 for c in span_counts if c >= 2),
                median_span_gap=median_gap,
                rotated=rotated,
                monospace=mono,
            )
        )
    return out


def _content_bounds(page: fitz.Page, blocks) -> tuple[float, float, float, float]:
    """Ink bounds of the page, so we stop hardcoding 35pt margins.

    Rotated blocks are excluded: a preprint server's vertical identifier down
    the edge of page 1 is real ink, but it sits outside the column grid, and
    letting it set the left bound inflates the apparent content width enough to
    break column detection downstream.
    """
    rects = [b.rect for b in blocks if not b.rotated]
    rects += [fitz.Rect(d["rect"]) for d in page.get_drawings()]
    try:
        rects += [fitz.Rect(i["bbox"]) for i in page.get_image_info(xrefs=True)]
    except Exception:
        pass
    rects = [r for r in rects if r.width > 1 and r.height > 1]
    if not rects:
        pr = page.rect
        return pr.x0 + 40, pr.x1 - 40, pr.y0 + 40, pr.y1 - 40
    return (
        max(page.rect.x0, min(r.x0 for r in rects)),
        min(page.rect.x1, max(r.x1 for r in rects)),
        max(page.rect.y0, min(r.y0 for r in rects)),
        min(page.rect.y1, max(r.y1 for r in rects)),
    )


def detect_columns(page: fitz.Page, blocks) -> list[Column]:
    """Recover column bands by locating vertical gutters.

    A gutter is a contiguous run of x positions crossed by no *narrow* text
    block. Full-width elements (spanning figures, tables, titles) legitimately
    cross the gutter, so they are excluded from the vote by ignoring blocks
    wider than 60% of the content width.
    """
    x0, x1, _, _ = _content_bounds(page, blocks)
    content_w = x1 - x0
    if content_w <= 0:
        return [Column(page.rect.x0, page.rect.x1)]

    spans = [
        (b.rect.x0, b.rect.x1)
        for b in blocks
        if not b.rotated and b.rect.width > 20 and b.rect.width < content_w * 0.60 and len(b.text) > 25
    ]
    # Not enough narrow prose to judge: assume single column.
    if len(spans) < 6:
        return [Column(x0, x1)]

    step = 2.0
    n = max(1, int(content_w / step))
    crossings = []
    for i in range(n):
        x = x0 + i * step
        crossings.append(sum(1 for a, b in spans if a < x < b))

    # A gutter is where *almost* nothing crosses, not where nothing crosses.
    # Titles, spanning figures and wide captions legitimately bridge the columns,
    # and demanding a perfectly empty channel lets a single title erase the
    # entire two-column structure of the page.
    tolerance = max(0, int(len(spans) * 0.10))

    lo, hi = int(n * 0.28), int(n * 0.72)
    best: tuple[int, int] | None = None
    run_start = None
    for i in range(lo, hi):
        if crossings[i] <= tolerance:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                if best is None or (i - run_start) > (best[1] - best[0]):
                    best = (run_start, i)
                run_start = None
    if run_start is not None and (best is None or (hi - run_start) > (best[1] - best[0])):
        best = (run_start, hi)

    # A real gutter is a meaningful fraction of the page, not a coincidental gap.
    if best is None or (best[1] - best[0]) * step < content_w * 0.015:
        return [Column(x0, x1)]

    gutter_x0 = x0 + best[0] * step
    gutter_x1 = x0 + best[1] * step
    left = Column(x0, gutter_x0)
    right = Column(gutter_x1, x1)
    # Reject lopsided splits: real two-column layouts are roughly symmetric.
    if min(left.width, right.width) < content_w * 0.30:
        return [Column(x0, x1)]
    return [left, right]


def consensus_columns(layouts: list[PageLayout]) -> list[Column] | None:
    """The column geometry the document as a whole agrees on.

    Column detection needs prose to measure, so a page that is mostly figure —
    exactly the page where cropping matters most — can look single-column on its
    own evidence. A paper does not change its column count page by page, so
    pages with too little text should inherit the document's answer instead of
    silently widening every crop to the full page.
    """
    votes: dict[tuple[int, int, int, int], int] = {}
    for layout in layouts:
        if not layout.is_multi_column:
            continue
        left, right = layout.columns[0], layout.columns[1]
        key = (round(left.x0 / 4), round(left.x1 / 4), round(right.x0 / 4), round(right.x1 / 4))
        votes[key] = votes.get(key, 0) + 1
    if not votes:
        return None
    key, count = max(votes.items(), key=lambda kv: kv[1])
    multi_pages = sum(1 for layout in layouts if layout.is_multi_column)
    # Demand a real majority among the pages that could be measured, so one
    # oddly-typeset page cannot impose a grid on the rest of the document.
    if count < max(2, multi_pages * 0.5):
        return None
    a, b, c, d = (v * 4 for v in key)
    return [Column(a, b), Column(c, d)]


def apply_consensus(layout: PageLayout, consensus: list[Column] | None) -> PageLayout:
    """Give an under-determined page the document's column geometry."""
    if consensus is None or layout.is_multi_column:
        return layout
    span = consensus[-1].x1 - consensus[0].x0
    page_span = layout.content_x1 - layout.content_x0
    # Only if this page's content really occupies the same measure.
    if page_span < span * 0.75 or page_span > span * 1.25:
        return layout
    layout.columns = list(consensus)
    return layout


def analyze(page: fitz.Page) -> tuple[PageLayout, list[tuple[fitz.Rect, str]]]:
    blocks = text_blocks(page)
    cx0, cx1, cy0, cy1 = _content_bounds(page, blocks)
    layout = PageLayout(
        page_rect=page.rect,
        columns=detect_columns(page, blocks),
        content_x0=cx0,
        content_x1=cx1,
        content_y0=cy0,
        content_y1=cy1,
    )
    return layout, blocks


PROSE = "prose"
TABULAR = "tabular"
LABEL = "label"


def text_role(block: Block, band_width: float) -> str:
    """Classify a text block as prose, tabular data, or a short label.

    This distinction carries real weight. Prose is a *barrier*: a crop must never
    grow through a paragraph. Tabular text is *content*: many tables in papers
    are pure text with rules, so excluding them as "long text" makes tables
    unextractable. Labels (axis ticks, legends) are content too.

    Two shape heuristics both fail on their own. "Long text = prose" swallows
    tables. "Digit-heavy = table" misses symbolic tables whose cells read
    ``O(n^2 · d)``. The load-bearing signal is *column structure*: a table's
    lines are split into several spans at repeating x offsets, while a paragraph
    is one run of text per line.
    """
    rect, text = block.rect, block.text
    if len(text) < 60:
        return LABEL

    # A block set in a fixed-width face is code or a transcript — the body of a
    # listing, never the paper's own prose. Left as PROSE it becomes a barrier
    # and the listing's crop stops at its own first paragraph.
    if block.monospace:
        return TABULAR

    # Impossible leading: prose needs roughly 1.2x its font size per line, so a
    # block claiming far more lines than its height allows must be laying them
    # out side by side — that is a grid of cells, not a paragraph.
    if block.n_lines >= 3 and rect.height / block.n_lines < 8.0:
        return TABULAR

    # Column structure: most lines broken into cells *separated by gutters*.
    # Span count alone is not enough — justified prose containing inline math or
    # citations is also split into many spans, and treating it as tabular
    # removes the barrier that stops a crop from running into the next section.
    if (
        block.n_lines >= 3
        and block.multi_span_lines >= max(2, int(block.n_lines * 0.6))
        and block.median_span_gap >= 6.0
    ):
        return TABULAR

    digits = sum(c.isdigit() for c in text)
    alpha = sum(c.isalpha() for c in text)
    if digits / max(1, digits + alpha) > 0.15:
        return TABULAR

    fill = rect.width / band_width if band_width > 0 else 0
    if fill > 0.70 and rect.height > 20:
        return PROSE
    if len(text) > 400:
        return PROSE
    return LABEL


def is_body_text(block: Block, band_width: float) -> bool:
    """Whether a text block is prose rather than figure content.

    The previous heuristic excluded blocks that were *long and short* — which is
    the shape of a caption, not of a paragraph. A paragraph is long and **tall**
    and fills its column, so that test let entire sections into the crop.
    """
    return text_role(block, band_width) == PROSE

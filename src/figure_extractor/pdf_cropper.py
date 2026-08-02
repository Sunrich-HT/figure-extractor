"""PDF figure/table extraction by caption-anchored, column-aware bbox inference.

Algorithm, in one paragraph: find every caption label on the page; decide which
horizontal band it lives in (one column, or the full content width when it
spans the gutter); grow a cluster of graphic primitives outward from the caption
in the conventional direction for its kind, stopping at *barriers* — other
captions and prose paragraphs; pull in nearby non-prose text (axis labels,
legends); then score the result so a bad crop reports itself as bad.
"""

from __future__ import annotations

import contextlib
import io
import json
import zipfile
from pathlib import Path

import fitz

from .captions import ALL_KINDS, Label, count_references, parse_label
from .contact_sheet import make_contact_sheet
from .layout import (
    LABEL, PROSE, TABULAR, Column, PageLayout, analyze, apply_consensus,
    consensus_columns, is_body_text, text_role,
)
from .quality import assess, suggest_tier

# Backwards-compatible export: older callers/tests import CAPTION_RE from here.
from .captions import CAPTION_RE  # noqa: F401

# Exhibits whose body is text rather than graphics: a table's rows, an
# algorithm's pseudocode, a listing's source lines *are* the content, so looking
# only for drawings finds nothing to crop and reports a failure that is not one.
TEXT_BODIED_KINDS = frozenset({"table", "algorithm", "listing", "box"})

# Vertical distance (pt) allowed between two pieces of the same figure.
MAX_INTERNAL_GAP = 42.0
# How many column segments back a page-broken exhibit may be followed.
MAX_CONTINUATION_SEGMENTS = 4
# How far from the caption the figure body may start. Generous on purpose: the
# real guard against over-reaching is the barrier check, not this number.
MAX_CAPTION_GAP = 120.0


def _thicken(r: fitz.Rect, eps: float = 0.5) -> fitz.Rect:
    """Give zero-thickness rects a sliver of size.

    A perfectly horizontal rule or vertical connector has width or height of
    exactly 0, which makes ``Rect.is_empty`` true. Treating those as "nothing"
    discards table rules and every line of an attention diagram — the geometry
    is real, only its measure is zero.
    """
    r = fitz.Rect(r)
    if r.x1 - r.x0 < eps:
        r.x1 = r.x0 + eps
    if r.y1 - r.y0 < eps:
        r.y1 = r.y0 + eps
    return r


def _graphic_primitives(page: fitz.Page, layout: PageLayout) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    for d in page.get_drawings():
        r = _thicken(d["rect"])
        # Drop only true specks. Rejecting anything *thin* would discard axes,
        # rules and connector lines — an attention heat-map is made almost
        # entirely of long hairlines, and filtering on `width < 2 or height < 2`
        # erases the whole figure.
        if r.width < 2 and r.height < 2:
            continue
        # Header/footer rules: full-width hairlines outside the content band.
        if r.height < 3 and r.width > (layout.content_x1 - layout.content_x0) * 0.8:
            if r.y1 < layout.content_y0 + 24 or r.y0 > layout.content_y1 - 24:
                continue
        rects.append(r)
    try:
        for info in page.get_image_info(xrefs=True):
            r = _thicken(info["bbox"])
            if r.width > 2 and r.height > 2:
                rects.append(r)
    except Exception:
        pass
    return rects


def _normalise(crop: fitz.Rect, page: fitz.Page) -> fitz.Rect:
    """Clamp to the page and repair inverted edges.

    Clamping against a caption can invert an edge (content that starts below
    where it was allowed to end). Left inverted, PyMuPDF raises deep inside the
    renderer; normalised, the box is simply empty and the scorer calls it a
    failure.
    """
    return fitz.Rect(
        min(crop.x0, crop.x1), min(crop.y0, crop.y1),
        max(crop.x0, crop.x1), max(crop.y0, crop.y1),
    ) & page.rect


def _detected_tables(page: fitz.Page) -> list[fitz.Rect]:
    """Structural table bboxes from PyMuPDF's table finder.

    Heuristics over text shape cannot reliably separate a symbolic results table
    (``O(n^2 · d)``, almost no digits) from a paragraph. A dedicated table
    detector can, so prefer it and keep the heuristic only as a fallback.
    """
    # PyMuPDF prints an advisory line to stdout from inside find_tables(). The
    # CLI emits JSON on stdout, so an unsolicited banner there is not cosmetic —
    # it makes the output unparseable for anything downstream.
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            finder = page.find_tables()
    except Exception:
        return []
    out = []
    for t in getattr(finder, "tables", []) or []:
        try:
            r = fitz.Rect(t.bbox)
        except Exception:
            continue
        if not r.is_empty and r.width > 8 and r.height > 8:
            out.append(r)
    return out


def _merge_contiguous(rects: list[fitz.Rect]) -> list[fitz.Rect]:
    """Union rects that stack together vertically.

    Table detectors routinely return one logical table as several fragments
    split at horizontal rules. Taking the nearest fragment yields a 9pt sliver
    where the table should be, so stitch neighbours back together first.
    """
    if not rects:
        return []
    ordered = sorted(rects, key=lambda r: (r.y0, r.x0))
    groups = [fitz.Rect(ordered[0])]
    for r in ordered[1:]:
        cur = groups[-1]
        if r.y0 - cur.y1 <= MAX_INTERNAL_GAP:
            groups[-1] = cur | r
        else:
            groups.append(fitz.Rect(r))
    return groups


def _match_table(
    cap_rect: fitz.Rect,
    band: Column,
    tables: list[fitz.Rect],
    window: tuple[float, float],
) -> fitz.Rect | None:
    """The detected table nearest this caption, within its caption window.

    Restricting to the window before matching is what stops a caption from
    binding to a neighbour's content — a plot misdetected as a table two
    captions away is no longer even a candidate.
    """
    y_lo, y_hi = window
    inside = [
        r for r in tables
        if _in_band(r, band) and r.y1 > y_lo - 2 and r.y0 < y_hi + 2
    ]
    best: tuple[float, fitz.Rect] | None = None
    for r in _merge_contiguous(inside):
        if r.y0 >= cap_rect.y1 - 2:
            gap = r.y0 - cap_rect.y1
        elif r.y1 <= cap_rect.y0 + 2:
            gap = cap_rect.y0 - r.y1
        else:
            continue  # overlaps the caption itself
        if gap > MAX_CAPTION_GAP:
            continue
        if best is None or gap < best[0]:
            best = (gap, r)
    return None if best is None else fitz.Rect(best[1])


def _rule_side(
    primitives: list[fitz.Rect],
    cap_rect: fitz.Rect,
    band: Column,
    window: tuple[float, float],
) -> str | None:
    """Which side of the caption the table's own rules sit on, if it has any.

    LaTeX puts ``\\caption`` wherever the author wrote it, so a table caption may
    sit above or below its rules. Deciding by the gap to the nearest content
    alone is fragile: a two-column page whose grid was read as one wide column
    makes the paragraphs underneath look like short labels rather than prose, so
    they become candidate table content a point or two nearer than the real
    table. Booktabs rules are unambiguous, so use them when they exist and let
    the gap decide only when they do not.
    """
    y_lo, y_hi = window
    min_width = max(40.0, band.width * 0.35)
    above, below = [], []
    for r in primitives:
        if r.height > 3.0 or r.width < min_width:
            continue
        if not _overlaps_band(r, band) or r.y1 < y_lo - 2 or r.y0 > y_hi + 2:
            continue
        if r.y1 <= cap_rect.y0 + 2:
            above.append(cap_rect.y0 - r.y1)
        elif r.y0 >= cap_rect.y1 - 2:
            below.append(r.y0 - cap_rect.y1)

    # A table is bounded by at least a top and a bottom rule; one stray hairline
    # is more likely a figure's axis than a tabular.
    up_ok, down_ok = len(above) >= 2, len(below) >= 2
    if up_ok and not down_ok:
        return "up"
    if down_ok and not up_ok:
        return "down"
    if up_ok and down_ok:
        return "up" if min(above) < min(below) else "down"
    return None


def _caption_window(
    cap_rect: fitz.Rect,
    other_captions: list[fitz.Rect],
    band: Column,
    layout: PageLayout,
) -> tuple[float, float]:
    """The vertical span this caption may legitimately claim.

    Bounded by the nearest caption above and below in the same band. Everything
    else on the page belongs to somebody else.
    """
    above = [o.y1 for o in other_captions if _overlaps_band(o, band) and o.y1 <= cap_rect.y0 + 2]
    below = [o.y0 for o in other_captions if _overlaps_band(o, band) and o.y0 >= cap_rect.y1 - 2]
    y_lo = max(above) + 2 if above else layout.content_y0 - 4
    y_hi = min(below) - 2 if below else layout.content_y1 + 4
    return y_lo, y_hi


def _in_band(rect: fitz.Rect, band: Column) -> bool:
    """Rect overlaps the band by most of its own width.

    Uses a floor on the denominator so a zero-width vertical line is judged by
    position rather than silently excluded by a division guard.
    """
    inter = max(0.0, min(rect.x1, band.x1) - max(rect.x0, band.x0))
    return inter / max(rect.width, 0.1) > 0.55


def _overlaps_band(rect: fitz.Rect, band: Column) -> bool:
    """Whether a rect impinges on the band at all.

    Content assignment asks "is this rect *inside* my column"; caption
    boundaries ask the weaker question "does this label sit across my column".
    A full-width caption fails the first test — less than 55% of its width lands
    in either column — yet it unquestionably bounds what a single-column figure
    beneath it may claim. Using the strict test for both is why a spanning
    caption used to bound nothing at all.
    """
    inter = max(0.0, min(rect.x1, band.x1) - max(rect.x0, band.x0))
    return inter > min(band.width, rect.width) * 0.2


def _barrier_between(barriers: list[fitz.Rect], a_edge: float, b_edge: float) -> bool:
    lo, hi = (a_edge, b_edge) if a_edge <= b_edge else (b_edge, a_edge)
    if hi - lo < 1.0:
        return False
    for b in barriers:
        if b.y0 >= lo - 1.5 and b.y1 <= hi + 1.5:
            return True
    return False


def _cluster(
    cap_rect: fitz.Rect,
    candidates: list[fitz.Rect],
    barriers: list[fitz.Rect],
    direction: str,
) -> fitz.Rect | None:
    """Grow a bbox away from the caption, stopping at gaps and barriers."""
    if direction == "up":
        pool = [r for r in candidates if r.y1 <= cap_rect.y0 + 2]
        pool.sort(key=lambda r: -r.y1)
    else:
        pool = [r for r in candidates if r.y0 >= cap_rect.y1 - 2]
        pool.sort(key=lambda r: r.y0)
    if not pool:
        return None

    first = pool[0]
    if direction == "up":
        gap0, edge_a, edge_b = cap_rect.y0 - first.y1, cap_rect.y0, first.y1
    else:
        gap0, edge_a, edge_b = first.y0 - cap_rect.y1, cap_rect.y1, first.y0
    # Distance alone is a weak signal — journals leave 60pt of air between a
    # figure and its caption. What actually separates "my figure" from "someone
    # else's content" is whether prose or another caption sits in between.
    if gap0 > MAX_CAPTION_GAP:
        return None
    if gap0 > 0 and _barrier_between(barriers, edge_a, edge_b):
        return None

    cluster = fitz.Rect(first)
    for r in pool[1:]:
        if direction == "up":
            gap = cluster.y0 - r.y1
            edge_a, edge_b = cluster.y0, r.y1
        else:
            gap = r.y0 - cluster.y1
            edge_a, edge_b = cluster.y1, r.y0
        if gap > MAX_INTERNAL_GAP:
            break
        if gap > 0 and _barrier_between(barriers, edge_a, edge_b):
            break
        cluster |= r
    return cluster


def _clamp_between_captions(
    crop: fitz.Rect,
    cap_rect: fitz.Rect,
    other_captions: list[fitz.Rect],
    band: Column,
) -> fitz.Rect:
    """Confine a crop to the space between its caption and the neighbouring ones.

    A hard invariant beats another heuristic here: **a crop must never contain a
    different caption**. Distance limits, gap limits and barrier tests are all
    approximations that a real page eventually defeats; "you may not cross your
    neighbour's label" is exact, and it is what stops a figure from swallowing
    the table above it.
    """
    out = fitz.Rect(crop)
    above = [o for o in other_captions if _overlaps_band(o, band) and o.y1 <= cap_rect.y0 + 2]
    below = [o for o in other_captions if _overlaps_band(o, band) and o.y0 >= cap_rect.y1 - 2]
    if above:
        out.y0 = max(out.y0, max(o.y1 for o in above) + 2)
    if below:
        out.y1 = min(out.y1, min(o.y0 for o in below) - 2)
    return out


def _closer_caption_exists(
    cluster: fitz.Rect,
    cap_rect: fitz.Rect,
    other_captions: list[fitz.Rect],
    band: Column,
    own_gap: float,
) -> bool:
    """Whether some other caption sits nearer to this content than we do.

    Content belongs to its nearest caption. Without this rule a caption placed
    below its own table happily claims the figure underneath it, and two
    captions end up describing the same pixels.
    """
    own = max(0.0, own_gap)
    for o in other_captions:
        if not _overlaps_band(o, band) or o == cap_rect:
            continue
        if o.y0 >= cluster.y1:
            d = o.y0 - cluster.y1
        elif o.y1 <= cluster.y0:
            d = cluster.y0 - o.y1
        else:
            return True  # another caption sits inside the cluster
        if d < own - 2:
            return True
    return False


def _attach_labels(
    cluster: fitz.Rect,
    blocks: list[tuple[fitz.Rect, str]],
    band: Column,
    cap_rect: fitz.Rect,
    direction: str,
    barriers: list[fitz.Rect],
) -> fitz.Rect:
    """Pull in axis labels / legends that sit just outside the graphic hull."""
    halo = fitz.Rect(cluster)
    halo.x0 -= 22
    halo.x1 += 22
    halo.y0 -= 24
    halo.y1 += 24
    out = fitz.Rect(cluster)
    for block in blocks:
        r = block.rect
        if not _in_band(r, band):
            continue
        if is_body_text(block, band.width):
            continue
        if direction == "up" and r.y1 > cap_rect.y0 + 2:
            continue
        if direction == "down" and r.y0 < cap_rect.y1 - 2:
            continue
        if not r.intersects(halo):
            continue
        edge_a = out.y0 if r.y1 <= out.y0 else out.y1
        edge_b = r.y1 if r.y1 <= out.y0 else r.y0
        if _barrier_between(barriers, edge_a, edge_b):
            continue
        out |= r
    return out


def _infer_bbox(
    page: fitz.Page,
    layout: PageLayout,
    blocks: list[tuple[fitz.Rect, str]],
    primitives: list[fitz.Rect],
    cap_rect: fitz.Rect,
    label: Label,
    other_captions: list[fitz.Rect],
    margin: float,
    tables: list[fitz.Rect],
) -> tuple[fitz.Rect, bool, Column, list[fitz.Rect]]:
    """Infer one crop box. Returns (crop, had_graphics, band, prose_rects)."""
    band = layout.band_for(cap_rect)
    window = _caption_window(cap_rect, other_captions, band, layout)

    prose = [b.rect for b in blocks if _in_band(b.rect, band) and is_body_text(b, band.width)]
    barriers = [r for r in other_captions if _overlaps_band(r, band)] + prose

    # Structural detection wins outright when it fires.
    if label.kind == "table":
        matched = _match_table(cap_rect, band, tables, window)
        if matched is not None:
            crop = fitz.Rect(matched)
            crop.x0 = max(band.x0 - 2, crop.x0 - margin)
            crop.x1 = min(band.x1 + 2, crop.x1 + margin)
            crop.y0 -= margin
            crop.y1 += margin
            crop = _normalise(crop, page)
            return crop, not crop.is_empty, band, prose

    y_lo, y_hi = window

    def _within(r: fitz.Rect) -> bool:
        return r.y1 > y_lo - 2 and r.y0 < y_hi + 2

    graphics = [r for r in primitives if _in_band(r, band) and _within(r)]
    # Tables are frequently pure text with rules, so their body *is* text.
    if label.kind in TEXT_BODIED_KINDS:
        content = graphics + [
            b.rect for b in blocks
            if _in_band(b.rect, band)
            and _within(b.rect)
            and b.rect != cap_rect
            and text_role(b, band.width) in {TABULAR, LABEL}
        ]
    else:
        content = graphics

    # Conventional direction first (tables caption-above, figures caption-below),
    # but fall back to the other side rather than guessing blindly. Where the
    # exhibit has rules of its own, they outrank the convention: plenty of papers
    # caption a table underneath it.
    primary = "down" if label.kind in TEXT_BODIED_KINDS else "up"
    if label.kind in TEXT_BODIED_KINDS:
        primary = _rule_side(primitives, cap_rect, band, window) or primary
    secondary = "up" if primary == "down" else "down"

    # Evaluate both sides and let the evidence decide. Committing to the
    # conventional side as soon as it yields *anything* is what makes a table
    # captioned below its body swallow the next figure instead: content must
    # belong to the caption nearest to it, not to whichever caption asks first.
    uncontested: list[tuple[float, str, fitz.Rect]] = []
    contested: list[tuple[float, str, fitz.Rect]] = []
    for direction in (primary, secondary):
        cluster = _cluster(cap_rect, content, barriers, direction)
        if cluster is None:
            continue
        gap = (cap_rect.y0 - cluster.y1) if direction == "up" else (cluster.y0 - cap_rect.y1)
        entry = (max(0.0, gap), direction, cluster)
        if _closer_caption_exists(cluster, cap_rect, other_captions, band, gap):
            contested.append(entry)
        else:
            uncontested.append(entry)

    # Ownership is a preference, not a veto: when every side is contested we
    # still return the best available box rather than nothing, and let the
    # scorer judge it.
    pool = uncontested or contested
    best: tuple[fitz.Rect, str] | None = None
    if pool:
        # Smallest gap wins; the conventional side breaks near-ties.
        pool.sort(key=lambda c: (round(c[0] / 10.0), 0 if c[1] == primary else 1, c[0]))
        _, direction, cluster = pool[0]
        best = (_attach_labels(cluster, blocks, band, cap_rect, direction, barriers), direction)

    had_graphics = True
    if best is None:
        had_graphics = False
        # Last resort: a conservative box on the caption's conventional side.
        # Always guessing "above" produces a 2pt sliver for a table captioned at
        # the top of a page. Marked as a failure by the scorer either way — never
        # silently reported as a good crop.
        if primary == "down":
            bottom = min(layout.content_y1, cap_rect.y1 + 260)
            crop = fitz.Rect(band.x0, cap_rect.y1 + 2, band.x1, bottom)
        else:
            top = max(layout.content_y0, cap_rect.y0 - 260)
            crop = fitz.Rect(band.x0, top, band.x1, cap_rect.y0 - 2)
    else:
        crop, direction = best
        crop = fitz.Rect(crop)
        crop.x0 = max(band.x0 - 2, crop.x0 - margin)
        crop.x1 = min(band.x1 + 2, crop.x1 + margin)
        if direction == "up":
            crop.y0 = max(layout.content_y0 - 2, crop.y0 - margin)
            crop.y1 = min(cap_rect.y0 - 2, crop.y1 + margin)
        else:
            crop.y0 = max(cap_rect.y1 + 2, crop.y0 - margin)
            crop.y1 = min(layout.content_y1 + 2, crop.y1 + margin)

    crop = _clamp_between_captions(crop, cap_rect, other_captions, band)
    crop = _normalise(crop, page)
    if crop.is_empty or crop.width < 4 or crop.height < 4:
        had_graphics = False
    return crop, had_graphics, band, prose


def _reading_segments(pinfo) -> list[Column]:
    """One page's column bands in reading order."""
    layout = pinfo["layout"]
    if layout.is_multi_column and layout.columns:
        return sorted(layout.columns, key=lambda c: c.x0)
    return [Column(layout.content_x0, layout.content_x1)]


def _segment_tail(pinfo, band: Column) -> tuple[fitz.Rect, bool] | None:
    """The trailing run of exhibit content in one column, read bottom-up.

    Returns ``(rect, starts_here)``, where ``starts_here`` means a paragraph or
    another caption ended the run — the exhibit begins in this segment and the
    walk backwards can stop. Running out of blocks instead means the segment was
    filled top to bottom, so the exhibit continues even further back.

    ``None`` when this segment cannot be a continuation: a broken exhibit always
    resumes at the foot of the preceding column, so content that stops well
    short of it belongs to something else.
    """
    layout = pinfo["layout"]
    caps = [c["rect"] for c in pinfo["captions"] if _overlaps_band(c["rect"], band)]
    candidates = sorted(
        (b for b in pinfo["blocks"] if _in_band(b.rect, band) and b.rect.y1 <= layout.content_y1 + 2),
        key=lambda b: -b.rect.y0,
    )

    kept: list[fitz.Rect] = []
    starts_here = False
    frontier: float | None = None
    for b in candidates:
        if text_role(b, band.width) == PROSE or any(b.rect.intersects(c) for c in caps):
            starts_here = True
            break
        if frontier is not None and frontier - b.rect.y1 > MAX_INTERNAL_GAP:
            starts_here = True
            break
        kept.append(b.rect)
        frontier = b.rect.y0

    if not kept:
        return None
    rect = fitz.Rect(kept[0])
    for r in kept[1:]:
        rect |= r
    if layout.content_y1 - rect.y1 > MAX_INTERNAL_GAP:
        return None  # a gap at the foot of the column: not a continuation
    return rect, starts_here


def _continuation_parts(pages, stream, seg_index: int) -> list[tuple[int, fitz.Rect]]:
    """Earlier pieces of an exhibit broken across columns or pages.

    Walks backwards through the document's reading order, so a listing that ran
    down the left column, over into the right, and onto the next page is
    recovered in the order a reader meets it.
    """
    parts: list[tuple[int, fitz.Rect]] = []
    for k in range(seg_index - 1, max(-1, seg_index - 1 - MAX_CONTINUATION_SEGMENTS), -1):
        page_i, band = stream[k]
        found = _segment_tail(pages[page_i], band)
        if found is None:
            break
        rect, starts_here = found
        parts.append((page_i, rect))
        if starts_here:
            break
    parts.reverse()
    return parts


def _looks_truncated(crop: fitz.Rect, cap_rect: fitz.Rect, layout: PageLayout) -> bool:
    """A crop too small to be the exhibit, with its caption at the top of the column.

    That pairing is the signature of a page break: the body ran out above, and
    all that is left on this page is the last line or two before the caption.
    """
    return crop.height < 40 and (cap_rect.y0 - layout.content_y0) < 60


def _render_parts(parts: list[tuple[fitz.Page, fitz.Rect]], dpi: int, dest: Path, gap: int = 14):
    """Stitch the pieces of a broken exhibit into one image, in reading order."""
    pixes = [page.get_pixmap(dpi=dpi, clip=rect, alpha=False) for page, rect in parts]
    width = max(p.width for p in pixes)
    height = sum(p.height for p in pixes) + gap * (len(pixes) - 1)
    doc = fitz.open()
    try:
        sheet = doc.new_page(width=width, height=height)
        sheet.draw_rect(sheet.rect, color=None, fill=(1, 1, 1))
        y = 0
        for p in pixes:
            sheet.insert_image(fitz.Rect(0, y, p.width, y + p.height), pixmap=p)
            y += p.height + gap
        # 72 dpi renders one pixel per point, preserving the parts' own scale.
        sheet.get_pixmap(dpi=72).save(dest)
    finally:
        doc.close()


def _find_captions(doc: fitz.Document):
    """All caption blocks in reading order, keyed by (kind, number).

    Duplicate labels are kept when they occur on different pages: papers really
    do restart numbering in appendices, and collapsing them loses figures.
    """
    found = []
    for pi, page in enumerate(doc):
        layout, blocks = analyze(page)
        page_caps = []
        for rect, text in blocks:
            label = parse_label(text)
            if label:
                page_caps.append({"label": label, "rect": rect, "text": text})
        found.append({"page_index": pi, "page": page, "layout": layout, "blocks": blocks, "captions": page_caps})

    # Second pass: pages that could not measure their own columns inherit the
    # document's, so a figure-heavy page does not get a full-width band by
    # default.
    consensus = consensus_columns([f["layout"] for f in found])
    for f in found:
        f["layout"] = apply_consensus(f["layout"], consensus)
    return found


def extract_pdf_figures(
    pdf_path: Path,
    out_dir: Path,
    dpi: int = 300,
    margin: float = 8,
    make_sheet: bool = True,
    make_zip: bool = True,
    kinds: tuple[str, ...] = ALL_KINDS,
    tiers: tuple[str, ...] = ("A", "B", "C"),
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    body_text = "\n".join(p.get_text() for p in doc)
    pages = _find_captions(doc)

    items = []
    seen_slugs: dict[str, int] = {}
    first_of_kind: set[str] = set()

    # Reading order across the whole document, so an exhibit broken by a column
    # or page break can be followed back to where it started.
    stream = [(i, col) for i, p in enumerate(pages) for col in _reading_segments(p)]

    for pinfo in pages:
        page = pinfo["page"]
        layout = pinfo["layout"]
        blocks = pinfo["blocks"]
        caps = pinfo["captions"]
        if not caps:
            continue
        primitives = _graphic_primitives(page, layout)
        cap_rects = [c["rect"] for c in caps]
        wants_tables = any(c["label"].kind == "table" for c in caps) and "table" in kinds
        tables = _detected_tables(page) if wants_tables else []

        for cap in caps:
            label: Label = cap["label"]
            if label.kind not in kinds:
                continue
            others = [r for r in cap_rects if r is not cap["rect"]]
            crop, had_graphics, band, prose = _infer_bbox(
                page, layout, blocks, primitives, cap["rect"], label, others, margin, tables
            )
            parts: list[tuple[int, fitz.Rect]] = []
            if label.kind in TEXT_BODIED_KINDS and _looks_truncated(crop, cap["rect"], layout):
                seg = next(
                    (k for k, (pi, col) in enumerate(stream)
                     if pi == pinfo["page_index"] and _overlaps_band(cap["rect"], col)),
                    None,
                )
                if seg is not None:
                    parts = _continuation_parts(pages, stream, seg)

            if parts:
                # The exhibit is real, just split; judge it on its largest piece.
                parts = parts + [(pinfo["page_index"], crop)]
                biggest_i, biggest = max(parts, key=lambda pr: pr[1].get_area())
                verdict = assess(biggest, pages[biggest_i]["page"].rect, [], True, band.width)
            else:
                verdict = assess(crop, page.rect, prose, had_graphics, band.width)
            refs = count_references(body_text, label)
            is_first = label.kind not in first_of_kind
            first_of_kind.add(label.kind)
            tier = suggest_tier(label.kind, refs, verdict, is_first)

            slug = label.slug
            seen_slugs[slug] = seen_slugs.get(slug, 0) + 1
            if seen_slugs[slug] > 1:
                slug = f"{slug}_dup{seen_slugs[slug]}"

            entry = {
                "label": label.display,
                "kind": label.kind,
                "number": label.number,
                "page": pinfo["page_index"] + 1,
                "caption": cap["text"],
                "bbox": [round(v, 2) for v in (crop.x0, crop.y0, crop.x1, crop.y1)],
                "column_layout": "multi" if layout.is_multi_column else "single",
                "spans_columns": layout.is_multi_column and band.width > (layout.content_x1 - layout.content_x0) * 0.8,
                "referenced_in_body": refs,
                "suggested_tier": tier,
                "method": "caption-anchored-column-aware-crop",
                "dpi": dpi,
                "_sort": label.sort_key,
                "_slug": slug,
                "_crop": crop,
                "_page": page,
                "_parts": [(pages[i]["page"], r) for i, r in parts],
            }
            if parts:
                entry["parts"] = [
                    {"page": i + 1, "bbox": [round(v, 2) for v in (r.x0, r.y0, r.x1, r.y1)]}
                    for i, r in parts
                ]
                entry["method"] = "caption-anchored-crop-stitched-across-breaks"
            entry.update(verdict.as_dict())
            items.append(entry)

    items.sort(key=lambda e: (e["page"], e["_sort"]))

    figures = []
    image_paths = []
    skipped = 0
    for e in items:
        if e["suggested_tier"] not in tiers:
            skipped += 1
            e.pop("_crop"), e.pop("_page"), e.pop("_sort"), e.pop("_slug"), e.pop("_parts")
            e["output"] = None
            e["skipped_reason"] = f"tier {e['suggested_tier']} not in requested tiers {list(tiers)}"
            figures.append(e)
            continue
        crop = e.pop("_crop")
        page = e.pop("_page")
        e.pop("_sort")
        slug = e.pop("_slug")
        part_rects = e.pop("_parts")
        out_path = out_dir / f"{slug}_p{e['page']:02d}.png"
        try:
            if part_rects:
                _render_parts(part_rects, dpi, out_path)
            elif crop.is_empty or crop.width < 4 or crop.height < 4:
                raise ValueError(f"degenerate crop {crop.width:.1f}x{crop.height:.1f}pt")
            else:
                pix = page.get_pixmap(dpi=dpi, clip=crop, alpha=False)
                pix.save(out_path)
        except Exception as exc:
            e["output"] = None
            e["status"] = "failed"
            e["quality_score"] = 0.0
            e["quality_reasons"] = list(e.get("quality_reasons", [])) + [f"render failed: {exc}"]
            figures.append(e)
            continue
        e["output"] = str(out_path)
        image_paths.append((out_path, f"{e['label']}  [{e['status']}]"))
        figures.append(e)

    counts = {
        "total": len(figures),
        "rendered": len(image_paths),
        "skipped_by_tier": skipped,
        "ok": sum(1 for f in figures if f["status"] == "ok"),
        "suspect": sum(1 for f in figures if f["status"] == "suspect"),
        "failed": sum(1 for f in figures if f["status"] == "failed"),
        "figures": sum(1 for f in figures if f["kind"] == "figure"),
        "tables": sum(1 for f in figures if f["kind"] == "table"),
    }
    manifest = {
        "source": str(pdf_path),
        "kind": "pdf",
        "dpi": dpi,
        "pages": len(doc),
        "counts": counts,
        "figures": figures,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if make_sheet and image_paths:
        make_contact_sheet(
            [p for p, _ in image_paths],
            out_dir / "contact_sheet.jpg",
            title=f"{pdf_path.name} — {counts['rendered']} crops "
            f"({counts['ok']} ok / {counts['suspect']} suspect / {counts['failed']} failed)",
            labels=[lbl for _, lbl in image_paths],
        )
    if make_zip and image_paths:
        zip_path = out_dir / "figures.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p, _ in image_paths:
                z.write(p, p.name)
            z.write(out_dir / "manifest.json", "manifest.json")
            sheet = out_dir / "contact_sheet.jpg"
            if sheet.exists():
                z.write(sheet, "contact_sheet.jpg")
        manifest["zip"] = str(zip_path)
    return manifest


def crop_manual(pdf_path: Path, page: int, bbox: str, out_path: Path, dpi: int = 300) -> dict:
    doc = fitz.open(pdf_path)
    vals = [float(x) for x in bbox.split(",")]
    if len(vals) != 4:
        raise ValueError("bbox must be x0,y0,x1,y1")
    if not 1 <= page <= doc.page_count:
        raise ValueError(f"page {page} out of range (document has {doc.page_count} pages)")
    rect = fitz.Rect(*vals)
    pix = doc[page - 1].get_pixmap(dpi=dpi, clip=rect, alpha=False)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(out_path)
    return {"page": page, "bbox": vals, "output": str(out_path), "dpi": dpi, "status": "ok"}

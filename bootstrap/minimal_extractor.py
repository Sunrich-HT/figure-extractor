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

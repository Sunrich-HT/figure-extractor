"""Crop quality scoring.

A pipeline that cannot detect its own failures is worse than one that fails
loudly: every crop was previously stamped ``"status": "ok"``, including
whole-page fallbacks that contained the abstract and half a section of prose.

Nothing here inspects pixels. The evidence is geometric — how much prose the
crop swallowed, how much of the page it covers, and whether we ever found real
graphics at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import fitz

OK = "ok"
SUSPECT = "suspect"
FAILED = "failed"


@dataclass
class Verdict:
    status: str
    score: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"status": self.status, "quality_score": round(self.score, 3), "quality_reasons": self.reasons}


def _overlap_area(a: fitz.Rect, b: fitz.Rect) -> float:
    r = fitz.Rect(a) & fitz.Rect(b)
    return 0.0 if r.is_empty else r.width * r.height


def assess(
    crop: fitz.Rect,
    page_rect: fitz.Rect,
    prose_rects: list[fitz.Rect],
    had_graphics: bool,
    band_width: float,
) -> Verdict:
    """Judge one crop. Returns ok / suspect / failed with reasons."""
    reasons: list[str] = []
    score = 1.0

    area = max(1.0, crop.width * crop.height)
    page_area = max(1.0, page_rect.width * page_rect.height)

    if not had_graphics:
        # We never located a drawing or image — the bbox is a guess.
        return Verdict(FAILED, 0.0, ["no graphic primitives found above/below caption"])

    if crop.width < 24 or crop.height < 24:
        return Verdict(FAILED, 0.0, [f"degenerate crop {crop.width:.0f}x{crop.height:.0f}pt"])

    prose_area = sum(_overlap_area(crop, p) for p in prose_rects)
    prose_ratio = min(1.0, prose_area / area)
    if prose_ratio > 0.05:
        score -= min(0.75, prose_ratio * 1.6)
        reasons.append(f"body text covers {prose_ratio:.0%} of crop")

    page_ratio = area / page_area
    if page_ratio > 0.72:
        score -= 0.35
        reasons.append(f"crop covers {page_ratio:.0%} of the page")

    # A crop far wider than its own column band means the column constraint was
    # bypassed — the classic two-column bleed.
    if band_width > 0 and crop.width > band_width * 1.25:
        score -= 0.30
        reasons.append("crop is wider than its column band")

    score = max(0.0, min(1.0, score))
    if score >= 0.75:
        status = OK
    elif score >= 0.35:
        status = SUSPECT
    else:
        status = FAILED
    return Verdict(status, score, reasons)


def suggest_tier(label_kind: str, reference_count: int, verdict: Verdict, is_first: bool) -> str:
    """A *suggested* triage tier. Final tiering is a research judgement.

    Tier A  likely load-bearing: cited repeatedly in the body, or the paper's
            opening figure (which is almost always the claim figure).
    Tier B  supporting evidence worth keeping on disk.
    Tier C  keep the page reference only; do not spend a crop on it.
    """
    if verdict.status == FAILED:
        return "C"
    if is_first or reference_count >= 3:
        return "A"
    if reference_count >= 1 or label_kind == "table":
        return "B"
    return "C"

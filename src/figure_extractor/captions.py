"""Caption label parsing.

Academic papers do not number figures with plain integers. Real corpora contain
chapter-scoped numbers (``Figure 2.1``), appendix letters (``Figure B.1``),
supplementary prefixes (``Table S3``) and panel suffixes (``Figure 1a``).
A parser that only understands ``\\d+`` silently collapses distinct figures onto
the same identity, which downstream turns into overwritten files.

This module keeps the *label* as an opaque, order-aware value instead of an int.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Kinds we recognise. Order matters: longer alternatives first so ``Fig.`` does
# not shadow ``Figure``.
_KIND_ALTERNATIVES = r"Figures?|Figs?\.?|FIGURES?|Tables?|Tabs?\.?|TABLES?|Algorithms?|Algs?\.?"

# A number token: optional letter prefix (appendix/supplement), then a dotted
# numeric path, then an optional panel letter.
#   1        2.1      B.1      S3      A.2.1     1a
_NUM = r"(?:[A-Z]{1,2}[.\-]?)?\d+(?:\.\d+)*[a-z]?"

CAPTION_RE = re.compile(
    rf"^\s*(?P<kind>{_KIND_ALTERNATIVES})\s*"
    rf"(?P<num>{_NUM})\s*"
    r"(?P<sep>[.:：)\]]|\s[-–—|]\s|\s{2,}|$)",
)

# Cross-references inside body text ("Figure 3 shows that ...") must not be
# mistaken for captions. The reliable discriminator is punctuation: a caption is
# "Figure 1:" or "Figure 1.", a cross reference is a bare "Figure 3" followed by
# a verb. Matching on leading words instead is a trap — captions very commonly
# open with "The", so treating "the" as a reference marker silently drops them.
_XREF_TAIL = re.compile(
    r"^\s*(?:shows?|illustrates?|depicts?|presents?|reports?|summari[sz]es?|"
    r"compares?|gives?|lists?|plots?|visuali[sz]es?|demonstrates?)\b",
    re.I,
)
_PUNCT_SEPARATORS = {".", ":", "：", ")", "]"}


def _canon_kind(raw: str) -> str:
    r = raw.lower().rstrip(".")
    if r.startswith("fig"):
        return "figure"
    if r.startswith("tab"):
        return "table"
    if r.startswith("alg"):
        return "algorithm"
    return r


@dataclass(frozen=True)
class Label:
    """A parsed caption label, e.g. ``figure`` + ``B.1``."""

    kind: str  # "figure" | "table" | "algorithm"
    number: str  # verbatim, e.g. "2.1", "B.1", "S3", "1a"

    @property
    def slug(self) -> str:
        """Filename-safe identity. Distinct labels never collide."""
        n = self.number.replace(".", "-").replace("_", "-")
        return f"{self.kind[:3]}{n}"

    @property
    def display(self) -> str:
        return f"{self.kind.capitalize()} {self.number}"

    @property
    def sort_key(self) -> tuple:
        """Order appendix labels after body labels, and 2.10 after 2.9."""
        m = re.match(r"^([A-Z]{1,2})[.\-]?(.*)$", self.number)
        prefix, rest = (m.group(1), m.group(2)) if m else ("", self.number)
        parts: list[int] = []
        for chunk in re.split(r"[.\-]", rest):
            digits = re.sub(r"\D", "", chunk)
            if digits:
                parts.append(int(digits))
        # Empty prefix sorts first so body figures precede appendix figures.
        return (self.kind, prefix or "", tuple(parts), self.number)


def parse_label(text: str) -> Label | None:
    """Parse a caption label from the start of a text block.

    Returns ``None`` when the block is not a caption (including in-text cross
    references such as ``Figure 3 shows ...``).
    """
    m = CAPTION_RE.match(text or "")
    if not m:
        return None
    sep = m.group("sep").strip()
    tail = text[m.end():]

    if sep in _PUNCT_SEPARATORS:
        # Punctuated label — this is a caption, whatever word follows.
        return Label(kind=_canon_kind(m.group("kind")), number=m.group("num"))

    # No punctuation: the block may be prose that happens to begin with a label.
    if _XREF_TAIL.match(tail) or not tail.strip():
        return None
    return Label(kind=_canon_kind(m.group("kind")), number=m.group("num"))


def count_references(body_text: str, label: Label) -> int:
    """How often the body text refers to this label.

    Used as a (weak) signal of how load-bearing a figure is: a figure the authors
    never cite outside its own caption is rarely central to the argument.
    """
    num = re.escape(label.number)
    kind = "Fig(?:ure)?s?\\.?" if label.kind == "figure" else (
        "Tab(?:le)?s?\\.?" if label.kind == "table" else "Alg(?:orithm)?s?\\.?"
    )
    return len(re.findall(rf"{kind}\s*{num}\b", body_text, flags=re.I))

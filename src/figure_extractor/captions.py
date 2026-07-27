"""Caption label parsing.

Extraction has to be exhaustive: whatever a document calls its exhibits, they
should come out. Real corpora use far more than ``Figure N``.

* Chapter-scoped numbers — ``Figure 2.1``
* Appendix and supplementary letters — ``Figure B.1``, ``Table S3``
* Journal prefixes — ``Extended Data Fig. 1``, ``Supplementary Figure 3``
* Kinds beyond figures and tables — ``Scheme``, ``Algorithm``, ``Listing``,
  ``Box``, ``Chart``
* Nature's pipe separator — ``Fig. 1 | Overview``
* Chinese and Japanese labels — ``图 1``, ``表 2``, ``図 1``

A parser that understands only ``\\d+`` collapses distinct exhibits onto the
same identity, which downstream becomes overwritten files. The label is
therefore kept as an opaque, order-aware value rather than an int.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Journal qualifiers that make an otherwise identical number a different object:
# "Extended Data Fig. 1" is not "Fig. 1".
_PREFIX_ALTERNATIVES = (
    r"Extended\s+Data|Supplementary|Supplemental|Supp\.?|Appendix|Online|SI|附录|补充"
)

_KIND_ALTERNATIVES = (
    r"Figures?|Figs?\.?|FIGURES?|FIGS?\.?"
    r"|Tables?|Tabs?\.?|TABLES?"
    r"|Algorithms?|Algos?\.?|Algs?\.?"
    r"|Schemes?|Charts?|Listings?|Boxes|Box|Exhibits?|Plates?|Panels?"
    r"|Movies?|Videos?"
    r"|图表|插图|附图|附表|图|表|算法|方案|表格"
    r"|図表|図|表"
)

# A number token: optional letter prefix (appendix/supplement), a dotted numeric
# path, then an optional panel letter. Matches 1, 2.1, B.1, S3, A.2.1, 1a.
_NUM = r"(?:[A-Z]{1,2}[.\-]?)?\d+(?:\.\d+)*[a-z]?"

# Separators, loosest last. A single space is allowed, but a label separated
# only by a space is then screened against the cross-reference list below.
_SEP = r"[.:：、)\]]|\s*[|｜]\s*|\s[-–—]\s|\s{2,}|\s(?=\S)|$"

CAPTION_RE = re.compile(
    rf"^\s*(?:(?P<prefix>{_PREFIX_ALTERNATIVES})\s*)?"
    rf"(?P<kind>{_KIND_ALTERNATIVES})\s*"
    rf"(?P<num>{_NUM})\s*"
    rf"(?P<sep>{_SEP})",
)

# Verbs that mark a mention of an exhibit rather than its caption.
_XREF_TAIL = re.compile(
    r"^\s*(?:shows?|illustrates?|depicts?|presents?|reports?|summari[sz]es?"
    r"|compares?|gives?|lists?|plots?|visuali[sz]es?|demonstrates?|contains?"
    r"|indicates?|confirms?|suggests?|highlights?|provides?|displays?"
    r"|was|were|can|will|also|further|therefore|hence)\b",
    re.I,
)
_PUNCT_SEPARATORS = {".", ":", "：", "、", ")", "]", "|", "｜", "-", "–", "—"}

_KIND_CANON = [
    (("fig", "図", "图", "插图", "附图", "図表", "图表"), "figure"),
    (("tab", "表", "附表", "表格"), "table"),
    (("alg", "算法"), "algorithm"),
    (("scheme", "方案"), "scheme"),
    (("chart",), "chart"),
    (("listing",), "listing"),
    (("box", "boxes"), "box"),
    (("exhibit",), "exhibit"),
    (("plate",), "plate"),
    (("panel",), "panel"),
    (("movie", "video"), "media"),
]

#: Every canonical kind the parser can produce. Extraction defaults to all of
#: them: which exhibits are worth reading is a judgement for the reader, not a
#: filter to hard-code into retrieval.
ALL_KINDS = (
    "figure", "table", "algorithm", "scheme", "chart",
    "listing", "box", "exhibit", "plate", "panel", "media",
)

_PREFIX_CANON = {
    "extended data": "ed",
    "supplementary": "supp",
    "supplemental": "supp",
    "supp": "supp",
    "si": "supp",
    "补充": "supp",
    "appendix": "app",
    "附录": "app",
    "online": "online",
}


def _canon_kind(raw: str) -> str:
    r = raw.lower().rstrip(".")
    for needles, canon in _KIND_CANON:
        if any(r.startswith(n) for n in needles):
            return canon
    return r


def _canon_prefix(raw: str | None) -> str:
    if not raw:
        return ""
    r = " ".join(raw.lower().rstrip(".").split())
    return _PREFIX_CANON.get(r, re.sub(r"\W+", "", r)[:6])


@dataclass(frozen=True)
class Label:
    """A parsed caption label, e.g. ``figure`` + ``B.1``, optionally qualified."""

    kind: str
    number: str
    prefix: str = ""  # "", "ed", "supp", "app", "online"

    @property
    def slug(self) -> str:
        """Filename-safe identity. Distinct labels never collide."""
        n = self.number.replace(".", "-").replace("_", "-")
        head = f"{self.prefix}-" if self.prefix else ""
        return f"{head}{self.kind[:3]}{n}"

    @property
    def display(self) -> str:
        qualifier = {
            "ed": "Extended Data ",
            "supp": "Supplementary ",
            "app": "Appendix ",
            "online": "Online ",
        }.get(self.prefix, f"{self.prefix.capitalize()} " if self.prefix else "")
        return f"{qualifier}{self.kind.capitalize()} {self.number}"

    @property
    def sort_key(self) -> tuple:
        """Body exhibits first, then appendix/supplementary; 2.10 after 2.9."""
        m = re.match(r"^([A-Z]{1,2})[.\-]?(.*)$", self.number)
        letter, rest = (m.group(1), m.group(2)) if m else ("", self.number)
        parts: list[int] = []
        for chunk in re.split(r"[.\-]", rest):
            digits = re.sub(r"\D", "", chunk)
            if digits:
                parts.append(int(digits))
        prefix_rank = {"": 0, "online": 1, "ed": 2, "app": 3, "supp": 4}.get(self.prefix, 5)
        return (prefix_rank, self.kind, letter or "", tuple(parts), self.number)


def parse_label(text: str) -> Label | None:
    """Parse a caption label from the start of a text block.

    Returns ``None`` when the block is not a caption, including in-text cross
    references such as ``Figure 3 shows ...``.
    """
    m = CAPTION_RE.match(text or "")
    if not m:
        return None

    label = Label(
        kind=_canon_kind(m.group("kind")),
        number=m.group("num"),
        prefix=_canon_prefix(m.group("prefix")),
    )
    sep = m.group("sep").strip()
    tail = text[m.end():]

    if sep in _PUNCT_SEPARATORS:
        # A punctuated label is a caption, whatever word follows. Screening on
        # leading words instead loses every caption that opens with "The".
        return label

    # Separated only by a space, so the label may just open a sentence. Demand
    # positive evidence of a caption rather than the absence of one keyword:
    # "Fig. 6 (middle) shows the behaviors" hides its verb behind a panel
    # reference, so inspecting the first word alone lets it through.
    tail = tail.strip()
    if not tail:
        return None
    if tail.startswith("("):
        return None  # panel reference: "Fig. 6 (middle) ...", "Fig. 4 (a) ..."

    # A caption's title starts like a title — a capital, a digit, or CJK. A
    # cross reference continues the sentence, so the next word is a lowercase
    # verb or preposition. This is general; the verb list below is not, and it
    # let "Figure 3 reveals similar patterns" through because "reveals" simply
    # was not on it.
    if tail[0].islower() and tail[0].isascii():
        return None
    if any(_XREF_TAIL.match(word) for word in tail.split()[:6]):
        return None
    return label


def count_references(body_text: str, label: Label) -> int:
    """How often the body text refers to this label.

    A weak signal of how load-bearing an exhibit is: one the authors never cite
    outside its own caption is rarely central to the argument. It is a signal,
    not a verdict — deciding which figures matter is a reading judgement.
    """
    num = re.escape(label.number)
    kind_patterns = {
        "figure": r"Fig(?:ure)?s?\.?|图",
        "table": r"Tab(?:le)?s?\.?|表",
        "algorithm": r"Alg(?:orithm)?s?\.?|算法",
    }
    kind = kind_patterns.get(label.kind, re.escape(label.kind) + "s?")
    return len(re.findall(rf"(?:{kind})\s*{num}\b", body_text, flags=re.I))

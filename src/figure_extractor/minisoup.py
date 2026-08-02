"""A BeautifulSoup-shaped reader built on the standard library.

The HTML path used to need beautifulsoup4, which put it out of reach of exactly
the runtimes this tool cares about: a sandbox that ships PyMuPDF and cannot
reach PyPI. Parsing HTML well enough to find ``<img>``, ``<figure>``, ``srcset``
and ``<embed>`` does not justify a dependency, so this covers the subset the
extractor uses — ``find``/``find_all``/``get``/``get_text`` — over
``html.parser``.

beautifulsoup4 is still preferred when installed: it is far more forgiving of
real-world markup. This is the fallback that keeps the feature available at all.
"""
from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

# Void elements never have children, so they must not open a nesting level.
VOID = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})
# Nor may these ever be left open by sloppy markup and swallow the rest of the page.
AUTO_CLOSE = {"p": {"p", "div", "section", "figure", "table", "ul", "ol"},
              "li": {"li"}, "tr": {"tr"}, "td": {"td", "th", "tr"}, "th": {"td", "th", "tr"}}


class Tag:
    """One element. Text nodes live in ``strings`` interleaved by position."""

    def __init__(self, name: str, attrs: dict[str, str] | None = None):
        self.name = name
        self.attrs: dict[str, str] = attrs or {}
        self.children: list["Tag"] = []
        self.parent: "Tag | None" = None
        self._text: list[str] = []

    # -- attribute access ---------------------------------------------------
    def get(self, key: str, default=None):
        # bs4 hands back a list for class; callers join it, so match that.
        if key == "class":
            raw = self.attrs.get("class")
            return raw.split() if raw else (default if default is not None else [])
        return self.attrs.get(key, default)

    def __getitem__(self, key: str):
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __contains__(self, key: str) -> bool:
        return key in self.attrs

    # -- traversal ----------------------------------------------------------
    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()

    def _matches(self, name, class_) -> bool:
        if callable(name):
            return bool(name(self))
        if isinstance(name, (list, tuple, set)):
            if self.name not in name:
                return False
        elif isinstance(name, str):
            if self.name != name:
                return False
        if class_ is not None:
            joined = " ".join(self.get("class", []) or [])
            if hasattr(class_, "search"):
                if not class_.search(joined):
                    return False
            elif class_ not in joined.split():
                return False
        return True

    def find_all(self, name=None, class_=None, limit: int | None = None):
        out = []
        for node in self.descendants():
            if node._matches(name, class_):
                out.append(node)
                if limit is not None and len(out) >= limit:
                    break
        return out

    def find(self, name=None, class_=None):
        found = self.find_all(name, class_, limit=1)
        return found[0] if found else None

    # -- text ---------------------------------------------------------------
    def get_text(self, separator: str = "", strip: bool = False) -> str:
        parts = list(self._text)
        for child in self.children:
            parts.append(child.get_text(separator, strip))
        if strip:
            parts = [p.strip() for p in parts]
        parts = [p for p in parts if p]
        text = separator.join(parts)
        return text.strip() if strip else text

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.name} {self.attrs}>"


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Tag("[document]")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        closes = AUTO_CLOSE.get(self.stack[-1].name)
        if closes and tag in closes:
            self.stack.pop()
        node = Tag(tag, {k: (v if v is not None else "") for k, v in attrs})
        node.parent = self.stack[-1]
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Tag(tag, {k: (v if v is not None else "") for k, v in attrs})
        node.parent = self.stack[-1]
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].name == tag:
                del self.stack[i:]
                return
        # An end tag with no start is markup noise; ignoring it is what browsers do.

    def handle_data(self, data):
        if data.strip():
            self.stack[-1]._text.append(unescape(data))


def parse(markup: str) -> Tag:
    """Parse a document and return its root, which behaves like a Tag."""
    builder = _Builder()
    # Scripts and styles carry brace-heavy text that is never page content and
    # regularly confuses caption extraction.
    markup = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", markup)
    builder.feed(markup)
    builder.close()
    return builder.root


def BeautifulSoup(markup: str, features: str = "html.parser") -> Tag:  # noqa: N802
    """Drop-in entry point, so the caller does not care which parser it got."""
    return parse(markup)

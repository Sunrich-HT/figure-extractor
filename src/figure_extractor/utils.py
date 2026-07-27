"""Source resolution: turn whatever the user pasted into a local file.

Two things went wrong here before. Only ``arxiv.org/abs/`` was normalised, so
OpenReview and ACL Anthology links never reached their PDFs; and when a
download returned something that was not a PDF, the result was silently treated
as HTML, so a blocked request surfaced far downstream as
``Unsupported or unresolved source kind: html`` instead of "the server refused
us".
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Publishers routinely reject unfamiliar agents outright. Presenting a normal
# browser agent is the difference between a 200 and a 403 on most paper hosts.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 figure-extractor/0.2"
)

PDF = "pdf"
HTML = "html"
UNKNOWN = "unknown"


class SourceError(RuntimeError):
    """Raised when a source cannot be retrieved, with the real reason attached."""


@dataclass
class ResolvedSource:
    path: Path
    kind: str
    resolved_url: str
    note: str = ""


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def normalize_source_url(url: str) -> tuple[str, str]:
    """Rewrite a landing-page URL to the artefact it stands for.

    Returns (url, note). Users paste the page they were reading, not the file
    they want; every entry here is a landing page whose PDF lives elsewhere.
    """
    # arXiv abstract page -> PDF (version suffix preserved).
    m = re.match(r"https?://(?:www\.)?arxiv\.org/abs/([^?#]+)", url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}", "arxiv abs -> pdf"

    # arXiv HTML rendering: keep it, it carries the original figure bitmaps.
    if re.match(r"https?://(?:www\.)?arxiv\.org/html/", url):
        return url, "arxiv html kept (original figure assets)"

    # OpenReview forum -> PDF endpoint.
    m = re.match(r"https?://openreview\.net/forum\?(?:.*&)?id=([^&#]+)", url)
    if m:
        return f"https://openreview.net/pdf?id={m.group(1)}", "openreview forum -> pdf"

    # ACL Anthology landing page -> PDF.
    m = re.match(r"https?://(?:www\.)?aclanthology\.org/([^?#]+?)/?$", url)
    if m and not m.group(1).endswith(".pdf"):
        return f"https://aclanthology.org/{m.group(1)}.pdf", "acl anthology -> pdf"

    # Semantic Scholar / bioRxiv full-text pages expose a .full.pdf sibling.
    m = re.match(r"https?://(?:www\.)?(bio|med)rxiv\.org/content/([^?#]+?)(?:\.full)?/?$", url)
    if m and not url.endswith(".pdf"):
        return f"https://www.{m.group(1)}rxiv.org/content/{m.group(2)}.full.pdf", f"{m.group(1)}rxiv -> pdf"

    return url, ""


def sniff_kind(source: str) -> str:
    """Best guess at the artefact type from the URL or path alone."""
    lower = source.lower().split("?")[0].rstrip("/")
    if lower.endswith(".pdf") or "/pdf/" in lower or lower.endswith("/pdf"):
        return PDF
    if lower.endswith((".html", ".htm")):
        return HTML
    if is_url(source):
        # Query-string PDF endpoints (openreview.net/pdf?id=...) land here.
        if re.search(r"/pdf\b", source.lower()):
            return PDF
        return UNKNOWN
    suffix = Path(source).suffix.lower()
    if suffix == ".pdf":
        return PDF
    if suffix in {".html", ".htm"}:
        return HTML
    return UNKNOWN


def download_url(url: str, dest: Path, timeout: int = 90) -> tuple[bytes, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    except urllib.error.HTTPError as exc:
        raise SourceError(
            f"{url} returned HTTP {exc.code} ({exc.reason}). "
            "Publisher sites commonly block automated access; download the PDF "
            "manually and pass the local path instead."
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise SourceError(f"could not fetch {url}: {exc}") from exc
    dest.write_bytes(data)
    return data, ctype


def _looks_like_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def _looks_like_html(data: bytes) -> bool:
    head = data[:1024].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html", b"<?xml")) or b"<html" in head


def ensure_local_source(source: str, workdir: Path) -> ResolvedSource:
    """Resolve a user-supplied source to a local file of a known kind."""
    workdir.mkdir(parents=True, exist_ok=True)

    if not is_url(source):
        path = Path(source)
        if not path.exists():
            raise SourceError(f"no such file: {path}")
        kind = sniff_kind(source)
        if kind == UNKNOWN:
            head = path.read_bytes()[:1024]
            kind = PDF if _looks_like_pdf(head) else (HTML if _looks_like_html(head) else UNKNOWN)
        if kind == UNKNOWN:
            raise SourceError(f"cannot tell whether {path} is a PDF or an HTML document")
        return ResolvedSource(path=path, kind=kind, resolved_url=str(path))

    url, note = normalize_source_url(source)
    expected = sniff_kind(url)
    local = workdir / ("source.pdf" if expected == PDF else "source.html")
    data, ctype = download_url(url, local)

    # Content decides, not the URL — but a mismatch is worth saying out loud,
    # because "expected a PDF and got HTML" usually means we were bounced to a
    # login wall or an interstitial rather than that the paper is an HTML page.
    if _looks_like_pdf(data):
        actual = PDF
    elif _looks_like_html(data) or ctype.startswith("text/html"):
        actual = HTML
    elif ctype == "application/pdf":
        actual = PDF
    else:
        raise SourceError(
            f"{url} returned {len(data)} bytes of {ctype or 'unknown type'}, "
            "which is neither a PDF nor an HTML page"
        )

    if actual != expected and expected == PDF:
        note = (note + "; " if note else "") + (
            f"expected a PDF but the server returned {ctype or 'HTML'} — "
            "this is often a login wall, consent page or bot check"
        )
    if actual == HTML and local.suffix == ".pdf":
        local = local.with_suffix(".html")
        local.write_bytes(data)

    return ResolvedSource(path=local, kind=actual, resolved_url=url, note=note)


def safe_name(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")
    return text[:120] or "file"

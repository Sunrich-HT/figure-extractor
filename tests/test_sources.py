import pytest

from figure_extractor.utils import PDF, SourceError, ensure_local_source, normalize_source_url, sniff_kind


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://arxiv.org/abs/1512.03385", "https://arxiv.org/pdf/1512.03385"),
        ("https://arxiv.org/abs/2404.19756v2", "https://arxiv.org/pdf/2404.19756v2"),
        ("https://openreview.net/forum?id=abc123", "https://openreview.net/pdf?id=abc123"),
        ("https://openreview.net/forum?noteId=x&id=abc123", "https://openreview.net/pdf?id=abc123"),
        ("https://aclanthology.org/2021.findings-acl.100/", "https://aclanthology.org/2021.findings-acl.100.pdf"),
    ],
)
def test_landing_pages_resolve_to_the_pdf(url, expected):
    """Users paste the page they were reading, not the file they want."""
    assert normalize_source_url(url)[0] == expected


def test_arxiv_html_is_kept_as_html():
    url = "https://arxiv.org/html/2404.19756v1"
    assert normalize_source_url(url)[0] == url


def test_already_direct_pdf_urls_are_untouched():
    url = "https://aclanthology.org/2021.findings-acl.100.pdf"
    assert normalize_source_url(url)[0] == url


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/pdf/1512.03385",
        "https://openreview.net/pdf?id=abc123",
        "https://aclanthology.org/2021.findings-acl.100.pdf",
    ],
)
def test_pdf_endpoints_are_recognised(url):
    """`openreview.net/pdf?id=` has no '.pdf' and no '/pdf/' — only '/pdf'."""
    assert sniff_kind(url) == PDF


def test_missing_local_file_raises_a_clear_error(tmp_path):
    with pytest.raises(SourceError, match="no such file"):
        ensure_local_source(str(tmp_path / "nope.pdf"), tmp_path / "work")


def test_unidentifiable_local_file_raises(tmp_path):
    junk = tmp_path / "thing.bin"
    junk.write_bytes(b"\x00\x01\x02not a document")
    with pytest.raises(SourceError, match="cannot tell"):
        ensure_local_source(str(junk), tmp_path / "work")


# --------------------------------------------------------------------------
# What people actually paste: a browser's PDF viewer, not a PDF
# --------------------------------------------------------------------------

def test_browser_pdf_viewer_urls_unwrap_to_the_file():
    """A viewer's address bar carries the real document in a parameter."""
    from figure_extractor.utils import normalize_source_url

    cases = {
        "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html"
        "?file=https%3A%2F%2Farxiv.org%2Fpdf%2F2607.28146v1":
            "https://arxiv.org/pdf/2607.28146v1",
        # Unwrapping composes with the landing-page rules: abs -> pdf.
        "https://mozilla.github.io/pdf.js/web/viewer.html"
        "?file=https%3A%2F%2Farxiv.org%2Fabs%2F1512.03385":
            "https://arxiv.org/pdf/1512.03385",
        "https://docs.google.com/viewer?url=https%3A%2F%2Fexample.org%2Fp.pdf&embedded=true":
            "https://example.org/p.pdf",
        "https://host.tld/web/viewer.html#file=/static/paper.pdf":
            "https://host.tld/static/paper.pdf",
    }
    for given, want in cases.items():
        got, note = normalize_source_url(given)
        assert got == want, f"{given} -> {got}"
        assert "viewer" in note


def test_ordinary_urls_are_left_alone():
    """A ?url= that is not a document must not hijack the source."""
    from figure_extractor.utils import normalize_source_url

    for url in ("https://example.com/blog/post",
                "https://arxiv.org/pdf/2607.28146v1",
                "https://example.com/search?url=cats"):
        got, _ = normalize_source_url(url)
        assert got == url, got

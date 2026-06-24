from figure_extractor.pdf_cropper import CAPTION_RE


def test_caption_regex():
    assert CAPTION_RE.search("Figure 1. Something")
    assert CAPTION_RE.search("Fig. 12: Something")
    assert CAPTION_RE.search("FIGURE 3. Something")

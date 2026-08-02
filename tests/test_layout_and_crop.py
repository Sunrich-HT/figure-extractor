"""Geometry regression tests built on synthetic PDFs.

These exist because the original test suite asserted only that a regex matched
``Figure 1.``, which is true of both a correct extractor and one that crops half
the page. Every test here fails on the pre-rewrite behaviour.
"""

from pathlib import Path

import fitz
import pytest

from figure_extractor.layout import analyze, text_role
from figure_extractor.pdf_cropper import extract_pdf_figures
from figure_extractor.quality import FAILED, OK, assess

LOREM = (
    "Deeper neural networks are more difficult to train. We present a residual "
    "learning framework to ease the training of networks that are substantially "
    "deeper than those used previously. We explicitly reformulate the layers as "
    "learning residual functions with reference to the layer inputs, instead of "
    "learning unreferenced functions. "
)


def _two_column_page(tmp_path):
    """A two-column page: prose on the left, a boxed figure on the right."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Several separate paragraphs per column: column detection measures prose,
    # and two giant text boxes are not enough evidence to find a gutter.
    for i in range(4):
        page.insert_textbox(fitz.Rect(50, 60 + i * 160, 288, 210 + i * 160), LOREM, fontsize=9)
    for i in range(2):
        page.insert_textbox(fitz.Rect(324, 380 + i * 160, 562, 530 + i * 160), LOREM, fontsize=9)
    # The "figure": a drawn box in the right column.
    page.draw_rect(fitz.Rect(340, 90, 545, 300), color=(0, 0, 0), width=1.2)
    page.insert_textbox(
        fitz.Rect(324, 310, 562, 350),
        "Figure 1: A boxed diagram living only in the right column.",
        fontsize=9,
    )
    path = tmp_path / "twocol.pdf"
    doc.save(path)
    return path


def test_columns_are_detected(tmp_path):
    doc = fitz.open(_two_column_page(tmp_path))
    layout, _ = analyze(doc[0])
    assert layout.is_multi_column, "two-column page reported as single column"
    assert len(layout.columns) == 2


def test_crop_stays_inside_its_column(tmp_path):
    """The core failure: a right-column figure absorbing the left column."""
    pdf = _two_column_page(tmp_path)
    manifest = extract_pdf_figures(pdf, tmp_path / "out", dpi=72, make_sheet=False, make_zip=False)
    figs = [f for f in manifest["figures"] if f["kind"] == "figure"]
    assert len(figs) == 1
    x0, _, x1, _ = figs[0]["bbox"]
    assert x0 > 300, f"crop reaches into the left column (x0={x0})"
    assert x1 <= 570
    assert figs[0]["status"] == OK, figs[0]["quality_reasons"]


def test_crop_does_not_swallow_the_neighbouring_caption(tmp_path):
    """Two stacked figures must not claim each other's content."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(80, 60, 530, 200), color=(0, 0, 0), width=1.2)
    page.insert_textbox(fitz.Rect(70, 210, 540, 240), "Figure 1: Upper diagram.", fontsize=9)
    page.draw_rect(fitz.Rect(80, 260, 530, 420), color=(0, 0, 0), width=1.2)
    page.insert_textbox(fitz.Rect(70, 430, 540, 460), "Figure 2: Lower diagram.", fontsize=9)
    pdf = tmp_path / "stacked.pdf"
    doc.save(pdf)

    manifest = extract_pdf_figures(pdf, tmp_path / "out2", dpi=72, make_sheet=False, make_zip=False)
    by_label = {f["label"]: f for f in manifest["figures"]}
    assert set(by_label) == {"Figure 1", "Figure 2"}
    top = by_label["Figure 1"]["bbox"]
    bottom = by_label["Figure 2"]["bbox"]
    # Figure 2's crop must start below Figure 1's caption, not above it.
    assert bottom[1] > top[3], f"Figure 2 crop ({bottom}) overlaps Figure 1 ({top})"


def test_tables_are_extracted_not_just_figures(tmp_path):
    """Regression: table captions were not recognised at all (0/14 recall)."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(70, 60, 540, 90), "Table 1: Results on the benchmark.", fontsize=9)
    for i, y in enumerate(range(110, 210, 24)):
        page.draw_line(fitz.Point(80, y), fitz.Point(530, y))
        page.insert_textbox(fitz.Rect(84, y + 2, 530, y + 20), f"model-{i}    12.3    45.6    78.9", fontsize=8)
    pdf = tmp_path / "table.pdf"
    doc.save(pdf)

    manifest = extract_pdf_figures(pdf, tmp_path / "out3", dpi=72, make_sheet=False, make_zip=False)
    tables = [f for f in manifest["figures"] if f["kind"] == "table"]
    assert len(tables) == 1, manifest["figures"]
    assert tables[0]["status"] != FAILED, tables[0]["quality_reasons"]
    _, y0, _, y1 = tables[0]["bbox"]
    assert y1 - y0 > 40, "table crop collapsed to a sliver"


def test_zero_thickness_rules_are_not_discarded(tmp_path):
    """A perfectly horizontal rule has height 0 and `Rect.is_empty` is True."""
    r = fitz.Rect(10, 100, 400, 100)
    assert r.is_empty  # documents why the naive filter dropped table rules
    from figure_extractor.pdf_cropper import _thicken

    assert _thicken(r).height > 0
    assert _thicken(r).width == pytest.approx(390)


class _FakeBlock:
    def __init__(self, rect, text, n_lines, multi=0, gap=0.0, monospace=False):
        self.rect = rect
        self.text = text
        self.n_lines = n_lines
        self.max_spans_per_line = multi
        self.multi_span_lines = multi
        self.median_span_gap = gap
        self.rotated = False
        self.monospace = monospace


def test_prose_with_inline_math_is_not_mistaken_for_a_table():
    """Justified prose is split into many spans; that alone must not mean table."""
    block = _FakeBlock(fitz.Rect(50, 100, 288, 200), LOREM, n_lines=8, multi=7, gap=0.3)
    assert text_role(block, band_width=238) == "prose"


def test_monospace_prose_is_listing_content_not_a_barrier():
    """A transcript fills its column like a paragraph, but it is a listing's body.

    Classified as prose it becomes a barrier and the listing's own crop stops at
    its first paragraph, which is how Listing 4 of arXiv 2607.28146 was lost.
    """
    block = _FakeBlock(fitz.Rect(50, 100, 288, 200), LOREM, n_lines=8, monospace=True)
    assert text_role(block, band_width=238) == "tabular"


def test_cells_laid_out_side_by_side_are_a_table():
    """21 'lines' inside 67pt cannot be stacked prose — they are cells."""
    cells = "Layer Type Complexity per Layer Sequential Operations Maximum Path Length " * 2
    block = _FakeBlock(fitz.Rect(125, 117, 487, 184), cells, n_lines=21, multi=12, gap=0.3)
    assert text_role(block, band_width=399) == "tabular"


def test_scorer_rejects_a_whole_page_crop():
    page = fitz.Rect(0, 0, 612, 792)
    crop = fitz.Rect(40, 40, 572, 752)
    prose = [fitz.Rect(50, 60, 560, 700)]
    verdict = assess(crop, page, prose, had_graphics=True, band_width=512)
    assert verdict.status != OK, verdict


def test_scorer_reports_failure_when_no_graphics_were_found():
    verdict = assess(fitz.Rect(0, 0, 200, 200), fitz.Rect(0, 0, 612, 792), [], had_graphics=False, band_width=200)
    assert verdict.status == FAILED


def _caption_below_table_page(tmp_path):
    """A table captioned underneath it, with body prose further down the page.

    Reproduces arXiv 2607.28146, where all 13 tables are captioned below and the
    paragraphs beneath the caption sat a point nearer than the table itself.
    """
    pdf = tmp_path / "cap_below.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # A heading above the table, so its top rule is not the topmost thing on the
    # page — a full-width hairline up there is discarded as a running header.
    page.insert_text((60, 76), "4  Results", fontsize=11)
    page.draw_line(fitz.Point(60, 130), fitz.Point(552, 130))
    page.insert_text((70, 152), "Model      Overall   Liberal   Fascist", fontsize=9)
    page.draw_line(fitz.Point(60, 162), fitz.Point(552, 162))
    page.insert_text((70, 182), "GPT-5.4      81%       82%       80%", fontsize=9)
    page.insert_text((70, 198), "Kimi K2.5    76%       73%       85%", fontsize=9)
    page.draw_line(fitz.Point(60, 212), fitz.Point(552, 212))
    page.insert_text((60, 240), "Table 1: Win rates by role, with the caption set "
                                "below the tabular as this paper does.", fontsize=9)
    for i in range(4):
        page.insert_text((60, 290 + i * 90), LOREM[:220], fontsize=9)
        page.insert_text((320, 290 + i * 90), LOREM[:220], fontsize=9)
    doc.save(pdf)
    doc.close()
    return pdf


def test_table_captioned_below_crops_upward(tmp_path):
    """The rules decide the side, not the caption-above convention."""
    pdf = _caption_below_table_page(tmp_path)
    manifest = extract_pdf_figures(pdf, tmp_path / "out", dpi=72,
                                   make_sheet=False, make_zip=False)
    table = next(f for f in manifest["figures"] if f["kind"] == "table")
    x0, y0, x1, y1 = table["bbox"]
    assert y1 <= 240, f"crop must stay above the caption, got {table['bbox']}"
    assert y0 <= 135, f"crop must reach the top rule, got {table['bbox']}"
    assert table["status"] != FAILED, table.get("quality_reasons")


def _page_broken_listing(tmp_path):
    """A transcript that fills page 1 and spills two lines onto page 2.

    The caption follows the spill, so page 2 on its own holds nothing but a
    fragment — the shape of Listing 2 in arXiv 2607.28146.
    """
    pdf = tmp_path / "broken_listing.pdf"
    doc = fitz.open()
    first = doc.new_page(width=612, height=792)
    first.insert_textbox(fitz.Rect(70, 70, 540, 190), LOREM * 2, fontsize=9)
    for i, y in enumerate(range(230, 762, 12)):
        first.insert_text((70, y), f"Alice: turn {i:02d} — I vote JA and keep my word.",
                          fontsize=8, fontname="cour")

    second = doc.new_page(width=612, height=792)
    second.insert_text((70, 80), "Bob: fine, the game ends here.", fontsize=8, fontname="cour")
    second.insert_textbox(fitz.Rect(70, 95, 540, 130),
                          "Listing 1: A transcript broken across the page boundary.",
                          fontsize=9)
    second.insert_textbox(fitz.Rect(70, 150, 540, 300), LOREM * 2, fontsize=9)
    doc.save(pdf)
    doc.close()
    return pdf


def test_exhibit_broken_across_pages_is_stitched(tmp_path):
    """The fragment sharing the caption's page is not the exhibit."""
    pdf = _page_broken_listing(tmp_path)
    manifest = extract_pdf_figures(pdf, tmp_path / "out", dpi=72,
                                   make_sheet=False, make_zip=False)
    item = next(f for f in manifest["figures"] if f["kind"] == "listing")
    assert item["status"] != FAILED, item.get("quality_reasons")

    parts = item.get("parts")
    assert parts, "a page-broken exhibit must record every part it was built from"
    assert [p["page"] for p in parts] == [1, 2], parts
    # The part on page 1 is the body, and it must run to the foot of the column.
    body = parts[0]["bbox"]
    assert body[3] > 700, f"page-1 part stops short of the column foot: {body}"
    assert body[1] > 190, f"page-1 part swallowed the paragraph above it: {body}"
    assert Path(item["output"]).exists()


def test_a_self_contained_exhibit_is_not_stitched(tmp_path):
    """The walk back must not fire for exhibits that are whole on their own page."""
    pdf = _two_column_page(tmp_path)
    manifest = extract_pdf_figures(pdf, tmp_path / "out2", dpi=72,
                                   make_sheet=False, make_zip=False)
    assert all("parts" not in f for f in manifest["figures"]), manifest["figures"]


def test_a_chart_read_as_a_table_does_not_steal_the_caption(tmp_path):
    """Table finders read a gridded bar chart as a table.

    On a page holding a real tabular above its caption and a chart below, the
    chart can be the nearer "detected table" — and it used to win outright,
    handing Table 6 of arXiv 2607.28146 a picture of Figure 3.
    """
    pdf = tmp_path / "chart_and_table.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((60, 80), "4  Results", fontsize=11)
    # The real tabular, captioned underneath it.
    page.draw_line(fitz.Point(60, 120), fitz.Point(552, 120))
    page.insert_text((70, 142), "Model      Overall   Liberal   Fascist", fontsize=9)
    page.draw_line(fitz.Point(60, 152), fitz.Point(552, 152))
    page.insert_text((70, 172), "GPT-5.4      83%       82%       79%", fontsize=9)
    page.insert_text((70, 188), "Kimi K2.5    78%       78%       85%", fontsize=9)
    page.draw_line(fitz.Point(60, 202), fitz.Point(552, 202))
    page.insert_text((60, 230), "Table 1: Endorsement rate, captioned below the tabular.",
                     fontsize=9)
    # A gridded chart further down, which a table finder happily calls a table.
    for i in range(6):
        x = 120 + i * 70
        page.draw_line(fitz.Point(x, 320), fitz.Point(x, 560))
    for i in range(8):
        y = 330 + i * 28
        page.draw_rect(fitz.Rect(120, y, 120 + 40 * (i % 5 + 3), y + 18),
                       color=(0, 0, 0), fill=(0.4, 0.5, 0.7))
    page.insert_text((60, 600), "Figure 1: Distribution of game outcomes.", fontsize=9)
    doc.save(pdf)
    doc.close()

    manifest = extract_pdf_figures(pdf, tmp_path / "out", dpi=72,
                                   make_sheet=False, make_zip=False)
    table = next(f for f in manifest["figures"] if f["kind"] == "table")
    assert table["bbox"][3] <= 232, (
        f"the table's crop reached past its caption into the chart: {table['bbox']}")
    assert table["bbox"][1] <= 125, f"crop missed the tabular's top rule: {table['bbox']}"

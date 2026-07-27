from figure_extractor.captions import Label, count_references, parse_label


def test_plain_captions():
    assert parse_label("Figure 1. Something").display == "Figure 1"
    assert parse_label("Fig. 12: Something").display == "Figure 12"
    assert parse_label("FIGURE 3. Something").display == "Figure 3"
    assert parse_label("Table 4: Results").display == "Table 4"


def test_caption_may_begin_with_any_word():
    """Regression: captions very often open with 'The'.

    Filtering cross references by leading word silently dropped every caption
    starting with a common word, losing Figure 1 of the Transformer paper.
    """
    for text in (
        "Figure 1: The Transformer - model architecture.",
        "Table 2: The Transformer achieves better BLEU scores than previous models.",
        "Figure 5: We show that attention heads specialise.",
        "Table 3: In this ablation we vary the number of heads.",
    ):
        assert parse_label(text) is not None, text


def test_cross_references_are_not_captions():
    assert parse_label("Figure 3 shows that the model converges") is None
    assert parse_label("Table 2 summarises the ablations") is None
    assert parse_label("as shown in Figure 3, the model converges") is None


def test_chapter_and_appendix_numbering_stay_distinct():
    """Regression: the HTML path collapsed 2.1-2.4 onto one filename."""
    labels = [parse_label(f"Figure {n}: caption") for n in ("2.1", "2.2", "2.3", "2.4", "B.1", "D.3", "S1")]
    assert all(lab is not None for lab in labels)
    slugs = [lab.slug for lab in labels]
    assert len(set(slugs)) == len(slugs), slugs
    assert "." not in "".join(slugs)


def test_sort_key_orders_numerically_and_puts_appendix_last():
    labels = [Label("figure", n) for n in ("2.10", "2.2", "B.1", "1")]
    ordered = [lab.number for lab in sorted(labels, key=lambda x: x.sort_key)]
    assert ordered == ["1", "2.2", "2.10", "B.1"]


def test_reference_counting():
    body = "As Figure 3 shows ... we revisit Fig. 3 later ... unlike Figure 4."
    assert count_references(body, Label("figure", "3")) == 2
    assert count_references(body, Label("figure", "4")) == 1

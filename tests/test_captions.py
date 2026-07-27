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


def test_journal_prefixes_are_part_of_the_identity():
    """`Extended Data Fig. 1` is not `Fig. 1`, and must not overwrite it."""
    plain = parse_label("Figure 1: body figure.")
    extended = parse_label("Extended Data Fig. 1 | different figure.")
    supp = parse_label("Supplementary Figure 1: another one.")
    assert plain and extended and supp
    assert len({plain.slug, extended.slug, supp.slug}) == 3


def test_kinds_beyond_figures_and_tables():
    for text, kind in [
        ("Scheme 1. Synthetic route.", "scheme"),
        ("Algorithm 1 Training loop", "algorithm"),
        ("Listing 1: Reference implementation.", "listing"),
        ("Box 1 | Key definitions.", "box"),
        ("Chart 2 | Market share.", "chart"),
    ]:
        label = parse_label(text)
        assert label is not None and label.kind == kind, text


def test_nature_pipe_separator_and_cjk_labels():
    assert parse_label("Fig. 1 | Overview of the method.").display == "Figure 1"
    assert parse_label("图 1: 模型总体架构").kind == "figure"
    assert parse_label("表 2. 消融实验结果").kind == "table"


def test_body_exhibits_sort_before_supplementary():
    labels = [parse_label(t) for t in (
        "Supplementary Figure 1: s.", "Figure 2: b.", "Extended Data Fig. 1 | e.", "Figure 1: a.",
    )]
    ordered = [lab.display for lab in sorted(labels, key=lambda x: x.sort_key)]
    assert ordered == ["Figure 1", "Figure 2", "Extended Data Figure 1", "Supplementary Figure 1"]


def test_panel_reference_is_not_a_caption():
    """Regression: a verb hidden behind a panel reference slipped through.

    `Fig. 6 (middle) shows ...` begins with the label and its first token is
    `(middle)`, so checking only the first word accepted it as a caption and
    invented an eighth figure in a seven-figure paper.
    """
    assert parse_label("Fig. 6 (middle) shows the behaviors of ResNets.") is None
    assert parse_label("Fig. 4 (a) illustrates the pipeline") is None
    assert parse_label("Table 1 in the appendix reports full numbers") is None
    # ...while a genuinely space-separated caption still parses.
    assert parse_label("Algorithm 1 Training loop") is not None


def test_a_lowercase_continuation_is_a_cross_reference():
    """Found in the wild: "Figure 3 reveals ..." was accepted as a caption.

    A verb blacklist is inherently incomplete. A caption's title starts like a
    title — capital, digit or CJK — while a cross reference continues the
    sentence with a lowercase word.
    """
    for text in (
        "Figure 3 reveals similar qualitative patterns in real data",
        "Figure 2 exhibits the same trend",
        "Table 5 tabulates the ablations",
        "Figure 1 and Figure 2 together imply",
    ):
        assert parse_label(text) is None, text

    for text in (
        "Algorithm 1 Training loop",
        "Fig. 1 Overview of the method",
        "图 1 模型总体架构",
    ):
        assert parse_label(text) is not None, text

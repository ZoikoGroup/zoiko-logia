"""Tests for the dataset artifact every visual is derived from.

The property under test throughout: a visual kind is decided by preconditions
over the dataset's shape, never by asking a model what to draw. That is what
makes the selection hold across an unbounded query mix — query types are
open-ended, dataset shapes are a small closed set.
"""
from app.orchestration.dataset import (
    Dataset,
    DatasetColumn,
    build_dataset,
    parse_numeric,
    select_visual_kind,
    validate_dataset,
)
from app.orchestration.presentation import build_answer_presentation


def _dataset(headers, rows, **kwargs):
    return build_dataset(dataset_id="D1", title=headers[0], headers=headers, rows=rows, **kwargs)


# ── Column typing ────────────────────────────────────────────────────────


def test_units_are_declared_per_column():
    dataset = _dataset(["Segment", "Revenue"], [["Retail", "$50"], ["Wholesale", "$30"]])
    assert dataset.columns[0].dtype == "category"
    assert dataset.columns[1] == DatasetColumn(name="Revenue", dtype="numeric", unit="USD")


def test_a_year_label_column_is_temporal_not_a_measure():
    # Charting the year as a series is the classic mistake.
    dataset = _dataset(["Year", "Rate"], [["2024", "25%"], ["2025", "25%"], ["2026", "25%"]])
    assert dataset.columns[0].dtype == "temporal"
    assert dataset.numeric_columns == (1,)


def test_an_incomplete_column_stays_textual_and_is_not_plottable():
    dataset = _dataset(["Segment", "Revenue"], [["Retail", "$50"], ["Wholesale", "not disclosed"]])
    assert dataset.columns[1].dtype == "text"
    assert dataset.numeric_columns == ()


def test_a_mixed_unit_column_stays_textual():
    dataset = _dataset(["Segment", "Amount"], [["Retail", "$50"], ["Wholesale", "30%"]])
    assert dataset.columns[1].dtype == "text"


def test_currency_symbols_and_codes_normalise_to_one_unit():
    dataset = _dataset(["Segment", "Revenue"], [["A", "$50"], ["B", "100 USD"]])
    assert dataset.units == frozenset({"USD"})


def test_parenthesised_and_signed_negatives_parse():
    assert parse_numeric("(1,200)") == ("-1200", "")
    assert parse_numeric("-£1,200.50") == ("-1200.50", "£")
    assert parse_numeric("not a number") is None


# ── Validation ───────────────────────────────────────────────────────────


def test_mixed_units_across_columns_is_a_validation_failure():
    """Plotting GBP beside a percentage is the most common silently-wrong
    chart in financial reporting, and nothing checked it before."""
    dataset = _dataset(
        ["Segment", "Revenue", "Share"],
        [["Retail", "$50", "60%"], ["Wholesale", "$30", "40%"]],
    )
    codes = {issue.code for issue in validate_dataset(dataset)}
    assert "mixed_units" in codes
    assert select_visual_kind(dataset).kind == "table"


def test_ragged_rows_are_rejected():
    dataset = Dataset(
        dataset_id="D1", title="t",
        columns=(DatasetColumn("A", "category"), DatasetColumn("B", "numeric")),
        rows=(("x", "1"), ("y",)),
    )
    assert "ragged_rows" in {issue.code for issue in validate_dataset(dataset)}


def test_an_empty_dataset_is_rejected():
    dataset = Dataset(dataset_id="D1", title="t", columns=(DatasetColumn("A", "category"),), rows=())
    assert "empty_dataset" in {issue.code for issue in validate_dataset(dataset)}


def test_provenance_is_only_required_when_asked_for():
    dataset = _dataset(["Segment", "Revenue"], [["Retail", "$50"], ["Wholesale", "$30"]])
    assert validate_dataset(dataset) == ()
    assert "provenance_missing" in {
        issue.code for issue in validate_dataset(dataset, require_provenance=True)
    }


def test_a_row_without_a_citation_blocks_the_visual_when_provenance_is_required():
    dataset = _dataset(
        ["Segment", "Revenue"], [["Retail", "$50"], ["Wholesale", "$30"]],
        row_provenance=[("REF-1",), ()],
    )
    assert dataset.unsupported_rows() == (1,)
    decision = select_visual_kind(dataset, require_provenance=True)
    assert decision.kind == "table"
    assert "rows_without_citation" in decision.reasons


def test_every_row_cited_permits_the_visual():
    dataset = _dataset(
        ["Segment", "Revenue"], [["Retail", "$50"], ["Wholesale", "$30"]],
        row_provenance=[("REF-1",), ("REF-2",)],
    )
    assert select_visual_kind(dataset, require_provenance=True).kind == "bar"


def test_provenance_length_must_match_the_row_count():
    dataset = _dataset(
        ["Segment", "Revenue"], [["Retail", "$50"], ["Wholesale", "$30"]],
        row_provenance=[("REF-1",)],
    )
    assert "provenance_row_mismatch" in {issue.code for issue in validate_dataset(dataset)}


# ── Kind selection ───────────────────────────────────────────────────────


def test_a_temporal_axis_selects_a_trend_not_a_comparison():
    dataset = _dataset(["Quarter", "Revenue"], [["Q1", "$100"], ["Q2", "$120"], ["Q3", "$140"]])
    assert select_visual_kind(dataset).kind == "area"


def test_multiple_series_over_time_selects_line():
    dataset = _dataset(
        ["Quarter", "Budget", "Actual"],
        [["Q1", "$1", "$2"], ["Q2", "$3", "$4"], ["Q3", "$5", "$6"]],
    )
    assert select_visual_kind(dataset).kind == "line"


def test_a_categorical_axis_selects_bar():
    dataset = _dataset(["Segment", "Revenue"], [["Retail", "$50"], ["Wholesale", "$30"]])
    assert select_visual_kind(dataset).kind == "bar"


def test_percentage_units_select_a_composition_without_any_hint():
    # Percentages ARE a property of the data, so no hint is needed.
    dataset = _dataset(["Segment", "Share"], [["Retail", "60%"], ["Wholesale", "40%"]])
    assert select_visual_kind(dataset).kind == "donut"


def test_two_currency_values_are_a_comparison_unless_intent_says_otherwise():
    """Whether two non-negative values are a composition or a magnitude
    comparison is a fact about the reader, not the numbers."""
    dataset = _dataset(["Segment", "Revenue"], [["Retail", "$60"], ["Wholesale", "$40"]])
    assert select_visual_kind(dataset).kind == "bar"
    assert select_visual_kind(dataset, presentation_hint="compositional").kind == "donut"


def test_a_hint_cannot_promote_a_dataset_past_a_precondition():
    # The data decides what is drawable; intent only picks among the drawable.
    dataset = _dataset(["Standard", "Treatment"], [["IFRS 16", "On balance"], ["ASC 842", "Dual"]])
    assert select_visual_kind(dataset, presentation_hint="compositional").kind == "table"
    mixed = _dataset(
        ["Segment", "Revenue", "Share"],
        [["Retail", "$50", "60%"], ["Wholesale", "$30", "40%"]],
    )
    assert select_visual_kind(mixed, presentation_hint="compositional").kind == "table"


def test_one_row_is_a_metric_not_a_chart():
    dataset = _dataset(["Metric", "Value"], [["Total revenue", "$482,000"]])
    decision = select_visual_kind(dataset)
    assert decision.kind == "metric"
    assert "single_row" in decision.reasons


def test_too_many_rows_falls_back_to_a_table_with_a_stated_reason():
    rows = [[f"Item {index}", f"${index}"] for index in range(20)]
    decision = select_visual_kind(_dataset(["Item", "Amount"], rows))
    assert decision.kind == "table"
    assert "too_many_rows" in decision.reasons


def test_a_declined_chart_always_states_why():
    """A missing visual must be explainable, not mysterious."""
    dataset = _dataset(["Standard", "Treatment"], [["IFRS 16", "x"], ["ASC 842", "y"]])
    decision = select_visual_kind(dataset)
    assert decision.kind == "table"
    assert decision.reasons and all(isinstance(reason, str) for reason in decision.reasons)
    assert not decision.renders_chart


def test_no_kind_is_ever_absent():
    # A caller must never have to handle a missing decision — a dataset that
    # supports no chart still supports a table.
    for headers, rows in (
        (["A", "B"], [["x", "y"]]),
        (["A", "B"], [["x", "1"], ["y", "2"]]),
        (["A", "B", "C"], [["x", "1", "q"]]),
    ):
        assert select_visual_kind(_dataset(headers, rows)).kind in {
            "metric", "bar", "line", "area", "donut", "table",
        }


# ── Reproducibility ──────────────────────────────────────────────────────


def test_the_content_hash_covers_the_data_and_not_the_envelope():
    """A cache keyed on this must hit when the same figures recur. Ids and
    titles vary between requests carrying identical data; including a fetch
    timestamp — the obvious mistake — would make the hit rate zero."""
    left = build_dataset(dataset_id="A", title="One", headers=["S", "R"], rows=[["x", "1"]])
    right = build_dataset(dataset_id="B", title="Two", headers=["S", "R"], rows=[["x", "1"]])
    assert left.content_hash == right.content_hash


def test_different_data_hashes_differently():
    left = _dataset(["S", "R"], [["x", "1"]])
    right = _dataset(["S", "R"], [["x", "2"]])
    assert left.content_hash != right.content_hash


def test_a_unit_change_alone_changes_the_hash():
    # $1 and 1% are different facts even though the digits match.
    assert _dataset(["S", "R"], [["x", "$1"]]).content_hash != _dataset(
        ["S", "R"], [["x", "1%"]]
    ).content_hash


def test_truncation_is_recorded_rather_than_silent():
    dataset = build_dataset(
        dataset_id="D1", title="Items", headers=["Item", "Amount"],
        rows=[["a", "1"], ["b", "2"]], total_row_count=340,
    )
    assert dataset.is_truncated
    assert "340" in _fallback_of(dataset)


def _fallback_of(dataset):
    from app.orchestration.presentation import _dataset_text_fallback
    return _dataset_text_fallback(dataset)


# ── Integration with the existing presentation contract ─────────────────


def test_blocks_are_emitted_alongside_the_existing_contract():
    answer = (
        "Revenue by segment.\n\n"
        "| Segment | Revenue |\n| --- | --- |\n| Retail | $50 |\n| Wholesale | $30 |\n"
    )
    presentation = build_answer_presentation(
        "Show me a chart of revenue by segment", answer, citation_refs=["REF-1"],
    )
    assert presentation.charts, "the existing chart contract must still be populated"
    assert len(presentation.blocks) == 1
    block = presentation.blocks[0]
    assert block.kind == "bar"
    assert block.dataset_id == "answer-dataset-1"
    assert len(block.dataset_hash) == 64
    assert block.citations == ["REF-1"]
    assert block.text_fallback


def test_a_block_is_emitted_even_when_no_chart_is_produced():
    """The block is what makes a declined visual explainable — so it exists
    for text-only tables too."""
    answer = (
        "| Standard | Treatment |\n| --- | --- |\n"
        "| IFRS 16 | On balance sheet |\n| ASC 842 | Dual model |\n"
    )
    presentation = build_answer_presentation("Compare IFRS 16 and ASC 842", answer)
    assert presentation.charts == []
    assert [block.kind for block in presentation.blocks] == ["table"]
    assert "no_complete_numeric_column" in presentation.blocks[0].reasons


def test_a_mixed_unit_table_reports_the_reason_in_its_block():
    answer = (
        "| Segment | Revenue | Share |\n| --- | --- | --- |\n"
        "| Retail | $50 | 60% |\n| Wholesale | $30 | 40% |\n"
    )
    presentation = build_answer_presentation("chart of revenue and share", answer)
    assert presentation.blocks[0].kind == "table"
    assert "mixed_units" in presentation.blocks[0].reasons


def test_an_answer_with_no_table_emits_no_blocks():
    presentation = build_answer_presentation("Explain accruals", "Accrual accounting recognises...")
    assert presentation.blocks == []


def test_the_classifier_hint_reaches_the_kind_decision():
    answer = (
        "| Segment | Revenue |\n| --- | --- |\n| Retail | $60 |\n| Wholesale | $40 |\n"
    )
    without = build_answer_presentation("chart revenue by segment", answer)
    with_hint = build_answer_presentation(
        "chart revenue by segment", answer, presentation_hint="compositional",
    )
    assert without.blocks[0].kind == "bar"
    assert with_hint.blocks[0].kind == "donut"
    # ...and the rendered chart agrees with the block.
    assert with_hint.charts[0].type == "donut"


def test_the_same_answer_produces_the_same_blocks_every_time():
    # Determinism is required both for the cache key and for an audit export
    # to be comparable to what the user saw.
    answer = "| Quarter | Revenue |\n| --- | --- |\n| Q1 | $1 |\n| Q2 | $2 |\n| Q3 | $3 |\n"
    first = build_answer_presentation("revenue trend", answer)
    second = build_answer_presentation("revenue trend", answer)
    assert first.blocks == second.blocks


def test_an_ordinal_label_column_is_not_mistaken_for_a_date_axis():
    """A column headed "Year" holding 1, 2, 3 — MACRS recovery years — is an
    ordinal sequence, not a date axis. The values override the header: the
    dataset previously claimed an area chart here while the chart builder
    correctly declined to draw one, so the emitted block and the rendered
    chart disagreed."""
    dataset = _dataset(["Year", "Rate"], [["1", "20%"], ["2", "32%"], ["3", "19.2%"]])
    decision = select_visual_kind(dataset)
    assert decision.kind == "table"
    assert "no_usable_axis" in decision.reasons


def test_four_digit_years_are_still_a_real_date_axis():
    dataset = _dataset(["Year", "Rate"], [["2024", "25%"], ["2025", "25%"], ["2026", "25%"]])
    assert select_visual_kind(dataset).kind == "area"


def test_a_numeric_label_column_never_plots_a_measure_against_itself():
    dataset = _dataset(["Item", "Amount"], [["1", "$10"], ["2", "$20"]])
    assert select_visual_kind(dataset).reasons == ("no_usable_axis",)


def test_the_block_and_the_rendered_chart_always_agree():
    """The one invariant that matters across every shape: a block claiming a
    chart kind must correspond to a chart actually being emitted."""
    answers = [
        ("Chart the rate by recovery year",
         "| Year | Rate |\n| --- | --- |\n| 1 | 20% |\n| 2 | 32% |\n"),
        ("Chart revenue by quarter",
         "| Quarter | Revenue |\n| --- | --- |\n| Q1 | $1 |\n| Q2 | $2 |\n| Q3 | $3 |\n"),
        ("Chart the breakdown of revenue by segment",
         "| Segment | Revenue |\n| --- | --- |\n| Retail | $60 |\n| Wholesale | $40 |\n"),
        ("Chart revenue and margin percentage",
         "| Segment | Revenue | Margin |\n| --- | --- | --- |\n| A | $1 | 10% |\n| B | $2 | 20% |\n"),
        ("Compare the two standards",
         "| Standard | Treatment |\n| --- | --- |\n| A | full |\n| B | reduced |\n"),
    ]
    for query, answer in answers:
        presentation = build_answer_presentation(query, answer)
        block = presentation.blocks[0]
        claims_chart = block.kind in {"bar", "line", "area", "donut"}
        assert claims_chart == bool(presentation.charts), (
            f"{query!r}: block says {block.kind} but charts={len(presentation.charts)}"
        )

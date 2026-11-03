"""
Regression suite for charting the user's OWN uploaded documents.

Two things are being protected here, and the second matters more than the
first: that a readable table becomes a chart, and that an unreadable or
ambiguous one becomes NOTHING. Empty evidence lands on the existing "I
couldn't retrieve verified data for this chart request" message, which is the
correct outcome — a wrong chart is worse than no chart, because a chart is
read as fact at a glance.
"""
from app.orchestration.document_evidence import build_document_evidence
from app.orchestration.websearch import WebSource


def _doc(snippet: str, title: str = "management-accounts.xlsx") -> list[WebSource]:
    return [WebSource(title=title, url="", snippet=snippet, provider="uploaded_document")]


_ASSETS = (
    "Asset\tCost\tDepreciation\tNBV\n"
    "Plant\t180000\t60000\t120000\n"
    "Vehicles\t55,000\t20,000\t35,000\n"
    "IT Equipment\t42000\t18000\t24000\n"
    "Total\t277000\t98000\t179000\n"
)


# ── the feature ──────────────────────────────────────────────────────────

def test_spreadsheet_table_becomes_chart_observations():
    evidence = build_document_evidence("compare asset types in a bar chart", _doc(_ASSETS))

    assert [o.dimension for o in evidence.observations] == ["Plant", "Vehicles", "IT Equipment"]
    assert [o.value for o in evidence.observations] == [180000.0, 55000.0, 42000.0]
    assert evidence.provider == "uploaded_document"


def test_unformatted_and_grouped_numbers_both_parse():
    """A spreadsheet exports 180000; a rendered PDF shows 180,000. Matching
    only the grouped form silently dropped every raw spreadsheet figure."""
    evidence = build_document_evidence("chart this", _doc(_ASSETS))
    values = {o.dimension: o.value for o in evidence.observations}

    assert values["Plant"] == 180000.0      # unformatted
    assert values["Vehicles"] == 55000.0    # comma-grouped


def test_first_numeric_column_is_used_consistently():
    """Cost/Depreciation/NBV would interleave three different series if the
    column were chosen per row. One table, one measure."""
    evidence = build_document_evidence("chart this", _doc(_ASSETS))

    assert all(o.measure == "value" for o in evidence.observations)
    assert [o.value for o in evidence.observations] == [180000.0, 55000.0, 42000.0]


def test_pdf_style_whitespace_table_parses():
    evidence = build_document_evidence("show assets as a chart", _doc(
        "Asset class        Value\n"
        "Land and buildings   450,000\n"
        "Machinery            120,500\n"
    ))

    assert [o.dimension for o in evidence.observations] == ["Land and buildings", "Machinery"]


def test_parenthesised_negatives_keep_their_sign():
    """Accounting convention: (15,000) is a negative. Read as positive it
    flips a loss into a gain."""
    evidence = build_document_evidence("chart this", _doc(
        "Machinery            120,500\n"
        "Impairment           (15,000)\n"
    ))
    values = {o.dimension: o.value for o in evidence.observations}

    assert values["Impairment"] == -15000.0


def test_subject_reads_as_a_title_not_the_raw_question():
    evidence = build_document_evidence("compare different types of assets in bar chart", _doc(_ASSETS))

    assert evidence.subject == "Different types assets"


# ── failing closed ───────────────────────────────────────────────────────

def test_total_row_is_never_charted_beside_its_own_components():
    """A total is a different kind of quantity from the rows it summarises.
    Plotted as a peer it double-counts the series and dwarfs every other bar."""
    evidence = build_document_evidence("chart this", _doc(_ASSETS))

    assert "Total" not in [o.dimension for o in evidence.observations]


def test_prose_with_no_table_yields_nothing():
    assert build_document_evidence("chart this", _doc("The company performed well this year.")).observations == []


def test_single_data_row_yields_nothing():
    assert build_document_evidence("chart this", _doc("Asset\tValue\nPlant\t100\n")).observations == []


def test_repeated_label_with_conflicting_values_yields_nothing():
    """Either the same row arrived twice from overlapping chunks, or two
    different things share a name. Summing them would invent a figure that
    appears nowhere in the document."""
    assert build_document_evidence("chart this", _doc("A\t10\nB\t20\nA\t99\n")).observations == []


def test_no_documents_yields_nothing():
    assert build_document_evidence("chart this", []).observations == []


def test_header_words_are_not_treated_as_categories():
    evidence = build_document_evidence("chart this", _doc(_ASSETS))
    labels = {o.dimension.casefold() for o in evidence.observations}

    assert "asset" not in labels
    assert "category" not in labels


# ── a workbook of several sheets (QA group D, fixture F0) ────────────────

def _f0() -> list[WebSource]:
    return [
        WebSource(title="F0.xlsx — 'Statements'!1:5", url="", provider="uploaded_document",
                  snippet="Measure\tFY2024 / Opening\tFY2025 / Closing\nRevenue\t8000\t10000\n"
                          "Cost of goods sold\t5000\t6200\nDeferred revenue\t300\t400\nEquity\t2700\t3600"),
        WebSource(title="F0.xlsx — 'Quarterly revenue'!1:5", url="", provider="uploaded_document",
                  snippet="Quarter\tFY2025 revenue (USD thousands)\nQ1\t2100\nQ2\t2300\nQ3\t2500\nQ4\t3100"),
    ]


def _values(query: str) -> list[tuple[str, float]]:
    return [(o.dimension, o.value) for o in build_document_evidence(query, _f0()).observations]


def test_each_sheet_is_its_own_section_and_the_quarters_are_charted_alone():
    # D01 charted twenty bars: every statement line beside the four quarters.
    quarters = [("Q1", 2100.0), ("Q2", 2300.0), ("Q3", 2500.0), ("Q4", 3100.0)]
    assert _values("Plot F0 2025 quarterly revenue as a bar chart.") == quarters
    assert _values("Present the Q1-Q4 chart for a screen-reader user.") == quarters


def test_the_named_lines_of_the_year_asked_are_charted():
    # D04 would have charted FY2024's 8,000 and every statement line.
    assert _values("Chart FY2025 revenue, COGS and gross profit.") == [("Revenue", 10000.0),
                                                                      ("Cost of goods sold", 6200.0)]


def test_quarters_read_from_a_file_are_described_as_a_series_with_their_changes():
    # D01/D02: "These are separate line items, not a series over time" under Q1–Q4,
    # and "label Q4 QoQ growth" got no growth figure.
    from app.orchestration.service import _grounded_domain_fallback
    query = "Make a line chart of quarterly revenue and label Q4 QoQ growth."
    text = _grounded_domain_fallback(query, build_document_evidence(query, _f0()))
    assert "Q4 3,100 (+24.00% on Q3)" in text and "Q2 2,300 (+9.52% on Q1)" in text
    assert "not a series over time" not in text


def test_d03_a_waterfall_is_the_signed_profit_and_loss_bridge_only():
    # D03 stacked all sixteen statement lines, cash and equity included, to 34,100.
    from app.orchestration.service import _grounded_domain_fallback
    statement = WebSource(
        title="F0.xlsx — 'Statements'!1:8", url="", provider="uploaded_document",
        snippet="Measure\tFY2024 / Opening\tFY2025 / Closing\nRevenue\t8000\t10000\nCost of goods sold\t5000\t6200\n"
                "Depreciation\tNot prescribed\t400\nIncome tax expense\tNot prescribed\t300\nCash\t700\t1200\n"
                "Deferred revenue\t300\t400\nEquity\t2700\t3600")
    flows = WebSource(title="F0.xlsx — 'Cash flow and equity'!1:2", url="", provider="uploaded_document",
                      snippet="Item\tFY2025 (USD thousands)\nNet income\t3100")
    query = "Build a waterfall from FY2025 revenue to net income."
    evidence = build_document_evidence(query, [statement, flows])
    assert [(o.dimension, o.value) for o in evidence.observations] == [
        ("Revenue", 10000.0), ("Cost of goods sold", -6200.0), ("Depreciation", -400.0), ("Income tax expense", -300.0)]
    assert "it ends at 3,100, the net result" in _grounded_domain_fallback(query, evidence)
    # Steps that do not reach the file's own net income are not drawn as a bridge.
    wrong = WebSource(title=flows.title, url="", provider="uploaded_document",
                      snippet="Item\tFY2025 (USD thousands)\nNet income\t900")
    assert all(o.value >= 0 for o in build_document_evidence(query, [statement, wrong]).observations)


def test_d03_a_bridge_caption_names_its_end_result_not_its_last_step():
    # "decreased from 10000 (Revenue) to -300 (Income tax expense)" stood under the waterfall.
    from app.orchestration.evidence import EvidenceModel, Observation
    from app.orchestration.visualization.orchestrator import _summarize_series
    steps = [("Revenue", 10000), ("Cost of goods sold", -6200), ("Expenses", -2100), ("Depreciation", -400),
             ("Interest", -100), ("Income tax expense", -300)]
    evidence = EvidenceModel(observations=[Observation(dimension=d, value=v, measure="value") for d, v in steps],
                             dimensions=["category"], measures=["value"])
    caption = _summarize_series("Revenue to net income", evidence, None)
    assert caption == "Revenue to net income: starts at 10,000 (Revenue) and, after 5 steps, ends at 900."


def test_d06_an_accessible_presentation_gets_alt_text_and_the_table_route():
    # D06's chart narration had no alternative text and no keyboard / screen-reader route.
    from app.orchestration.service import _grounded_domain_fallback
    query = "Present the Q1-Q4 chart for mobile and a keyboard-only screen-reader user."
    text = _grounded_domain_fallback(query, build_document_evidence(query, _f0()))
    assert "**Alternative text:** a chart of 4 values in order: Q1 2,100, Q2 2,300, Q3 2,500, Q4 3,100." in text
    assert "screen reader" in text and "nothing is shown by colour alone" in text
    plain = "Plot F0 2025 quarterly revenue as a bar chart."
    assert "Alternative text" not in _grounded_domain_fallback(plain, build_document_evidence(plain, _f0()))

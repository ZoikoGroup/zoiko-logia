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

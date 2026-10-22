"""A requested chart type that was not drawn is named, with the reason."""
import json

from app.orchestration.chart_substitution import drawn_chart_types, substitution_note


def _fence(kind: str) -> str:
    return "```chart\n" + json.dumps({"type": kind, "title": "AAPL vs MSFT"}) + "\n```"


def test_a_pie_request_drawn_as_a_line_chart_says_why():
    note = substitution_note("compare the last 10 days aapl and microsoft stock prices in pie chart", "", _fence("line"))
    assert note.startswith("You asked for a pie chart; a line chart is shown instead")
    assert "comparison over time" in note


def test_no_note_when_the_requested_type_was_drawn_or_none_was_asked():
    assert substitution_note("show expenses by category as a pie chart", _fence("pie")) == ""
    assert substitution_note("show revenue as a bar chart", _fence("bar")) == ""
    assert substitution_note("compare aapl and msft prices", _fence("line")) == ""
    assert substitution_note("show it as a pie chart", "no chart here") == ""


def test_a_line_request_drawn_as_bars_is_named():
    assert "a bar chart is shown instead" in substitution_note("show monthly sales as a line chart", _fence("bar"))


def test_chart_types_are_read_from_fences():
    assert drawn_chart_types("text " + _fence("line") + _fence("line"), _fence("bar")) == ["line", "bar"]
    assert drawn_chart_types("```chart\nnot json\n```") == []

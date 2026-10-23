"""A Gantt chart from tasks written as people write them (kroki_diagrams._natural_tasks)."""
from datetime import date

from app.orchestration.kroki_diagrams import _extract_tasks, _natural_tasks, extract_kroki_graph

AUDIT = ("Show the year-end audit plan as a Gantt chart: Planning 1–10 Jan, Fieldwork 11 Jan–15 Feb, "
         "Review 16–28 Feb, Report 1–10 Mar.")


def test_commas_month_ranges_and_no_year_are_read():
    # This drew no Gantt chart; a bar chart of durations was shown instead.
    assert _natural_tasks(AUDIT.split(":", 1)[1], today=date(2026, 10, 23)) == [
        "Planning: 2026-01-01 to 2026-01-10", "Fieldwork: 2026-01-11 to 2026-02-15",
        "Review: 2026-02-16 to 2026-02-28", "Report: 2026-03-01 to 2026-03-10"]
    assert extract_kroki_graph(AUDIT) is not None


def test_a_range_past_december_starts_the_year_before_and_the_strict_form_still_works():
    assert _natural_tasks("Close books 20 Dec to 5 Jan", today=date(2026, 10, 23)) == [
        "Close books: 2025-12-20 to 2026-01-05"]
    assert _extract_tasks("Gantt chart: Planning: 2026-01-01 to 2026-01-10; Fieldwork: 2026-01-11 to 2026-02-15") == [
        "Planning: 2026-01-01 to 2026-01-10", "Fieldwork: 2026-01-11 to 2026-02-15"]


def test_tasks_without_dates_draw_nothing():
    assert _extract_tasks("Show this as a Gantt chart: Planning soon, Fieldwork later") is None

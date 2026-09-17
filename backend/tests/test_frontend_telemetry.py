"""
Regression suite for the frontend visualization-interaction telemetry
function backing POST /orchestration/telemetry — a closed event/category
vocabulary logged structurally (see frontend_telemetry.py's docstring for
why this is separate from the hash-chained audit ledger).
"""
import json
import logging

from app.orchestration.visualization.frontend_telemetry import log_frontend_interaction


def test_recognized_event_is_accepted_and_logged(caplog):
    with caplog.at_level(logging.INFO, logger="kriton.frontend_interaction"):
        accepted = log_frontend_interaction(
            event="view_selected", category="chart",
            visualization_id="spec-1", visualization_type="LINE", renderer="RECHARTS",
            detail={"from": "LINE", "to": "BAR"},
        )
    assert accepted is True
    record = json.loads(caplog.records[0].message)
    assert record["event"] == "view_selected"
    assert record["category"] == "chart"
    assert record["detail"] == {"from": "LINE", "to": "BAR"}


def test_unrecognized_event_name_is_rejected_not_logged(caplog):
    with caplog.at_level(logging.INFO, logger="kriton.frontend_interaction"):
        accepted = log_frontend_interaction(event="clicked_random_thing", category="chart")
    assert accepted is False
    assert len(caplog.records) == 0


def test_unrecognized_category_is_rejected():
    assert log_frontend_interaction(event="render_failed", category="widget") is False


def test_all_documented_categories_accepted():
    for category in ("chart", "graph", "flow"):
        assert log_frontend_interaction(event="interacted", category=category) is True

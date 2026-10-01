import json

import pytest

from app.domains.model_gateway.tools.chart_tool import ChartToolError, build_chart_fence


def test_valid_bar_chart_becomes_exact_fence_the_frontend_parses():
    args = json.dumps({
        "type": "bar",
        "title": "GDP growth",
        "categories": ["2023", "2024", "2025"],
        "series": [{"name": "UK", "data": [0.27, 1.08, 1.39]}],
    })
    fence = build_chart_fence(args)
    assert fence.startswith("```chart\n")
    assert fence.endswith("\n```")
    payload = json.loads(fence.removeprefix("```chart\n").removesuffix("\n```"))
    assert payload["type"] == "bar"
    assert payload["categories"] == ["2023", "2024", "2025"]
    assert payload["stacked"] is False


def test_stacked_flag_dropped_for_non_bar_types():
    args = json.dumps({
        "type": "pie",
        "title": "Expense split",
        "data": [{"name": "COGS", "value": 60}, {"name": "Admin", "value": 25}],
    })
    payload = json.loads(build_chart_fence(args).removeprefix("```chart\n").removesuffix("\n```"))
    assert "stacked" not in payload


def test_sankey_requires_nodes_and_links():
    args = json.dumps({"type": "sankey", "title": "Flow"})
    with pytest.raises(ChartToolError):
        build_chart_fence(args)


def test_unknown_chart_type_is_rejected():
    args = json.dumps({"type": "gauge", "title": "UK inflation vs target"})
    with pytest.raises(ChartToolError):
        build_chart_fence(args)


def test_malformed_json_is_rejected():
    with pytest.raises(ChartToolError):
        build_chart_fence("{not valid json")


def test_missing_required_field_is_rejected():
    args = json.dumps({"type": "bar", "title": "Revenue"})  # no categories/series
    with pytest.raises(ChartToolError):
        build_chart_fence(args)

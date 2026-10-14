"""QA 3 — exact result and formula version recorded; prose == chart == receipt."""
from agt01_support import call, reply, run

CHART = {"type": "line", "title": "Operating margin (%)", "categories": ["FY2024", "FY2025"],
         "series": [{"name": "Margin", "data": [12.0, 12.5]}]}


async def test_the_golden_case_is_verified_end_to_end():
    outcome, trace, _ = await run([
        reply(calls=[call("c1", "calculate", {"expression": "120000 / 1000000 * 100", "label": "FY2024 margin"}),
                     call("c2", "calculate", {"expression": "150000 / 1200000 * 100", "label": "FY2025 margin"})]),
        reply(calls=[call("c3", "calculate", {"expression": "12.5 - 12", "label": "Change (pp)"})]),
        reply(calls=[call("c4", "render_chart", CHART)]),
        reply("Operating margin rose from 12.0% to 12.5%, up 0.5 pp."),
    ])
    receipts = {r["label"]: r for r in outcome.calculation_receipts}
    assert receipts["FY2024 margin"]["result"] == "12" and receipts["FY2025 margin"]["result"] == "12.5"
    assert receipts["Change (pp)"]["result"] == "0.5"
    assert all(r["formula_version"] and r["input_hash"] for r in receipts.values())
    assert [r.calculation_id for r in trace if r.tool == "calculate"] == [r["calculation_id"] for r in outcome.calculation_receipts]
    assert outcome.unreconciled_figures == [] and len(outcome.artifacts) == 1
    assert '"data": [12.0, 12.5]' in outcome.artifacts[0] or "12.5" in outcome.artifacts[0]

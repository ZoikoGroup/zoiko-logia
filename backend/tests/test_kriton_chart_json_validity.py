"""
```kriton-chart``` blocks must be valid JSON matching {type, labels, series} —
the frontend (ask-kriton/page.tsx's KritonChart) does a bare JSON.parse() on
the fence content with no tolerance for anything else.

Regression test for a real, reported failure: asked for "a chart of the EITC
maximum credit amount by number of qualifying children," the model wrote a
Markdown TABLE inside the ```kriton-chart``` fence instead of JSON — parsing
failed outright, "Chart data could not be parsed." Root cause: unlike TABLE
and FLOWCHART, CHART never had its own syntax rule in format_intent.py
showing the model the required schema. First fix attempt got the JSON
*structure* right but still embedded [REF-N] markers and currency symbols
inside the values array (e.g. "values": [$3,526 [REF-3], ...]) — also invalid
JSON. Fixed by adding an explicit right-vs-wrong example naming that exact
failure mode.

Real API calls, no mocking — the point is verifying the model actually
follows the instruction on live, varied queries, which a mocked response
can't demonstrate.

Run with: python tests/test_kriton_chart_json_validity.py
"""
import asyncio
import json
import os
import re
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.core.database import AsyncSessionLocal, SessionLocal
from app.orchestration.service import ask_kriton
from app.orchestration.schemas import AskKritonRequest

_CHART_FENCE = re.compile(r"```kriton-chart\n(.*?)\n```", re.DOTALL)

# Queries expected to retrieve genuine multi-point numeric data and produce
# a chart — if a query stops producing a chart at all (context changed),
# that's a retrieval issue to investigate separately, not a failure of this
# test's actual concern (JSON validity of whatever chart IS produced).
QUERIES = [
    "Show me a chart of the EITC maximum credit amount by number of qualifying children",
    "Plot a chart comparing the global intangible low-taxed income and foreign-derived intangible income deduction figures",
]


async def _ask(query: str):
    async with AsyncSessionLocal() as db:
        sync_db = SessionLocal()
        try:
            request = AskKritonRequest(query=query, jurisdiction="", mode="Workflow")
            return await ask_kriton(
                db, sync_db,
                actor_id="test-actor", tenant_id="test-tenant-chart-json",
                role="Admin", request=request,
                idempotency_key=f"test-{uuid.uuid4().hex[:8]}",
            )
        finally:
            sync_db.close()


def _validate_chart_json(text: str) -> tuple[bool, str]:
    match = _CHART_FENCE.search(text)
    if match is None:
        return True, "no kriton-chart block present (not a failure of this test)"
    try:
        spec = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        return False, f"invalid JSON: {e}"
    if not isinstance(spec, dict) or "labels" not in spec or "series" not in spec:
        return False, f"missing required keys: {spec}"
    if spec.get("type") not in ("bar", "line"):
        return False, f"type must be 'bar' or 'line', got {spec.get('type')!r}"
    for series in spec["series"]:
        for value in series.get("values", []):
            if not isinstance(value, (int, float)):
                return False, f"non-numeric value in series {series.get('name')!r}: {value!r}"
    return True, "valid"


async def test_kriton_chart_blocks_are_valid_json():
    if not os.environ.get("GROQ_API_KEY"):
        print("test_kriton_chart_blocks_are_valid_json: SKIPPED (no GROQ_API_KEY)")
        return
    for query in QUERIES:
        response = await _ask(query)
        text = response.answer.text if response.answer else ""
        ok, detail = _validate_chart_json(text)
        status = "OK" if ok else "WRONG"
        print(f"{status}: {query!r} -> {detail}")
        assert ok, f"{query!r} produced an invalid kriton-chart block: {detail}"
    print("test_kriton_chart_blocks_are_valid_json: PASSED")


async def main():
    await test_kriton_chart_blocks_are_valid_json()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())

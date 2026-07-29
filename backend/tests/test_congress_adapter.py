import pytest

from app.domains.reference_data.adapters.congress_adapter import (
    CongressAPIError,
    get_bill,
    normalize_bill_payload,
)
from app.domains.reference_data.models import ReferenceSourceBundle
from app.domains.reference_data.service import (
    CONGRESS_GOVERNED_SOURCE_ID,
    extract_congress_bill_identifier,
    to_congress_rag_chunk,
)
from app.orchestration.retrieve import infer_category


def test_extracts_complete_house_bill_identifier():
    assert extract_congress_bill_identifier(
        "What is the status of H.R. 1 in the 119th Congress?"
    ) == (119, "hr", 1)


def test_extracts_joint_resolution_identifier():
    assert extract_congress_bill_identifier(
        "Summarize H.J.Res. 12 from the 118th Congress"
    ) == (118, "hjres", 12)


def test_refuses_to_guess_missing_congress_number():
    assert extract_congress_bill_identifier("What is the status of H.R. 1?") is None


def test_normalizes_bill_and_latest_summary():
    normalized = normalize_bill_payload(
        {
            "bill": {
                "congress": 119,
                "type": "HR",
                "number": "1",
                "title": "Example Tax Act",
                "introducedDate": "2025-01-03",
                "latestAction": {"actionDate": "2025-02-01", "text": "Passed House"},
                "policyArea": {"name": "Taxation"},
                "laws": [],
                "url": "https://api.congress.gov/v3/bill/119/hr/1",
            }
        },
        {
            "summaries": [
                {"updateDate": "2025-01-05", "text": "<p>Old summary</p>"},
                {"updateDate": "2025-02-02", "text": "<p>Latest summary</p>"},
            ]
        },
    )
    assert normalized["title"] == "Example Tax Act"
    assert normalized["summary"] == "<p>Latest summary</p>"


def test_rag_chunk_contains_grounded_bill_facts_and_strips_html():
    bundle = ReferenceSourceBundle(
        source_name="Congress.gov — Bill Lookup",
        source_url="https://www.congress.gov/bill/119th-congress/house-bill/1",
        data=[{
            "congress": 119, "bill_type": "HR", "bill_number": "1",
            "title": "Example Tax Act", "introduced_date": "2025-01-03",
            "policy_area": "Taxation", "latest_action": {},
            "summary": "<p>Changes a <strong>tax</strong> rule.</p>", "laws": [],
        }],
    )
    chunk = to_congress_rag_chunk(bundle, source_id=CONGRESS_GOVERNED_SOURCE_ID)
    assert chunk["metadata"]["source_id"] == CONGRESS_GOVERNED_SOURCE_ID
    assert "Changes a tax rule." in chunk["text"]
    assert "<p>" not in chunk["text"]


@pytest.mark.asyncio
async def test_adapter_rejects_invalid_bill_type_before_network():
    with pytest.raises(CongressAPIError, match="Invalid"):
        await get_bill(119, "invalid", 1)


def test_bill_query_routes_to_us_legislation():
    assert infer_category("What is the status of H.R. 1 in the 119th Congress?") == "us-legislation"

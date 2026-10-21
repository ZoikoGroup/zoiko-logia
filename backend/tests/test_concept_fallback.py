"""A concept question the sources do not cover gets a labelled general
explanation instead of "Not answered" (concept_fallback.py)."""
from unittest.mock import AsyncMock

from app.orchestration.concept_fallback import general_explanation, is_concept_question

FAILURE = "Kriton is temporarily unable to reach the language model provider."


def test_only_plain_concept_questions_qualify():
    plain = dict(has_documents=False, uses_live_data=False)
    assert is_concept_question("give me the difference between audit and account", **plain)
    assert is_concept_question("What is IPR?", **plain)
    assert is_concept_question("Explain accrual accounting", **plain)
    # figures, rules, live data or a file keep the sources-only answer
    assert not is_concept_question("What is the VAT registration threshold?", **plain)
    assert not is_concept_question("What is 18% of 50,000?", **plain)
    assert not is_concept_question("Explain the TDS rules for rent", **plain)
    assert not is_concept_question("What is audit?", has_documents=True, uses_live_data=False)
    assert not is_concept_question("What is the dollar rate?", has_documents=False, uses_live_data=True)
    assert not is_concept_question("Prepare a balance sheet", **plain)


async def test_the_explanation_is_used_only_without_figures_or_citations():
    good = "Accounting records and reports transactions; an audit independently examines those records."
    assert await general_explanation("audit vs accounting", AsyncMock(return_value=good), FAILURE) == good
    for bad in ("The audit threshold is £10,200,000.", "Under section 143 an audit…", "Audit is done [REF-1].",
                "VAT is 20% in the UK.", FAILURE, "ok"):
        assert await general_explanation("q", AsyncMock(return_value=bad), FAILURE) == ""
    assert await general_explanation("q", AsyncMock(side_effect=RuntimeError("down")), FAILURE) == ""

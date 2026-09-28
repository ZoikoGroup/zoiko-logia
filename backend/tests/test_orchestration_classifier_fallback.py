from app.domains.risk_safety.schemas import SafetyDecision
from app.orchestration.service import _classification_allowed


def test_provider_resolves_only_ml_uncertainty():
    uncertain = SafetyDecision(
        allowed=False,
        risk_level="MEDIUM",
        route="CLARIFICATION",
        rules_applied=["l2-classification-uncertain"],
    )
    assert not _classification_allowed(uncertain, None)
    assert _classification_allowed(uncertain, "LOW")

    other_block = SafetyDecision(
        allowed=False,
        risk_level="RESTRICTED",
        route="REFUSAL",
        rules_applied=["l0-privacy-block"],
    )
    assert not _classification_allowed(other_block, "LOW")

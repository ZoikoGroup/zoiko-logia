"""A HIGH-risk question about the user's attached file is prepared from it."""
from app.orchestration.service import _high_risk_instruction


def test_with_an_attached_file_the_model_prepares_what_was_asked():
    instruction = _high_risk_instruction(True)
    assert "Prepare exactly what is asked" in instruction and "verified figures" in instruction
    assert "Do not certify" in instruction
    assert "Do NOT make the decision" not in instruction


def test_without_a_file_it_stays_general_guidance():
    instruction = _high_risk_instruction(False)
    assert "Give general guidance only" in instruction and "Do NOT make the decision" in instruction

"""
Pure unit tests for the 2026-07-22 product vision doc's domain-restriction
gate (app/orchestration/prescreen.py::check_off_topic_domain) and
topic-based professional referral mapping
(app/orchestration/professional_referral.py). See memory:
product-vision-kriton-tutor-not-search.
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.orchestration.prescreen import check_off_topic_domain
from app.orchestration.professional_referral import referral_for_category, referral_message


def test_off_topic_direct_requests_are_caught():
    assert check_off_topic_domain("Explain chemistry.") == "chemistry"
    assert check_off_topic_domain("Teach me physics.") == "physics"
    assert check_off_topic_domain("What is biology?") == "biology"
    print("test_off_topic_direct_requests_are_caught: PASSED")


def test_off_topic_gate_does_not_block_real_accounting_questions():
    """Deliberately narrow (exact-match) design — a real accounting
    question that happens to mention a science word in passing, or a
    substantive question about an in-domain topic, must never be blocked."""
    assert check_off_topic_domain(
        "How does the R&D tax credit apply to chemistry research costs?"
    ) is None
    assert check_off_topic_domain("What is the standard deduction?") is None
    assert check_off_topic_domain("Explain double-entry bookkeeping.") is None
    assert check_off_topic_domain("What is the history of ASC 606?") is None
    print("test_off_topic_gate_does_not_block_real_accounting_questions: PASSED")


def test_referral_mapping_matches_vision_doc_table():
    assert "tax" in referral_for_category("tax").lower()
    assert "auditor" in referral_for_category("audit").lower()
    assert "accountant" in referral_for_category("standards").lower() or "cpa" in referral_for_category("standards").lower()
    assert "lawyer" in referral_for_category("us-legislation").lower()
    print("test_referral_mapping_matches_vision_doc_table: PASSED")


def test_referral_falls_back_to_generic_for_unmapped_category():
    assert referral_for_category("some-future-category-not-yet-mapped") == "a qualified accounting or tax professional"
    print("test_referral_falls_back_to_generic_for_unmapped_category: PASSED")


def test_referral_message_names_the_professional():
    message = referral_message("audit")
    assert "auditor" in message.lower()
    assert message.strip().endswith(".")
    print("test_referral_message_names_the_professional: PASSED")


if __name__ == "__main__":
    test_off_topic_direct_requests_are_caught()
    test_off_topic_gate_does_not_block_real_accounting_questions()
    test_referral_mapping_matches_vision_doc_table()
    test_referral_falls_back_to_generic_for_unmapped_category()
    test_referral_message_names_the_professional()
    print("All tests passed successfully!")

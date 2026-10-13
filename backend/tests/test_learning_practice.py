"""Practice quizzes: questions from the knowledge-base question banks, marked
against each case's key facts (app/domains/learning_cpd/practice.py)."""
import pytest
from fastapi import HTTPException

from app.domains.learning_cpd.practice import BANKS, _cases, check_answer, draw_questions, list_banks


def test_only_the_practice_banks_are_offered_never_the_holdout():
    assert {b["id"] for b in list_banks()} == {"uk-vat", "india-gst"}
    assert all(b["questionCount"] > 0 for b in list_banks())
    assert not any("holdout" in file for file, _, _ in BANKS.values())


@pytest.mark.parametrize("bank_id", list(BANKS))
def test_every_question_accepts_an_answer_stating_its_key_facts(bank_id):
    # A question the marker could never accept would be unanswerable.
    for case in _cases(bank_id):
        answer = " ".join((case.get("must_contain") or []) + (case.get("must_contain_any") or [])[:1])
        assert check_answer(bank_id, case["id"], answer)["correct"], case["id"]


def test_drawn_questions_never_carry_the_expected_facts():
    drawn = draw_questions("uk-vat", 5, seed=1)
    assert len(drawn) == 5 and len({q["id"] for q in drawn}) == 5
    assert all(set(q) == {"id", "question", "category"} for q in drawn)


def test_question_count_is_bounded():
    assert len(draw_questions("uk-vat", 500, seed=1)) == 10
    assert len(draw_questions("india-gst", 0, seed=1)) == 1


def test_marking_matches_facts_however_the_number_is_written():
    for answer in ("The threshold is £90,000.", "It's 90000 a year", "about 90 000 of taxable turnover"):
        assert check_answer("uk-vat", "vat-reg-threshold", answer)["correct"], answer


def test_a_wrong_or_empty_answer_is_marked_wrong_with_what_was_missing():
    wrong = check_answer("uk-vat", "vat-reg-threshold", "It is £85,000")
    assert not wrong["correct"] and wrong["missing"] == ["90,000"] and wrong["expected"] == ["90,000"]
    assert wrong["source"] == "HMRC guidance on GOV.UK"
    assert not check_answer("uk-vat", "vat-reg-threshold", "   ")["correct"]


def test_any_of_alternatives_need_only_one_match():
    result = check_answer("uk-vat", "vat-voluntary", "Yes, you can register voluntarily.")
    assert result["correct"]
    assert not check_answer("uk-vat", "vat-voluntary", "No.")["correct"]


def test_unknown_bank_or_question_is_not_found():
    for call in (lambda: draw_questions("us-sales-tax"), lambda: check_answer("uk-vat", "nope", "x")):
        with pytest.raises(HTTPException) as err:
            call()
        assert err.value.status_code == 404

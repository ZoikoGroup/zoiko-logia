"""Practice quizzes for Learning & Practice.

Questions come from Kriton's own knowledge-base question banks in
backend/evals/ (UK VAT, India GST). Each case lists the key facts a correct
answer must contain; a learner's free-text answer is marked against those
facts the same way run_baseline_eval.py marks Kriton's answers.

Only the practice banks are used. uk_vat_holdout.json is deliberately NOT
exposed: it is the held-out set that measures Kriton on questions nothing
was tuned against, and must stay unseen.

The expected facts never leave the server until an answer is checked, so a
quiz cannot be read from the question list.
"""
from __future__ import annotations

import json
import random
import re
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

_EVALS = Path(__file__).resolve().parents[3] / "evals"

# bank id -> (file, title, source note shown with each answer)
BANKS: dict[str, tuple[str, str, str]] = {
    "uk-vat": ("uk_vat_questions.json", "UK VAT", "HMRC guidance on GOV.UK"),
    "india-gst": ("india_gst_questions.json", "India GST", "GST Council FAQs on the September 2025 rate changes"),
}
MAX_QUESTIONS = 10

_DIGIT_COMMA = re.compile(r"(?<=\d)[,\s](?=\d{3}\b)")


def _normalise(text: str) -> str:
    """Lower-case, and write 90,000 / 90 000 as 90000, so a fact matches
    however the learner formats the number."""
    return _DIGIT_COMMA.sub("", (text or "").lower()).replace("‑", "-")


@lru_cache(maxsize=None)
def _cases(bank_id: str) -> tuple[dict, ...]:
    if bank_id not in BANKS:
        raise HTTPException(status_code=404, detail="Unknown practice bank")
    data = json.loads((_EVALS / BANKS[bank_id][0]).read_text(encoding="utf-8"))
    return tuple(
        case for case in data.get("cases", [])
        if case.get("outcome") == "answered" and (case.get("must_contain") or case.get("must_contain_any"))
    )


def list_banks() -> list[dict]:
    return [
        {"id": bank_id, "title": title, "questionCount": len(_cases(bank_id)), "source": source}
        for bank_id, (_, title, source) in BANKS.items()
    ]


def draw_questions(bank_id: str, count: int = 5, seed: int | None = None) -> list[dict]:
    """A random set of questions, without their expected facts."""
    cases = list(_cases(bank_id))
    picked = random.Random(seed).sample(cases, min(max(count, 1), MAX_QUESTIONS, len(cases)))
    return [{"id": c["id"], "question": c["question"], "category": c.get("category", "")} for c in picked]


def check_answer(bank_id: str, question_id: str, answer: str) -> dict:
    case = next((c for c in _cases(bank_id) if c["id"] == question_id), None)
    if case is None:
        raise HTTPException(status_code=404, detail="Unknown question")
    text = _normalise(answer)
    required = case.get("must_contain") or []
    any_of = case.get("must_contain_any") or []
    missing = [fact for fact in required if _normalise(fact) not in text]
    any_ok = not any_of or any(_normalise(fact) in text for fact in any_of)
    return {
        "correct": bool(text.strip()) and not missing and any_ok,
        "expected": required,
        "acceptedAlternatives": any_of,
        "missing": missing + ([] if any_ok else ["one of: " + ", ".join(any_of)]),
        "source": BANKS[bank_id][2],
    }

"""Does the answer address the question that was asked?

"How much VAT do I owe, and can I deduct all my expenses?", asked right after
an IFRS / US GAAP inventory question in the same chat, was answered with the
IAS 2 / ASC 330 comparison again. Every sentence was cited and true, so the
release check passed it — it was the answer to a different question.

A small fixed vocabulary of accounting topics is matched in the question and
the answer. When the question names topics and the answer is about another
topic none of them share, the answer is off-topic. A question naming no
listed topic is never judged.
"""
from __future__ import annotations

import re

_TOPICS: dict[str, re.Pattern] = {name: re.compile(pattern, re.I) for name, pattern in {
    "indirect_tax": r"\b(?:vat|gst|sales tax|input tax|output tax|reverse charge|hmrc)\b",
    "inventory": r"\b(?:inventor(?:y|ies)|ias\s?2\b|asc\s?330|net realisable value|net realizable value|nrv|lower of cost)",
    "presentation": r"\b(?:ifrs\s?18|ias\s?1\b|presentation of financial statements|management[- ]defined performance)",
    "leases": r"\b(?:ifrs\s?16|asc\s?842|leases?|right[- ]of[- ]use)\b",
    "revenue_recognition": r"\b(?:ifrs\s?15|asc\s?606|revenue recognition|performance obligations?)\b",
    "payroll": r"\b(?:payroll|paye|national insurance|provident fund|esic?|gratuity|salary slip)\b",
    "income_tax": r"\b(?:corporation tax|income tax|tax slabs?|tds)\b",
    "depreciation": r"\b(?:depreciation|ias\s?16|useful life|residual value)\b",
    "exchange_rates": r"\b(?:exchange rates?|eur/gbp|usd/inr|fx rates?)\b",
    "inflation": r"\b(?:inflation|cpi|consumer price index)\b",
    "financial_instruments": r"\b(?:ifrs\s?9|expected credit loss|ecl)\b",
}.items()}
# An answer's topic is one it is substantially about, not a passing mention.
_MIN_ANSWER_MENTIONS = 3


def topics_in(text: str, *, min_mentions: int = 1) -> set[str]:
    return {name for name, pattern in _TOPICS.items() if len(pattern.findall(text or "")) >= min_mentions}


def off_topic(question: str, answer: str) -> bool:
    """True when the answer is about a topic the question does not ask about
    and covers none of the topics the question does ask about."""
    asked = topics_in(question)
    if not asked or not (answer or "").strip():
        return False
    answered = topics_in(answer, min_mentions=_MIN_ANSWER_MENTIONS)
    covered = topics_in(answer)
    return bool(answered) and not (answered & asked) and not (covered & asked)


def recompose_instruction(question: str) -> str:
    return (
        "\n\n=== Your previous draft answered a different question ===\n"
        "It addressed a topic the current question does not ask about. Answer ONLY this question, "
        f"on its own:\n{question}\n"
        "Use only the evidence above that bears on it. If the evidence does not answer part of it, say so "
        "for that part, and ask for any information the question itself says is needed."
    )

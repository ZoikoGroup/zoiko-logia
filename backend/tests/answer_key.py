"""Grading an answer against a hand-derived answer key (review questions,
22 Oct 2026).

A key lists, per point, regular expressions of which one must appear
(`expect`) and, per scenario, statements that contradict a correct answer
(`contradictions`: a known wrong value or reasoning). Numbers match only as
whole numbers ("500,000" is not found in "1,500,000"). Passing means the
answer states the expected results and none of the known errors; it does not
prove the reasoning correct, and keyword points (controls, VIE) show coverage
only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "review_questions_20261022.json"


@dataclass
class Grade:
    missing: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.missing and not self.contradictions


def load() -> dict:
    return json.loads(FIXTURE.read_text())


# A number grouped with spaces ("400 000", "7 900 000", "306 353.6"; ordinary,
# no-break, narrow no-break or thin spaces) is the same number as "400,000".
# The 23 Oct hedge answer wrote every amount this way and would have been
# graded as missing them. Only whole groups of three after a 1-3 digit lead:
# "2027 100 barrels" is two numbers and stays so.
_SPACE_GROUPED = re.compile(r"(?<![\d.,])\d{1,3}(?:[    ]\d{3})+(?![\d])")


def normalise_numbers(text: str) -> str:
    """The answer with space-grouped thousands written with commas. Values,
    decimals and signs are unchanged."""
    return _SPACE_GROUPED.sub(lambda m: re.sub(r"[    ]", ",", m.group(0)), text or "")


def grade(answer: str, name: str, review: dict | None = None) -> Grade:
    review = review or load()
    text = normalise_numbers(answer)
    result = Grade()
    for label, patterns in review["answer_keys"][name].items():
        if not any(re.search(pattern, text, re.I) for pattern in patterns):
            result.missing.append(label)
    for label, pattern in review.get("contradictions", {}).get(name, {}).items():
        if re.search(pattern, text, re.I):
            result.contradictions.append(label)
    return result

"""Verifiable GRPO tasks. No self-grading LLM or thumbs-up rewards."""
from __future__ import annotations

import json
import random
from decimal import Decimal, InvalidOperation

from app.orchestration.calculation_service import evaluate_expression


def completion_text(completion) -> str:
    if isinstance(completion, str):
        return completion
    if isinstance(completion, list) and len(completion) == 1 and isinstance(completion[0], dict) and completion[0].get("role") == "assistant":
        return completion[0].get("content", "")
    return ""


def exact_result_reward(completions, expected, **kwargs) -> list[float]:
    """Full JSON parsing prevents rewarding a correct number hidden in wrong prose.

    Only exact finite answers earn a reward. This checks arithmetic, not tax
    expertise, safe tool use, citations, or general factual correctness.
    """
    if len(completions) != len(expected):
        raise ValueError("Reward labels and completions must align")
    rewards = []
    for completion, target in zip(completions, expected):
        reward = 0.0
        try:
            def pairs(items):
                if len(items) != len({k for k, _ in items}):
                    raise ValueError("Duplicate JSON keys")
                return dict(items)
            text = completion_text(completion)
            if len(text) > 256:
                raise ValueError("Oversized answer")
            obj = json.loads(text, object_pairs_hook=pairs, parse_float=Decimal)
            if isinstance(obj, dict) and set(obj) == {"answer"} and not isinstance(obj["answer"], bool):
                result, reference = Decimal(str(obj["answer"])), Decimal(str(target))
                if result.is_finite() and reference.is_finite() and result == reference:
                    reward = 1.0
        except (ValueError, TypeError, InvalidOperation):
            pass
        rewards.append(reward)
    return rewards


def arithmetic_tasks(*, count: int = 1000, seed: int = 42) -> list[dict]:
    if not 10 <= count <= 100000:
        raise ValueError("Task count must be between 10 and 100000")
    rng = random.Random(seed)
    rows, seen = [], set()
    while len(rows) < count:
        amount, rate, cost = rng.randint(100, 100000), rng.randint(1, 40), rng.randint(1, 99)
        family = len(rows) % 3
        if family == 0:
            expression = f"{amount} * {rate} / 100"
            question = f"Calculate {rate}% of {amount}."
        elif family == 1:
            expression = f"{amount} * (1 + {rate} / 100)"
            question = f"Increase {amount} by {rate}%."
        else:
            expression = f"{amount} - {cost}"
            question = f"Subtract {cost} from {amount}."
        if expression in seen:
            continue
        seen.add(expression)
        rows.append({"id": f"arithmetic-{len(rows)}", "group": expression,
                     "prompt": [{"role": "user", "content": question +
                                 ' Return only JSON with one key "answer" containing the exact numeric result.'}],
                     "expected": str(evaluate_expression(expression)), "expression": expression})
    return rows

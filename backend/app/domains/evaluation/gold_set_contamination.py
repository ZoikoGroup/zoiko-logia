"""Deterministic leakage checks between development and release holdouts."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


_SPACE = re.compile(r"\s+")


def normalized_text(value: str) -> str:
    return _SPACE.sub(" ", value.casefold()).strip()


def case_fingerprint(
    *, query_text: str, document_family: str | None, source_refs: list[str] | None,
) -> str:
    material = "|".join([
        normalized_text(query_text),
        (document_family or "").casefold().strip(),
        ",".join(sorted(source_refs or [])),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ContaminationReport:
    status: str
    collisions: list[dict[str, str]]


def scan_cases(candidate_cases, comparison_cases) -> ContaminationReport:
    comparison = {case.fingerprint: case for case in comparison_cases if case.fingerprint}
    collisions = []
    for case in candidate_cases:
        other = comparison.get(case.fingerprint)
        if other is not None and other.id != case.id:
            collisions.append({"case_id": case.id, "conflicts_with": other.id})
    return ContaminationReport(
        status="FAILED" if collisions else "PASSED", collisions=collisions,
    )

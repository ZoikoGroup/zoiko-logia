"""Exact citation spans (ZL-ENG-AGT-01 §06.4, App. B3 `permitted_span`).

A citation used to resolve only to a whole passage. For each answer sentence
that cites [REF-n], this finds the sentence inside REF-n's evidence text that
supports it (most shared content words) and records its character offsets,
so a reviewer or auditor lands on the exact supporting text. Deterministic;
a sentence with too little overlap gets no span rather than a wrong one.
"""
from __future__ import annotations

import re

_REF = re.compile(r"\[(REF-\d+)\]")
# A full stop ends a sentence only before whitespace or the end, so "1.5%"
# and "£1.6m." stay whole.
_SENTENCE = re.compile(r"(?:[^.!?\n]|[.!?](?=\S))+(?:[.!?]+|$)")
_WORD = re.compile(r"[a-z0-9£$€₹%][a-z0-9£$€₹%.,]*", re.I)
_STOP = frozenset("the a an and or of to in on for is are be by with as at from that this it its your you".split())
MIN_OVERLAP = 0.3


def _words(text: str) -> set[str]:
    return {w.lower().strip(".,") for w in _WORD.findall(text or "") if w.lower() not in _STOP and len(w) > 1}


def exact_spans(answer: str, evidence: dict[str, str]) -> dict[str, list[dict]]:
    """{ref_id: [{"start", "end", "overlap"}]} for every cited claim with a
    supporting sentence in that reference's evidence text."""
    spans: dict[str, list[dict]] = {}
    for claim in _SENTENCE.findall(answer or ""):
        refs = _REF.findall(claim)
        claim_words = _words(_REF.sub(" ", claim))
        if not refs or not claim_words:
            continue
        for ref in dict.fromkeys(refs):
            text = evidence.get(ref)
            if not text:
                continue
            best = None
            for match in _SENTENCE.finditer(text):
                words = _words(match.group(0))
                if not words:
                    continue
                overlap = len(claim_words & words) / len(claim_words)
                if best is None or overlap > best[0]:
                    best = (overlap, match.start(), match.end())
            if best and best[0] >= MIN_OVERLAP:
                span = {"start": best[1], "end": best[2], "overlap": round(best[0], 2)}
                if span not in spans.setdefault(ref, []):
                    spans[ref].append(span)
    return spans


def evidence_by_ref(lines: list[str]) -> dict[str, str]:
    """"[REF-3] text…" evidence lines → {"REF-3": "text…"} (first wins)."""
    found: dict[str, str] = {}
    for line in lines:
        match = re.match(r"\s*\[(REF-\d+)\]\s*(.*)", line or "", re.S)
        if match and match.group(1) not in found:
            found[match.group(1)] = match.group(2)
    return found

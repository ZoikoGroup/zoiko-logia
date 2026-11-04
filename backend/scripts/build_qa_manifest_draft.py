"""Builds a DRAFT machine-readable manifest of the 72-case chatbot QA pack
(prerequisite P5 for WF-01 A3) from the question bank document, and the
planned-observation baseline derived from it (3 Nov 2026).

  * Every field is read from the document; nothing is inferred. Each case keeps
    its exact text and a SHA-256 of it.
  * Planned repetitions follow WF-01: P0 x5, other priorities x3.
  * Every planned observation is NOT_RUN. This is a derived plan, not the
    supplied 292-row baseline (which was not found), and it is not release
    evidence: status DRAFT_UNRATIFIED until QA Automation ratifies it.
  * The P0 count and total observations are reported as found. A difference
    from WF-01's stated 38 P0 / 292 observations is recorded, not corrected.

    python3 scripts/build_qa_manifest_draft.py QUESTION_BANK.docx
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "evals" / "qa_pack_72_manifest.DRAFT.json"
_SUITE = re.compile(r"^\d+\.\d+\s+Suite\s+([A-Z])\s+[—-]\s+(.+)$")
_CASE = re.compile(r"^([A-Z]\d{2})\s+\|\s+(.+?)\s+\[(P\d)\s*•\s*([^\]]+)\]\s*$")
REPEATS = {"P0": 5}
DEFAULT_REPEATS = 3


def _text(path: Path) -> str:
    raw = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "ignore")
    raw = re.sub(r"</w:p>", "\n", raw)
    raw = re.sub(r"</w:tc>", " | ", raw)
    raw = re.sub(r"<w:(?:tab|br|cr)\b[^>]*/>", " ", raw)
    text = html.unescape(re.sub(r"<[^>]+>", "", raw))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def build(source: Path) -> dict:
    lines = _text(source).splitlines()
    suites, cases, suite, current = {}, [], None, None
    for line in lines:
        if found := _SUITE.match(line):
            suite = found.group(1)
            suites[suite] = found.group(2)
            current = None
            continue
        if found := _CASE.match(line):
            current = {"case_id": found.group(1), "suite": suite, "title": found.group(2),
                       "priority": found.group(3), "fixture": found.group(4).strip(), "body": []}
            cases.append(current)
            continue
        if current is not None and not re.match(r"^\d+\s*$", line):
            if re.match(r"^\d+(?:\.\d+)?\s+[A-Z]", line) and not line.startswith(current["case_id"]):
                current = None     # the next numbered section ends the case
                continue
            current["body"].append(line)
    for case in cases:
        body = "\n".join(case.pop("body"))
        case["text"] = body
        case["text_sha256"] = hashlib.sha256(f"{case['case_id']}|{case['title']}|{body}".encode()).hexdigest()
        case["planned_repetitions"] = REPEATS.get(case["priority"], DEFAULT_REPEATS)
    ids = [c["case_id"] for c in cases]
    p0 = sum(c["priority"] == "P0" for c in cases)
    planned = sum(c["planned_repetitions"] for c in cases)
    findings = []
    if len(ids) != len(set(ids)):
        findings.append(f"duplicate case ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    if len(cases) != 72:
        findings.append(f"{len(cases)} cases found, the document states 72")
    if p0 != 38:
        findings.append(f"{p0} P0 cases found, WF-01 states 38")
    if planned != 292:
        findings.append(f"{planned} planned observations derived, WF-01 states 292")
    return {
        "status": "DRAFT_UNRATIFIED",
        "release_evidence": False,
        "source": {"file": f"external:{source.name}", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        "repetition_rule": "P0 x5, other priorities x3 (WF-01 screen 04.03)",
        "counts": {"cases": len(cases), "p0": p0, "planned_observations": planned,
                   "by_priority": {p: sum(c["priority"] == p for c in cases) for p in sorted({c["priority"] for c in cases})}},
        "findings": findings,
        "suites": suites,
        "cases": cases,
        "planned_observations": [{"case_id": c["case_id"], "repetition": r, "status": "NOT_RUN"}
                                 for c in cases for r in range(1, c["planned_repetitions"] + 1)],
    }


if __name__ == "__main__":
    manifest = build(Path(sys.argv[1]))
    OUT.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(manifest["counts"]), "findings:", manifest["findings"], "->", OUT)

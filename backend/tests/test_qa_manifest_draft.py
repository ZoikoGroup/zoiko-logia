"""The DRAFT 72-case QA manifest (prerequisite P5 for WF-01 A3): read from the
question bank, planned at P0 x5 and others x3, every observation NOT_RUN, and
never presented as release evidence or as the supplied baseline."""
import json
from collections import Counter
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "evals" / "qa_pack_72_manifest.DRAFT.json"


def _manifest():
    return json.loads(MANIFEST.read_text())


def test_it_is_a_draft_and_not_release_evidence():
    manifest = _manifest()
    assert manifest["status"] == "DRAFT_UNRATIFIED" and manifest["release_evidence"] is False
    assert manifest["source"]["file"].startswith("external:") and len(manifest["source"]["sha256"]) == 64


def test_counts_match_the_documents():   # RG-006 plan: 38 P0 x5 + 34 others x3 = 292
    manifest = _manifest()
    assert manifest["counts"] == {"cases": 72, "p0": 38, "planned_observations": 292,
                                  "by_priority": {"P0": 38, "P1": 33, "P2": 1}}
    assert manifest["findings"] == []
    assert Counter(c["suite"] for c in manifest["cases"]) == {s: 6 for s in "ABCDEFGHIJKL"}


def test_case_ids_are_unique_and_every_case_has_its_text():
    cases = _manifest()["cases"]
    assert len({c["case_id"] for c in cases}) == 72
    assert all(c["text"].startswith("ASK ") and len(c["text_sha256"]) == 64 for c in cases)


def test_every_planned_observation_is_not_run_and_distinct():
    manifest = _manifest()
    planned = manifest["planned_observations"]
    assert {o["status"] for o in planned} == {"NOT_RUN"}
    assert len({(o["case_id"], o["repetition"]) for o in planned}) == 292
    repeats = {c["case_id"]: c["planned_repetitions"] for c in manifest["cases"]}
    assert all(repeats[c["case_id"]] == (5 if c["priority"] == "P0" else 3) for c in manifest["cases"])

"""WF-01 workcard A1, step 1: the authority register and its duplicate-ID check
(registry/authority_register.json, scripts/check_authority_ids.py).

Covers RG-001 (a duplicate identifier across two documents is not published
as resolved) and RG-002 (ZL-T0-05/06 are recorded as evidence unavailable, not
as non-existent or approved), plus: no silent or self-ratified resolution, no
pass states, and the register matches the controlled documents in docs/."""
import copy
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from check_authority_ids import REGISTER, check, check_docs  # noqa: E402


@pytest.fixture
def register():
    return json.loads(REGISTER.read_text())


def test_the_register_passes_its_own_check(register):
    assert check(register) == []


def test_the_register_matches_the_controlled_documents(register):
    assert check_docs(register) == []


def test_zl_eng_06_stays_unresolved_with_two_referents(register):
    [eng06] = [c for c in register["collisions"] if c["legacy_id"] == "ZL-ENG-06"]
    assert eng06["state"] == "COLLISION_UNRESOLVED" and eng06["resolution"] is None
    assert {c["described_as"] for c in eng06["candidates"]} == {"information-quality standard", "model-tiering standard"}
    assert all(c["canonical_id"] is None for c in eng06["candidates"])
    assert eng06["evidence"], "the collision must cite the documents that evidence it"


@pytest.mark.parametrize("identifier", ["ZL-T0-05", "ZL-T0-06"])
def test_tier0_05_06_are_unavailable_not_absent(register, identifier):
    [entry] = [u for u in register["unavailable_references"] if u["id"] == identifier]
    assert entry["state"] == "EVIDENCE_UNAVAILABLE_IN_REPO" and entry["flagged_unrecovered_by_gap_analysis"]
    assert entry["cited_by"]


def test_no_canonical_id_is_invented(register):
    for doc in register["documents"]:
        declared = [item["id"] for item in doc["declared_ids"]]
        if doc["canonical_id"] is not None:
            assert declared == [doc["canonical_id"]], doc["path"]


def test_a_document_with_two_declared_ids_is_left_unresolved(register):
    [prd] = [d for d in register["documents"]
             if d["path"].endswith("ZoikoLogia_Product_Requirements_Document_Wireframe_Specification.docx")]
    assert prd["state"] == "MULTIPLE_DECLARED_IDS" and prd["canonical_id"] is None


def test_an_unrecorded_duplicate_fails(register):  # RG-001
    broken = copy.deepcopy(register)
    first, second = [d for d in broken["documents"] if d["state"] == "DECLARED"][:2]
    second["declared_ids"] = copy.deepcopy(first["declared_ids"])
    second["canonical_id"] = first["canonical_id"]
    problems = check(broken)
    assert any("duplicate canonical_id" in p for p in problems)
    assert any("not recorded as an unresolved collision" in p for p in problems)


def test_a_silent_resolution_fails(register):
    broken = copy.deepcopy(register)
    eng06 = next(c for c in broken["collisions"] if c["legacy_id"] == "ZL-ENG-06")
    eng06["candidates"][0]["canonical_id"] = "ZL-ENG-06A"
    assert any("without an independent ratification" in p for p in check(broken))


def test_a_self_ratified_resolution_fails(register):
    broken = copy.deepcopy(register)
    eng06 = next(c for c in broken["collisions"] if c["legacy_id"] == "ZL-ENG-06")
    eng06.update(state="RESOLVED", resolution={"map": "proposed"})
    broken["ratifications"] = [{"legacy_id": "ZL-ENG-06", "proposer": "doc-control", "ratifier": "doc-control"}]
    assert any("without an independent ratification" in p for p in check(broken))


def test_removing_tier0_05_fails(register):  # RG-002
    broken = copy.deepcopy(register)
    broken["unavailable_references"] = [u for u in broken["unavailable_references"] if u["id"] != "ZL-T0-05"]
    assert any("ZL-T0-05" in p for p in check(broken))


def test_a_pass_state_or_release_claim_fails(register):
    broken = copy.deepcopy(register)
    broken["documents"][0]["state"] = "APPROVED"
    assert any("pass-like states" in p for p in check(broken))
    broken = copy.deepcopy(register)
    broken["release_evidence"] = True
    assert any("release_evidence" in p for p in check(broken))


def test_a_changed_document_is_detected(register):
    broken = copy.deepcopy(register)
    broken["documents"][0]["sha256"] = "0" * 64
    assert any("changed since the register was built" in p for p in check_docs(broken))

"""CI check for the authority register (WF-01 workcard A1, step 1).

    python3 scripts/check_authority_ids.py            # the register itself
    python3 scripts/check_authority_ids.py --docs     # and that docs/*.docx still match it

Exit 1, with every reason printed, when:
  * a canonical identifier is used twice;
  * a document's state and canonical_id disagree (canonical_id is set only for
    a single, unshared declared identifier);
  * two documents declare the same identifier and it is not recorded as an
    unresolved collision;
  * a collision is marked resolved, given a resolution or canonical ids, without
    a ratification by someone other than its proposer (none exists in step 1,
    so every collision must stay COLLISION_UNRESOLVED);
  * ZL-T0-05 / ZL-T0-06 are not recorded as unavailable evidence;
  * an unavailable reference is also given as a canonical identifier;
  * the register claims to be release evidence or holds a pass state;
  * (--docs) a controlled document was added, removed or changed since the
    register was built, or declares different identifiers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTER = HERE.parent / "registry" / "authority_register.json"
_PASS_WORDS = {"PASS", "PASSED", "QUALIFIED", "RELEASED", "VERIFIED", "APPROVED"}


def _values(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _values(value)
    else:
        yield node


def check(register: dict) -> list[str]:
    problems: list[str] = []
    if register.get("release_evidence") is not False:
        problems.append("the register must state release_evidence: false")
    passing = sorted({v for v in _values({k: register[k] for k in ("documents", "collisions", "unavailable_references")
                                          if k in register}) if isinstance(v, str) and v.upper() in _PASS_WORDS})
    if passing:
        problems.append(f"pass-like states are not allowed in the register: {passing}")

    documents = register.get("documents", [])
    canonical: dict[str, str] = {}
    declared: dict[str, list[str]] = {}
    for doc in documents:
        ids = [item["id"] for item in doc.get("declared_ids", [])]
        for identifier in ids:
            declared.setdefault(identifier, []).append(doc["path"])
        cid, state = doc.get("canonical_id"), doc.get("state")
        if cid:
            if cid in canonical:
                problems.append(f"duplicate canonical_id {cid}: {canonical[cid]} and {doc['path']}")
            canonical[cid] = doc["path"]
        if state == "DECLARED" and (len(ids) != 1 or cid != ids[0]):
            problems.append(f"{doc['path']}: DECLARED needs exactly one declared id equal to canonical_id")
        if state != "DECLARED" and cid is not None:
            problems.append(f"{doc['path']}: state {state} must not carry a canonical_id ({cid})")

    collisions = register.get("collisions", [])
    recorded = {c["legacy_id"] for c in collisions if c.get("state") == "COLLISION_UNRESOLVED"}
    for identifier, paths in sorted(declared.items()):
        if len(paths) > 1 and identifier not in recorded:
            problems.append(f"{identifier} is declared by {len(paths)} documents and not recorded as an unresolved collision")
    ratified = {(r.get("legacy_id"), r.get("proposer")) for r in register.get("ratifications", [])
                if r.get("proposer") and r.get("ratifier") and r.get("proposer") != r.get("ratifier")}
    for collision in collisions:
        legacy = collision.get("legacy_id")
        resolved = (collision.get("state") != "COLLISION_UNRESOLVED" or collision.get("resolution") is not None
                    or any(c.get("canonical_id") for c in collision.get("candidates", [])))
        if resolved and not any(lid == legacy for lid, _ in ratified):
            problems.append(f"{legacy} is marked resolved without an independent ratification")
        if legacy in canonical:
            problems.append(f"{legacy} is an unresolved collision but is used as a canonical_id")
    if "ZL-ENG-06" not in recorded:
        problems.append("ZL-ENG-06 must be recorded as COLLISION_UNRESOLVED")

    unavailable = {u["id"]: u for u in register.get("unavailable_references", [])}
    for identifier in ("ZL-T0-05", "ZL-T0-06"):
        entry = unavailable.get(identifier)
        if not entry or entry.get("state") != "EVIDENCE_UNAVAILABLE_IN_REPO" or not entry.get("flagged_unrecovered_by_gap_analysis"):
            problems.append(f"{identifier} must be recorded as EVIDENCE_UNAVAILABLE_IN_REPO and flagged unrecovered")
    for identifier in unavailable:
        if identifier in canonical:
            problems.append(f"{identifier} is recorded as unavailable but used as a canonical_id")
    return problems


def check_docs(register: dict) -> list[str]:
    sys.path.insert(0, str(HERE))
    from build_authority_register import scan
    problems = []
    current = {doc["path"]: doc for doc in scan()}
    listed = {doc["path"]: doc for doc in register.get("documents", [])}
    for path in sorted(set(current) - set(listed)):
        problems.append(f"{path} is not in the register")
    for path in sorted(set(listed) - set(current)):
        problems.append(f"{path} is in the register but no longer in docs/")
    for path in sorted(set(current) & set(listed)):
        if current[path]["sha256"] != listed[path]["sha256"]:
            problems.append(f"{path} changed since the register was built")
        if [i["id"] for i in current[path]["declared_ids"]] != [i["id"] for i in listed[path]["declared_ids"]]:
            problems.append(f"{path} declares different identifiers from the register")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", action="store_true", help="also check docs/*.docx against the register")
    parser.add_argument("--register", type=Path, default=REGISTER)
    args = parser.parse_args()
    register = json.loads(args.register.read_text())
    problems = check(register) + (check_docs(register) if args.docs else [])
    for problem in problems:
        print(f"AUTHORITY: {problem}")
    print(f"authority register: {len(register.get('documents', []))} documents, "
          f"{sum(c.get('state') == 'COLLISION_UNRESOLVED' for c in register.get('collisions', []))} unresolved collisions, "
          f"{len(register.get('unavailable_references', []))} unavailable references, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

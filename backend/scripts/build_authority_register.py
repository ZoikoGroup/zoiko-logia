"""Builds backend/registry/authority_register.json from the controlled documents
in docs/*.docx (WF-01 workcard A1, step 1; 3 Nov 2026).

What it records, and only that:
  * each document: repo path, SHA-256 of the file, title, the identifiers the
    document declares for itself (with the exact text that declares them), and
    the identifiers it cites;
  * a canonical_id ONLY where exactly one document declares exactly one
    identifier that no other document declares; otherwise canonical_id is null
    and the state says why;
  * cited identifiers that no document in the repository declares, as
    EVIDENCE_UNAVAILABLE_IN_REPO (ZL-T0-05/06 are additionally flagged by the
    gap analysis as unrecovered);
  * identifier collisions: those found here between documents, and ZL-ENG-06,
    whose two referents are described in documents outside the repository
    (hashed, not copied). Every collision is COLLISION_UNRESOLVED with no
    resolution: resolving one needs a Document Control proposal ratified by a
    different person (Chief Architect), which does not exist yet.

The register is not release evidence and holds no PASS states.

    python3 scripts/build_authority_register.py [--external FILE ...]
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
OUT = Path(__file__).resolve().parents[1] / "registry" / "authority_register.json"

# Identifiers of the controlled-document families in use (ZL-T0-04, ZL-T0-04-WF-01,
# ZL-T2-01D, ZL-ENG-06, ZL-RPT-007, ZL-OV-01C, ZL-WF-GAP-01).
ID = r"ZL-(?:T[0-9]|ENG|RPT|OV|WF|GAP|BE|DM)(?:-[A-Z0-9]{1,6}){1,4}"
_ID = re.compile(rf"\b{ID}\b")
# A document declares its own identifier in its control block.
_DECLARED = re.compile(rf"(?:Document\s+(?:ID|Number|No\.?|Code|Reference)|Doc(?:ument)?\s+ID|Document\s+control)\s*[:|•]?\s*({ID})", re.I)


def _text(path: Path) -> str:
    """The document's text: runs joined as written (Word splits one word over
    several runs), paragraphs and table cells ended, tabs and breaks spaced."""
    raw = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "ignore")
    raw = re.sub(r"</w:p>", "\n", raw)
    raw = re.sub(r"</w:tc>", " | ", raw)
    raw = re.sub(r"<w:(?:tab|br|cr)\b[^>]*/>", " ", raw)
    return html.unescape(re.sub(r"<[^>]+>", "", raw))


def _title(path: Path, text: str) -> str:
    try:
        core = zipfile.ZipFile(path).read("docProps/core.xml").decode("utf-8", "ignore")
        found = re.search(r"<dc:title>([^<]+)</dc:title>", core)
        if found and found.group(1).strip():
            return html.unescape(found.group(1).strip())
    except KeyError:
        pass
    return next((" ".join(line.split()) for line in text.splitlines() if line.strip()), path.stem)[:200]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan(docs: Path = DOCS) -> list[dict]:
    out = []
    for path in sorted(docs.glob("*.docx")):
        text = _text(path)
        flat = " ".join(text.split())
        declared = {}
        for match in _DECLARED.finditer(flat):
            declared.setdefault(match.group(1), flat[max(0, match.start() - 40):match.end() + 40])
        cited = sorted(set(_ID.findall(flat)) - set(declared))
        out.append({"path": str(path.relative_to(REPO)), "sha256": _sha(path), "title": _title(path, text),
                    "declared_ids": [{"id": k, "evidence": v} for k, v in sorted(declared.items())], "cited_ids": cited})
    return out


def _base(identifier: str) -> str:
    """The standard a wireframe belongs to: ZL-T0-04-WF-01 -> ZL-T0-04."""
    return re.sub(r"-(?:WF|BE|DM|LLM|MRP)(?:-[A-Z0-9]+)*$", "", identifier)


ZL_ENG_06 = {
    "legacy_id": "ZL-ENG-06",
    "state": "COLLISION_UNRESOLVED",
    "candidates": [
        {"described_as": "information-quality standard", "canonical_id": None},
        {"described_as": "model-tiering standard", "canonical_id": None},
    ],
    "text_available_in_repo": False,
    "resolution": None,
    "note": "Neither standard's text is in the repository. Canonical identifiers are assigned by Document Control "
            "and ratified by the Chief Architect (WF-01 screen 02); none has been assigned.",
}


def build(external: list[Path]) -> dict:
    documents = scan()
    owners: dict[str, list[str]] = {}
    for doc in documents:
        for item in doc["declared_ids"]:
            owners.setdefault(item["id"], []).append(doc["path"])
    collisions = [{"legacy_id": identifier, "state": "COLLISION_UNRESOLVED", "declared_by": paths, "resolution": None}
                  for identifier, paths in sorted(owners.items()) if len(paths) > 1]
    for doc in documents:
        ids = [item["id"] for item in doc["declared_ids"]]
        if not ids:
            doc.update(canonical_id=None, state="ID_NOT_FOUND")
        elif len(ids) > 1:
            doc.update(canonical_id=None, state="MULTIPLE_DECLARED_IDS")
        elif len(owners[ids[0]]) > 1:
            doc.update(canonical_id=None, state="COLLISION_UNRESOLVED")
        else:
            doc.update(canonical_id=ids[0], state="DECLARED")
    declared = set(owners)
    cited: dict[str, set[str]] = {}
    for doc in documents:
        for identifier in doc["cited_ids"]:
            cited.setdefault(identifier, set()).add(doc["path"])
    unavailable = []
    for identifier in sorted(cited):
        if identifier in declared or identifier == "ZL-ENG-06":
            continue
        unavailable.append({"id": identifier, "state": "EVIDENCE_UNAVAILABLE_IN_REPO",
                            "flagged_unrecovered_by_gap_analysis": identifier in ("ZL-T0-05", "ZL-T0-06"),
                            "wireframes_in_repo": sorted({d["canonical_id"] for d in documents
                                                         if d["canonical_id"] and _base(d["canonical_id"]) == identifier}),
                            "cited_by": sorted(cited[identifier])})
    eng06 = dict(ZL_ENG_06, cited_by=sorted(cited.get("ZL-ENG-06", set())),
                 evidence=[{"file": f"external:{path.name}", "sha256": _sha(path), "quote": quote}
                           for path in external for quote in _eng06_quotes(path)])
    return {
        "version": "authority-register-0.1",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workcard": "WF-01 A1 step 1",
        "release_evidence": False,
        "note": "Records what the controlled documents state. Not release evidence; no gate status. canonical_id is set "
                "only where one document unambiguously declares one identifier; every other case stays unresolved.",
        "documents": documents,
        "collisions": collisions + [eng06],
        "unavailable_references": unavailable,
        "ratifications": [],
    }


def _eng06_quotes(path: Path) -> list[str]:
    flat = " ".join(_text(path).split())
    return [flat[max(0, m.start() - 120):m.end() + 120] for m in re.finditer(r"ZL-ENG-06", flat)
            if re.search(r"two different standards|both carry ZL-ENG-06|used by two", flat[max(0, m.start() - 160):m.end() + 160], re.I)][:2]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--external", nargs="*", default=[], type=Path,
                        help="documents outside the repository that evidence the ZL-ENG-06 collision (hashed, not copied)")
    register = build(parser.parse_args().external)
    OUT.write_text(json.dumps(register, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(register['documents'])} documents, {len(register['collisions'])} collisions, "
          f"{len(register['unavailable_references'])} unavailable references -> {OUT}")

"""Offline plan only. Reads an exported JSON inventory, never connects to a database.

No apply mode exists. Status transitions require separate explicit authorization.
Input: [{version_id, source_id, title, status, submitted_by, approved_by, usage_count}].
"""
import argparse
import hashlib
import json
from pathlib import Path


def plan(rows):
    candidates = [row for row in rows if row.get("approved_by") and
                  row.get("approved_by") == row.get("submitted_by") and
                  row.get("status") in {"APPROVED", "ACTIVE"}]
    candidates.sort(key=lambda r: (-int(r.get("usage_count", 0)), r["version_id"]))
    return {"mode": "DRY_RUN_ONLY", "executed": False, "expected_count": 22,
            "actual_count": len(candidates), "count_matches": len(candidates) == 22,
            "review_window_ready": False, "independent_reviewer": None,
            "review_schedule": None, "production": "NO-GO",
            "first_six": [r["version_id"] for r in candidates[:6]],
            "ranking_verified": all("usage_count" in r for r in candidates),
            "proposed_transitions": [{"version_id": r["version_id"], "source_id": r["source_id"],
                "from_status": r["status"], "proposed_status": "UNDER_REVIEW",
                "reason": "INDEPENDENT_REVIEW_REQUIRED", "executed": False} for r in candidates],
            "preserve": ["all audit events", "original content and hashes", "existing approval attribution"],
            "required_before_transition": ["explicit transition authorization", "named independent reviewer",
                "review schedule prioritizing six highest-use documents", "verified usage inventory",
                "tested snapshot and restore", "confirmed review window"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory",type=Path,required=True)
    args=parser.parse_args()
    raw=args.inventory.read_bytes()
    result=plan(json.loads(raw))
    result["inventory_sha256"]=hashlib.sha256(raw).hexdigest()
    print(json.dumps(result,indent=2))
    return 0 if result["count_matches"] and result["ranking_verified"] else 1

if __name__ == "__main__":
    raise SystemExit(main())

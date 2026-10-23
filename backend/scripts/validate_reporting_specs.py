"""Validate reporting assets or compile a scoped local JSON draft.

Run from backend: .venv/bin/python scripts/validate_reporting_specs.py
This local operator command is not an HTTP endpoint or approval workflow.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domains.reporting.request_service import build_requested_draft
from app.domains.reporting.specification import (SCHEMAS, TABLES, catalog_support, load_table,
    schema_validator, specification_hashes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--account-map", type=Path)
    parser.add_argument("--authorised-entity", action="append", default=[])
    args = parser.parse_args()
    if any((args.request, args.ledger, args.account_map)) and not all((args.request, args.ledger, args.account_map)):
        parser.error("--request, --ledger and --account-map must be supplied together")
    for name in SCHEMAS:
        schema_validator(name)
    result = {"tables": {name: len(load_table(name)) for name in TABLES},
              "sha256": specification_hashes(), "catalogue": catalog_support()}
    if args.request:
        report = build_requested_draft(json.loads(args.request.read_text()), json.loads(args.ledger.read_text()),
            json.loads(args.account_map.read_text()), authorised_entity_ids=frozenset(args.authorised_entity))
        result["draft"] = {"state": report.draft.state.value, "error_code": report.draft.error_code,
            "error_detail": report.draft.error_detail, "snapshot_hash": report.draft.snapshot_hash,
            "facts": report.facts,
            "reconciliation": [{"rule_id": o.rule_id, "passed": o.passed, "delta": str(o.delta),
                                "severity": o.severity, "source": o.specification_source}
                               for o in report.draft.outcomes]}
    print(json.dumps(result, indent=2))
    return 0 if "draft" not in result or result["draft"]["state"] == "DRAFT_RECONCILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

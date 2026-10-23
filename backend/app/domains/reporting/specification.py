"""Load controlled specifications; a catalogue entry is not implementation support."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry

SPEC = Path(__file__).with_name("spec")
TABLES = {
    "report_catalog": ("report_id", "report_name", "family", "report_class", "phase", "minimum_evidence", "certification_required"),
    "reconciliation_rules": ("rule_id", "area", "invariant", "default_severity"),
    "acceptance_test_cases": ("test_id", "suite", "test_case", "input_mutation", "expected_behavior", "severity"),
}
STATEMENT_TEMPLATES = {"RPT-001": "balance_sheet", "RPT-002": "profit_or_loss",
                       "RPT-004": "cash_flow", "RPT-006": "changes_in_equity"}
SCHEMAS = {"report_request", "financial_fact", "report_manifest"}


class SpecificationError(ValueError):
    pass


def load_table(name: str, root: Path = SPEC) -> list[dict[str, str]]:
    if name not in TABLES:
        raise SpecificationError("Unknown specification table")
    with (root / (name + ".csv")).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != TABLES[name]:
            raise SpecificationError(f"{name}: unexpected columns")
        rows = list(reader)
    key = TABLES[name][0]
    seen = set()
    for row in rows:
        if None in row or any(not isinstance(v, str) or not v.strip() for v in row.values()):
            raise SpecificationError(f"{name}: malformed or empty field")
        if row[key] in seen:
            raise SpecificationError(f"{name}: duplicate {row[key]}")
        seen.add(row[key])
    if not rows:
        raise SpecificationError(f"{name}: empty specification")
    return rows


def schema_validator(name: str) -> Draft202012Validator:
    if name not in SCHEMAS:
        raise SpecificationError("Unknown schema")
    schema = json.loads((SPEC / "schemas" / (name + ".schema.json")).read_text())
    # Controlled compatibility correction: the supplied JSON double-escapes
    # the decimal point. Preserve the source and change only this known pattern.
    if name == "financial_fact":
        supplied = schema["properties"]["value"]["pattern"]
        if supplied == r"^-?[0-9]+(\\.[0-9]+)?$":
            schema["properties"]["value"]["pattern"] = r"^-?[0-9]+(\.[0-9]+)?$"
    Draft202012Validator.check_schema(schema)
    # Never retrieve a remote reference while validating a local contract.
    return Draft202012Validator(schema, format_checker=FormatChecker(), registry=Registry())


def validate_contract(name: str, payload: dict) -> None:
    errors = list(schema_validator(name).iter_errors(payload))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise SpecificationError(f"{name}.{path}: {error.message}")
    period = payload.get("period", {})
    if "start" in period and "end" in period and period["start"] > period["end"]:
        raise SpecificationError(f"{name}.period: start must not follow end")
    if name == "financial_fact":
        from decimal import Decimal
        value, status = payload["value"], payload["value_status"]
        if status in {"PRESENT", "ZERO"}:
            if value is None or (Decimal(value) == 0) != (status == "ZERO"):
                raise SpecificationError("financial_fact: value and value_status disagree")
        elif value is not None:
            raise SpecificationError("financial_fact: unavailable values must be null")


def catalog_support() -> list[dict]:
    return [dict(row, draft_compiler_supported=row["report_id"] in STATEMENT_TEMPLATES,
                 certified=False) for row in load_table("report_catalog")]


def specification_hashes() -> dict[str, str]:
    paths = [SPEC / (name + ".csv") for name in TABLES]
    paths += [SPEC / "schemas" / (name + ".schema.json") for name in sorted(SCHEMAS)]
    return {p.relative_to(SPEC).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

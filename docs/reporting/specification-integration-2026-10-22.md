# Reporting specification integration — 22 October 2026

The six founder-supplied CSV/JSON files are connected to the existing reporting library. The original files remain byte-identical to their Downloads copies. Excel schedules and attendance files are not reporting inputs and were not imported.

## Implemented

- `specification.py` reads the 90-template catalogue, 10 reconciliation definitions and 58 acceptance definitions. It rejects malformed CSV headers, empty fields and duplicate identifiers. It provides per-file SHA-256 fingerprints and a catalogue support matrix that distinguishes implemented draft compilers from catalogue entries. No template is marked certified.
- Draft 2020-12 JSON Schema validation uses `jsonschema`, with date-format checking and no remote-reference retrieval. Contract names are allowlisted. Request and fact date ranges must be ordered. Fact values retain decimal strings: missing, zero and present are distinct; unavailable values must be null.
- `request_service.build_requested_draft` validates requests, checks catalogue membership and class, requires server-resolved entity authorisation, matches entity/currency/period to the ledger, and calls the existing ledger compiler and reconcilers. Successful output facts are validated against the financial-fact contract.
- Supported draft templates: RPT-001 balance sheet, RPT-002 profit or loss, RPT-004 cash flow, RPT-006 changes in equity. Current scope remains **one synthetic entity, one period, one currency, scale 1, JSON facts, MANAGEMENT_BASIS without comparatives**. These are not framework-certified statutory reports. Unsupported templates, actual-data requests, framework claims, scaling and export requests return an explicit unavailable result.
- Existing reconciliation checks now require their supplied CSV definitions and include their configured severity. Missing required rules prevent a reconciled result. No CSV expression is evaluated as executable code. Arithmetic remains in the established reconcilers.
- `validate_contract("report_manifest", payload)` validates manifest structure. This does not create an audit commitment, approve a report or authorise issue. Manifest persistence, authenticated HTTP reporting routes, UI/chat dispatch, renderers and approval workflows remain unimplemented.

## Controlled specification differences

1. The supplied fact schema's decimal regex is double-escaped: it rejects ordinary decimal strings such as `12.50`. The loader applies a narrowly matched compatibility correction to that exact in-memory pattern. The source JSON is unchanged. A corrected owner-issued schema should replace this compatibility correction in a future version.
2. The existing compiler includes PL-001, but the supplied rules CSV does not. PL-001 remains an explicitly internal CRITICAL check; it is not silently dropped or attributed to the founder CSV.
3. FRQA-0004 says duplicate posting must BLOCK. Existing import idempotency safely ignores an identical same-version retry and records it; this blocks double-counting but does not reject a safe retry. Conflicting content is still rejected. Owner clarification is needed before changing this established behavior; neither the acceptance CSV nor the existing golden test was altered.

## Local commands

From `backend/`, validate the assets and inspect the catalogue support matrix:

```sh
.venv/bin/python scripts/validate_reporting_specs.py
```

Compile a supported local draft from explicit JSON inputs:

```sh
.venv/bin/python scripts/validate_reporting_specs.py \
  --request /path/to/request.json \
  --ledger /path/to/ledger.json \
  --account-map /path/to/account-map.json \
  --authorised-entity 'Exact entity identifier'
```

The command writes JSON to stdout and uses a nonzero exit status for unavailable/incomplete drafts. The authorisation argument is for a local operator; an eventual HTTP endpoint must resolve authorisation from the authenticated server context, never from the body. A request's `entity_ids` must exactly match the current ledger's `entity` identifier. No database or external model is contacted.

## Acceptance coverage

All 58 original CSV rows are collected as individually named pytest cases. Nine have executable coverage in `test_reporting_specifications.py`: balanced control, unmatched debit, unsupported scale, duplicate double-count prevention (with the interpretation noted above), missing-as-zero, cash bridge, mixed instant/duration structure, rejection of binary numeric fact values, and provider-independent numerical compilation.

The remaining **49 cases are explicitly skipped as unimplemented**, not counted as successful acceptance. They include consolidation, FX translation, effective-date rule packs, rights/revocation, source/citation semantics, actual file export parity, issue/audit persistence and cancellation. The numeric boundary tests do not substitute for full renderer/export or production security acceptance. The supplied cases are descriptions rather than complete executable fixtures; these nine use the existing synthetic golden ledger and focused contract mutations.

No live Groq/provider calls, production deployment, shared database changes, or approval/issue claims are part of this integration. The active server must load the changed code before it can use the library; existing chat behavior is not routed through this internal reporting boundary.

## Observed verification

- Targeted reporting suites, including the real local CLI smoke test: **63 passed, 49 skipped**.
- Full offline backend suite: **3,478 passed, 75 skipped, 2 expected failures**. The CLI smoke test was added afterwards and passed in the targeted rerun; it does not change application code.
- All six controlled assets match their original Downloads bytes; the README provenance table is updated separately.
- Validator dependency installed in the project virtual environment and declared in `backend/requirements.txt`.
- No frontend changes; frontend tests were not rerun for this backend-only integration.

Logs, asset fingerprints and per-case coverage are saved in `specification-integration-evidence-2026-10-22/` beside this document.

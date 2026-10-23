# Controlled reporting specification inputs

Files here come from the ZL-RPT-001…006 specification set. Copy them in exactly
as received — a change needs a new version from the document owner, not an edit
in place.

| File | Goes in | Used for |
|---|---|---|
| `report_catalog.csv` (90 rows) | this folder | template registry / certified-support matrix |
| `reconciliation_rules.csv` | this folder | rule IDs and severities checked by `reconcile.py` |
| `acceptance_test_cases.csv` (58 cases) | this folder | test backlog |
| `*.schema.json` (request, fact, manifest) | `schemas/` | API and contract validation |

When adding a file, record it below.

| File | Source document / version | Received | Approval status |
|---|---|---|---|
| `report_catalog.csv` | Founder-supplied; version not declared | Copied 2026-10-22 | Received; certification not established |
| `reconciliation_rules.csv` | Founder-supplied; version not declared | Copied 2026-10-22 | Received; PL-001 omission documented |
| `acceptance_test_cases.csv` | Founder-supplied; version not declared | Copied 2026-10-22 | Received; 9 covered, 49 pending |
| `schemas/report_request.schema.json` | Proposed ReportRequest v1 | Copied 2026-10-22 | Received; not an approval |
| `schemas/financial_fact.schema.json` | Proposed FinancialFact v1 | Copied 2026-10-22 | Received; decimal compatibility correction documented |
| `schemas/report_manifest.schema.json` | Proposed ReportManifest v1 | Copied 2026-10-22 | Received; issue workflow not implemented |

Integration scope and controlled-file differences: see `docs/reporting/specification-integration-2026-10-22.md` at the repository root.

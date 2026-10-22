# ADR-RPT-001 — Reporting gates G1 + G2: golden route 001

| | |
|---|---|
| Status | Proposed — awaiting Chief Architect and Head of Accounting Domain review |
| Date | 2026-10-21 |
| Interprets | ZL-RPT-007 Master Engineering Implementation Playbook v1.0 (itself PROPOSED) |
| Code | `backend/app/domains/reporting/` · tests `backend/tests/test_reporting_golden_route.py` |

Planning review, 21 October 2026: see the [verified implementation plan](implementation-plan-2026-10-21.md). This ADR remains proposed. The code's G1/G2 labels refer to ZL-RPT-007, not the differently numbered gates in ZL-RPT-005. Existing arithmetic tests do not certify framework completeness, persistence, issue controls or all 58 acceptance cases.

## Scope built

ZL-RPT-007 §18.1 "first golden route": one synthetic entity, one period (calendar 2026), one currency (USD), a controlled synthetic ledger, producing a balance sheet, profit or loss, cash-flow statement and statement of changes in equity as **reconciled draft outputs only**. No accounting framework is selected; G3 rule packs and disclosures are out of scope, so this output is not a complete IFRS / US GAAP / FRS 102 financial statement.

| Playbook | Module |
|---|---|
| §4 report states | `states.py` — pipeline reaches at most `DRAFT_RECONCILED` |
| §6.1 import, dedupe, cutoff, seal | `ledger.py`, `snapshot.py` |
| §6.2 account map | `mapping.py` — unmapped account = exception, never "Other" |
| §7 facts and compiler | `compiler.py` — Decimal only, fact_id + lineage + source journals per line |
| §7 / §15.2 invariants | `reconcile.py` — TB-001, BS-001, PL-001, CF-001, EQ-001, each recomputed independently |
| §18.1 golden route | `fixtures/golden_route_001.json` |

## Decisions

1. **Separate domain, not an extension of existing calculators.** `app/domains/calculations/` and `app/orchestration/calculations/` serve Ask Kriton chat arithmetic. The financial compiler has stricter invariants (Decimal-only, sealed inputs, no rounding), so it lives in `app/domains/reporting/` and imports neither.
2. **Decimal only.** A test parses every reporting module and fails on any `float` name or float literal. Ledger amounts must be decimal strings; JSON numbers, blanks and missing amounts are rejected (never coerced to zero).
3. **Report states are separate from workpaper states.** Workpapers keep `draft` / `in_review` / `signed_off`; reports use the seven §4 states.
4. **Cash-flow classification** comes from each cash journal's non-cash counterpart accounts. A journal whose counterparts span more than one class is an exception, not an allocation guess (§6.2 forbids unspecified proportions).
5. **Single currency only.** A multi-currency ledger returns `UNAVAILABLE / fx_missing_or_inapplicable`; translation is a later engine (§8).
6. **No persistence, API or audit events yet.** G1/G2 are a pure library so the arithmetic can be certified first.

## Open points (need an owner before G3+)

| Point | Proposal | Needs |
|---|---|---|
| API path | `/api/v1/reports/...` to match existing routes (playbook says `/v1/reports`) | Chief Architect |
| Audit event names | `reporting.snapshot_sealed`, `reporting.report_reconciled`, … in existing `domain.event` style | ZL-T0-13 confirmation |
| Controlled spec inputs | Seven CSV/JSON assets and ZL-RPT-002…007 are available in Downloads; register versions/checksums before future incorporation into `spec/` and `spec/schemas/`. ZL-RPT-001 remains outstanding. | Document owner approval / missing architecture document |
| Rule IDs | Received CSV has ten rules; local PL-001 is not in it, nor is proposed CF-002. Preserve CSV IDs and resolve extensions explicitly. | Reporting Engineering + Accounting Domain |
| Golden expected values | Hand-derived in the test docstring | Independent accountant sign-off (§15 L5) |
| Statement line order and labels | Currently sorted by line ID | Head of Design / renderer (G5) |
| Duplicate posting | Current identical source/version retries count once; FRQA-0004 says BLOCK, while playbook §15.2 allows either. Distinguish duplicate ledger rows from request replay before choosing behaviour. | Accounting Domain + Architect |
| Fact and completeness contracts | Existing facts need entity/basis/status/period wire-contract alignment. The second display fixture must remain incomplete without required notes even when numeric invariants pass. | Reporting + Accounting Domain |
| Persistence transaction | Existing audit/idempotency helpers commit internally. Atomic state-plus-audit writes and safe retries need an explicit reporting-owned transaction design and failure tests. | Platform + Security |

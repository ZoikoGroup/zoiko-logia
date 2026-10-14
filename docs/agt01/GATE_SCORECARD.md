# ZL-ENG-AGT-01 — Gate scorecard (§15)

As of 11 October 2026. "Automated tests pass" is not "PASSED": every gate also
needs its named owner's sign-off. G5, G7 and G8 need human or domain sign-off and
are never marked PASSED here.

| Gate | Owner | Status | Evidence | Still missing |
|---|---|---|---|---|
| G0 Design alignment | Chief Architect | PENDING | `CHANGE_REQUESTS.md` CR-02, CR-03, CR-04, CR-05, CR-06 | Reconcile proposed state names and new audit events with ZL-T0-13 and ZL-T0-06 |
| G1 Security / rights | Security + QA | AUTOMATED TESTS PASS | `tests/test_tool_policy.py`, `tests/agt01/test_qa05_cross_tenant.py`, `test_qa06_unauthorised_write.py`, `test_extra_controls.py` (unknown rights), `test_model_gateway_single_path.py` | Penetration test; Postgres RLS integration run (`RUN_DB_INTEGRATION_TESTS=1`) |
| G2 Safe decisions | AI Risk + QA | AUTOMATED TESTS PASS | `test_qa04`, `test_qa09`, `test_extra_controls.py` (uncertain ≠ LOW), `test_review_loop.py` | AI Risk review of refusal and review routes |
| G3 Evidence quality | Massarius + Domain | PENDING | `test_governed_kb_retrieval.py`, `test_learned_answers.py` | Demo B recorded with real historical sources |
| G4 Numeric correctness | Backend + QA | AUTOMATED TESTS PASS | `test_qa03`, `test_figure_reconciliation.py`, `test_extra_controls.py` | Domain sign-off of the 0.2% tolerance; sampling of live answers for false withholds |
| G5 Professional correctness | Domain Assurance | PENDING HUMAN SIGN-OFF | | Expert-scored benchmark (≥300 cases, §C) |
| G6 Failure resilience | Security + SRE + QA | AUTOMATED TESTS PASS | `test_qa10_failures.py`, `test_workflow_state.py`, `test_qa07` | Incident and rollback drill |
| G7 Multilingual scope | Localization + Domain | PENDING HUMAN SIGN-OFF | `test_qa09_non_english.py` (scope limit) | Nothing launched beyond English |
| G8 Operational readiness | CTO + Product + SRE | PENDING HUMAN SIGN-OFF | | Load, cost, monitoring and support sign-off |

Run: `make agt01-test`, `make agt01-demo`.

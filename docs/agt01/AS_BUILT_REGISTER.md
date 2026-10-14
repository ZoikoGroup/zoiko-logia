# ZL-ENG-AGT-01 v3.0 — As-built register

Status as of 11 October 2026. Statuses use the directive's scale (NOT STARTED /
PARTIAL / CODE COMPLETE / QA VERIFIED / APPROVED). Nothing here is QA VERIFIED or
APPROVED: automated tests pass, but no QA sign-off or recorded demonstration with
real sources has happened. Paths are relative to `backend/` unless stated.
See also [GATE_SCORECARD.md](GATE_SCORECARD.md) and [CHANGE_REQUESTS.md](CHANGE_REQUESTS.md).

Run the evidence: `make agt01-test` (QA pack) and `make agt01-demo` (Demos A and B).

## 1. Tool inventory

| Tool | Purpose | Function | Version | Data accessed | Roles | Scope | Timeout | Retries | Write | Owner | Tests |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `search_knowledge_base` | Governed source passages | `app/domains/model_gateway/tools/kb_tool.py` | 1.0 | Licence-checked, versioned source passages (tenant-private only for own tenant) | `KRITON_TOOL_ROLES` | tenant | 45 s | 0 | No | Massarius / Data | `test_governed_kb_retrieval.py`, `agt01/test_qa05` |
| `get_exchange_rate` | ECB reference rates | `tools/fx_tool.py` | 1.0 | Frankfurter (public) | `KRITON_TOOL_ROLES` | public | 14 s | 1 | No | Kriton / AI-ML | `test_agent_loop.py` |
| `get_economic_indicator` | World Bank indicators | `tools/economic_tool.py` | 1.0 | World Bank WDI, DBnomics (public) | `KRITON_TOOL_ROLES` | public | 12 s | 1 | No | Kriton / AI-ML | `test_agent_loop.py` |
| `get_market_data` | Prices, fundamentals | `tools/market_tool.py` | 1.0 | Twelve Data, SEC EDGAR (public) | `KRITON_TOOL_ROLES` | public | 15 s | 1 | No | Kriton / AI-ML | `test_agent_loop.py` |
| `calculate` | Deterministic arithmetic with a receipt | `tools/calc_tool.py` | 1.1 (formula `expression-evaluator-1.0`) | None | `KRITON_TOOL_ROLES` | none | 2 s | 0 | No | Backend / Calculation | `agt01/test_qa03`, `test_figure_reconciliation.py` |
| `render_chart` | Validated chart from sourced figures | `tools/chart_tool.py` | 1.0 | Figures already in the question or tool results | `KRITON_TOOL_ROLES` | none | 2 s | 0 | No | Frontend / Visualization | `test_agent_loop.py`, `agt01/test_extra_controls.py` |

Owners are team names from directive §16; named individuals are still TBD.

## 2. Agent loop map

| Question | Where |
|---|---|
| Entry point | `app/orchestration/service.py:2231` calls `model_gateway/service.py` `run_agentic_completion` → `agent.py:381` `run_agent` |
| Plan creation | The model proposes tool calls each step (`agent.py:615` loop); there is no separate plan object |
| Tool offering | `agent.py:423` `registry.function_schemas` (only tools the caller may use) |
| Authorisation | `agent.py:515` `authorize(name)` → `service.py:796` `_tool_authorizer` → `tool_registry.decide` (user active, same tenant, role unchanged, tool known, not a write action, role and permission) |
| Execution | `agent.py:510` `execute` → `ToolRegistry.execute` (decision must match the tool, schema validation, timeout, bounded retry) |
| Second call | The model's next turn after tool results are appended (`agent.py:615`) |
| Stop | `final_answer`, `max_steps` (`agent.py:731`), `time_budget` (`:618`, `:715`, `:721`), `token_budget` (`:655`); duplicate calls are not re-run; workflow states in `app/orchestration/workflow_state.py` |
| Verification | Figures `agent.py:682` and `:435`; release check `service.py:2870` |
| Records | `agent_tool_called` (decision ID, idempotency key, calculation ID), `calculation_receipt_recorded`, `agent_completed`, `workflow_completed`, `answer_receipt` (`app/orchestration/router.py`) |

### Agent design changes (12 October)

| Directive | Now |
|---|---|
| Kriton plans first (§02, App. B4) | `app/orchestration/agent_plan.py` plans before anything is fetched: `simple` or `agent` with an ordered tool list; audited as `agent_plan_proposed` with the policy-approved tool list; calls outside the plan are flagged `planned: false` |
| Don't pre-fetch everything (§02) | Agent runs no longer pre-fetch web search or live data; the new `search_web` tool fetches only when needed. The knowledge base is still pre-fetched (CR-10) and not searched twice |
| Simple questions skip the loop (§05.5) | `simple` plans use one grounded composition with no tool loop |
| Budgets, resume, no result (§05.4) | Token and optional USD budget (`AGENT_MAX_COST_USD`, `MODEL_PRICE_PER_MILLION_TOKENS`); `no_result` stop reason; safe resume of successful tool calls on a retry with the same idempotency key (15 min) |
| Real multi-step run (§02, §04) | `scripts/agt01_live_demo.py` against Groq and real tools; trace in `docs/agt01/evidence/live_run_20261012T050224Z.json` |
| Agent on (§05) | `GET /health/agent` and the startup log state ON/OFF and why |

## 3. Kriton → Massarius (retrieval) integration

| Item | Where / behaviour |
|---|---|
| Entry | `app/orchestration/governed_retrieval.py:59` `retrieve_governed_evidence` |
| Tenant boundary | SQL predicate in `retrieve.py` `_candidate_versions` (shared or own-tenant sources only) |
| Engagement boundary | Rights with `terms_reference` `engagement:<id>` usable only in that engagement, in both rights checks (CR-12) |
| Rights | `retrieve.py:286` retrieval right and `:291` model-transmission right, both checked before any passage text is read; `UNKNOWN` rights are denied (`source_library/licensing.py` `RIGHT_UNKNOWN`) |
| Licence gate | `governed_retrieval.py:76` `license_gate.check_eligibility` (second check before text reaches a prompt) |
| Search | Keyword + pgvector over eligible versions only, fused; authority, freshness and date applicability re-ranking |
| Bundle | `governed_retrieval.py:83` persists the manifest and entries before use; each passage carries `content_hash`, `permitted_span` and `rights_decision`; the answer receipt carries `citation_spans` (the exact supporting sentence per citation, `citation_spans.py`) |
| Conflicts | A `conflicts` relationship marks the bundle `conflicting_sources` → human review (`routing_matrix.py`); tested end to end |
| Dates | Approval requires an effective-from date (`source_library/service.py`); all 59 searchable versions have one |
| Corpus | Searchable text: 22 HMRC (UK) sources, 2,214 passages; 1 Indian GST source, 75 passages. US, IFRS and Indian income-tax entries are metadata only, so those questions rely on trusted web search |
| Dates | Effective-from/to and supersession checked per version; historical version chosen for an as-of date |

## 4. Knowledge base vs feedback

| Store | Table | Who can change it |
|---|---|---|
| Authoritative sources | `sources`, `source_versions`, `source_passages`, `source_rights` | Source managers (`source.manage`), maker-checker approval |
| Retrieval index | `source_passages.embedding` | Ingestion jobs only |
| Feedback | `answer_feedback` | Users (their own ratings) |
| Review tickets | `review_cases` (open → triaged → resolved → released) | Reviewers (`review.resolve`); release by a second reviewer |
| Reviewed answers (reused) | `benchmark_cases`, dataset `kriton-reviewed-gold:<tenant>` | Only via release after re-test |
| Pending reviewed answers | dataset `kriton-reviewed-pending:<tenant>` | Never read by Kriton |
| Old auto-learned answers | dataset `kriton-learned:<tenant>` | Never read any more |
| Training data | Export only, needs `--data-use-approval` | Offline, reviewer-approved answers only |

No path lets feedback reach sources, passages, the index or reused answers without a reviewer and a second-person release (`tests/agt01/test_qa08_feedback_poisoning.py`).

## 5. Calculations and charts

| Item | Behaviour |
|---|---|
| Deterministic calculations | `app/orchestration/calculations/engine.py` (Decimal, named formulas, currency checks) persisted by `domains/calculations/service.py` |
| Agent calculations | `calculate` tool, Decimal evaluator, receipt saved as a calculation run (`service.py:778`) |
| Charts | Values must appear in the question, the conversation or tool results (`agent.py` `unverified_chart_values`) |
| Model-written numbers | Every material figure is reconciled against evidence and receipts (`app/orchestration/figure_reconciliation.py`); unmatched figures withhold the answer or fail the release check |

## 6. Language coverage

UI text is English only. Professional answering is English only; the support matrix (`app/orchestration/language_support.py`) releases en/UK and en/US, with en/IN as a pilot. Other languages are detected and given an honest scope limit. Multilingual answering is **not implemented**, as the directive records.

## 7. Test coverage of the required failure cases

| Case | Status | Tests |
|---|---|---|
| Denial (tool / role) | Present | `tests/test_tool_policy.py`, `agt01/test_qa05`, `agt01/test_qa06` |
| No source | Present | `agt01/test_qa04` |
| Cross-tenant | Present | `agt01/test_qa05`, `tests/test_tenant_isolation.py` (Postgres integration) |
| Injected document | Present | `agt01/test_qa07`, `tests/test_untrusted_content.py` |
| Timeout | Present | `agt01/test_qa10` |
| Incomplete input | Present | `agt01/test_extra_controls.py` (currency mismatch, missing month) |
| Chart mismatch | Present | `agt01/test_extra_controls.py`, `tests/test_agent_loop.py` |
| Audit failure | Present | `agt01/test_qa10`, `tests/test_audit_batch_and_idempotency.py` |

## 8. Gap register

| Feature | Status | Evidence | Missing behaviour | Risk |
|---|---|---|---|---|
| Request context and pre-check (§03, §10) | CODE COMPLETE | `task_context.py`, `risk_classifier.py`, `agt01/test_extra_controls.py` | Uses the existing `TaskContext` rather than a new `RequestContext` (CR-04) | Low |
| Tool registry and per-step policy (§05) | CODE COMPLETE | `test_tool_policy.py`, `agt01/test_qa02`, `agt01/test_qa06` | Budget in tokens, not currency (CR-07) | Low |
| Bounded workflow (§05) | CODE COMPLETE | `test_workflow_state.py` | No resume of an interrupted run; a retry restarts it | Low |
| Retrieval and evidence bundles (§06) | CODE COMPLETE | `test_governed_kb_retrieval.py` | Demo B with real historical sources not recorded | Medium |
| Calculations and charts (§07) | CODE COMPLETE | `agt01/test_qa03`, `test_figure_reconciliation.py` | Data charts validated against tool results, not only receipts (CR-01); tolerance needs sign-off | Medium |
| Knowledge vs feedback (§08) | CODE COMPLETE | `agt01/test_qa08`, `test_review_loop.py` | | Low |
| Multilingual (§09) | CODE COMPLETE (scope limit only) | `agt01/test_qa09` | No other language launched (G7) | Low |
| Safety and approvals (§10) | CODE COMPLETE | `test_review_loop.py` (binding, maker-checker) | | Low |
| Model gateway (§11) | CODE COMPLETE | `test_model_gateway_single_path.py` | Gemini approval to be confirmed by Security; no processing-region data (CR-09) | Medium |
| Frontend states, audit (§12) | CODE COMPLETE | `frontend/tests/answer-state.test.ts` | Chart keyboard/WCAG review | Low |

## 9. Feature status records

Commit/tag: not committed yet (working tree on branch `Naresh-new`). Approvals needed for every feature: QA, plus Security (§05, §06, §10, §11), Domain Assurance (§06, §07), AI Risk (§10) and SRE (§12).

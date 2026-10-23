# Kriton reliability: validation (phases 3/6) and budgets (phase 5) — 22 October 2026

Built on `3e4792e` (PR #61, merged into `main` as `e958016` on 22 Oct; `main` has no other change since), in a separate worktree. Offline only: no model calls, no push, and no configuration, database or Tavily change.

## Phases 3/6 — arithmetic and concepts checked separately

### Figures (`figure_reconciliation.py`)

| Case (lease scenario) | Pushed branch | Now |
|---|---|---|
| `$42,123.64` amortisation (210,618.19 ÷ 5) | removed | kept |
| `$54,760.73` Year 1 expense, intermediate not shown | removed | kept |
| `$173,255.28` closing liability (two steps) | removed | kept |
| "83% of the economic life" (5 ÷ 6 years) | removed | kept |
| "75% or more … major part" (ASC 842 threshold, framed as the test) | removed | kept |
| "the lease term is 75% of the economic life" (stated as a fact) | removed | removed |
| Fabricated `$42,987.11`, `$87,345.19`; wrong "71%"; "growth was 83%" | removed | removed |
| Near-miss `$210,608.00` (210,618 − 5 − 5) | removed | removed |
| Dates, years, paragraph references (ASC 842-10-55-2), invoice/account/phone numbers, decimals, roundings | unchanged | unchanged |

**Rules added:**
- **One step from two verified figures** (the user's or the calculator's), for figures with **≥ 6 significant digits**. It chains for up to 3 rounds.
- **Sums and differences need comparable operands** (the smaller ≥ 1% of the larger). A count added to an amount is not a financial step. Without this, the near-miss `$210,608` passed as 210,618 − 5 − 5.
- **Two steps** for figures with **≥ 7 digits**, only when there are 16 or fewer verified numbers.
- **A percentage as a share of two user-given quantities of the same unit** ("5-year" ÷ "6 years"), only when the statement says what it is a share of.
- **ASC 842's 75%/90% thresholds and 90/95/99% confidence levels**, only in a statement that presents them as a threshold or a sampling confidence level.

**Measured:**
- Fabricated two-decimal amounts accepted: 0 of 4,000.
- Near-misses of the six real figures (± 1 to 1,000): this change accepts none. The pushed branch's older rules accept `$50,000 ± 1/5/6` (see below).
- Fabricated whole percentages "of the economic life": the change adds exactly one accepted value over the pushed branch, 83, which is the correct one.
- About 2.5 ms per check. The full suite runs in 64 s, the same as before.

**Pre-existing, tracked, not changed:** the older rules already accept:
- 14 small whole percentages (1, 2, 4, 5, 6, 7, 10, 11, 12, 20, 25, 30, 36, 80) in "x% of the economic life";
- a stated amount plus a small count (`$50,000 ± 1, 5, 6`).

Both are pinned as strict expected failures (20 cases) in `test_accounting_validation.py`, so a future fix shows up as an unexpected pass and the tests then become ordinary assertions.

### Concepts (`accounting_concepts.py`)

**Standard references.** A registered standard is replaced with the subject's standard **in the same framework** only when all of these hold:
- the sentence is about exactly one registered topic;
- it makes **no mention at all** of the cited standard's own subject (for example any "tax" for ASC 740 / IAS 12);
- the standard is not legitimately cited for that topic (ASC 350 / IAS 36 / IAS 38 also cover goodwill);
- the reference is not in a contrast ("not ASC 606", "rather than", "unlike", "formerly").

The answer then gets "Corrected: … The replacement is the standard for that topic in the same framework; confirm it applies to the entity's reporting framework and period."

- **Never changed (31 sentences tested):** cross-topic mentions, contrasts, superseded standards (ASC 840, IAS 18), other frameworks (Ind AS, FRS 102), PCAOB AS 3105 for issuers, IFRS 9 / IAS 2 impairment and write-downs, and unregistered standards.
- **Corrected (6 tested):** for example share options under "IAS 12 / ASC 740" become "IFRS 2 / ASC 718".
- **Found in review and fixed:** a first version wrongly changed 5 correct sentences, including "Goodwill is not amortised under ASC 350" and "Under IAS 12, the tax effect of the lease…".

**Method.** In a monetary-unit-sampling question, a statement using the attribute-sampling formula is removed and the answer states the MUS method; the answer is marked partial. A line naming or contrasting attribute sampling is kept, and the note is added only when something was removed.

### Limits
- The registry covers 10 topics' standard numbers and one method rule. It does not judge free-text reasoning; that needs the Phase 6 independent reviewer, which is not built.
- It does not decide which framework, jurisdiction or period applies to an entity.
- Figures more than two steps from verified numbers, or with fewer than 7 digits two steps away, are still removed.

## Phase 5 — measured, nothing changed

All 30 wordings were run offline (model scripted, first composition request):

| Measure | Value |
|---|---|
| Input tokens | median 3,902, max 4,580 |
| Context trimmed | 0 / 30 |
| Room for the answer | median 4,098 (completion cap 4,096) |

The completion cap binds first. Raising it is a separate decision, to be made after a cost review and a small live sample, neither of which has been run.

## Tests

- `tests/test_accounting_validation.py`: 78 passed and 20 strict expected failures (the known gaps).
- Full offline backend: **3,573 passed, 0 failed**, 22 xfailed, 65 s.
- Frontend: 227 passed; `tsc` and `eslint` clean.
- Diff against `3e4792e`: 8 files, +709 / −21; no conflict markers or stray files.

## Second transcript (22 Oct, 15:02–15:11): ten independent questions in one chat

Live log `backend/logs/dev.log`, server build `1984fa9` (pre-merge local code):

**Main cause (a regression from the Phase 1 resolver):** every question contained "Task for the **Bot**:". The resolver read capitalised words as company names, so it linked all ten questions (`named_party:Bot`, later `named_party:Average`).
- Up to 65 figures from unrelated scenarios were sent with each question.
- Input grew from 3,383 to 9,269 tokens and was trimmed to about 6,300–7,400 to fit the 8,000 limit.
- About 600–1,700 tokens were left for the answer.
- Three questions failed at the provider (`model_provider`), one escalated, and the others were cut off.

This regression is in `main` through PR #61.

| Cause | Fix (worktree) | Test |
|---|---|---|
| Capitalised words read as party names | A party must be introduced with a suffix ("Meridian Inc.", "Nexus Corp"); a new entity with its own figures starts a new task | Replay: all standalone, inputs 3,259–4,744 tokens, none trimmed; 2 new tests; all 30 earlier follow-ups still link |
| Agent path at GPT-OSS medium reasoning within the 4,096 cap | `GenerationBudget.create` sends `reasoning_effort="low"` for GPT-OSS (the standard path already did); callers can override | 4 tests |
| "US GAAP Lower of Cost or NRV **rules**" and "**currently** trading at $950" forced source-only answers | Applied-guidance words ignored when a named framework is applied to supplied figures; "currently trading at $X" with a price is not a lookup | 6 tests, including 3 real lookups that stay strict |
| Tool calls written as text (`【calculate: expression=…}】`) shown to users | Stripped in `normalize_citations` (closed or unclosed; needs a tool name and `key="…"` arguments) | 5 tests |
| AS 1105 (audit evidence) cited for control deficiencies | "Audit evidence" topic added; dash variants in references | 1 test |
| Correct unchecked figures labelled "did not match verified data" | Note now reads "could not be checked…"; disproved figures keep their own note | 1 test |

**Open, not changed:**
- A truncated answer on the standard path is discarded entirely ("Not answered — please try again").
- The planner adds search and market-data tools to fully supplied calculations.
- Low-precision derived figures the model computes without the calculator are removed (the EPS answer lost $79,000 / $1,459,000 / $2.61, all correct).
- Answers contain LaTeX (`\mathbf`, `\boxed`, `\begin{aligned}`) that the page shows raw.
- `main`'s "what is …" definition leniency makes "What is the latest share price…?" non-strict.
- The running server predates both the merge and these fixes.

Tests after this round: **3,592 passed, 0 failed**, 22 xfailed (known gaps).

## Resolver corrections after the acceptance run (22 Oct)

Acceptance tests (`tests/test_acceptance_oct22.py`) found three failures in the first resolver fix. Corrected, test-first:

| Gap | Correction | Now |
|---|---|---|
| "that amount" not a reference (dropping "that" to avoid "conclude that revenue…" went too far) | "that + noun" is a reference when the noun names a quantity (amount, figure, total…) or an item set out earlier (lease, contract…), and "that" does not follow a verb of saying or concluding | "Calculate the tax on that amount at 25%" keeps $180,000; "conclude that revenue…" and "auditors say that revenue…" do not link |
| CamelCase and lowercase-suffix names invisible ("EuroTech", "ParentCorp", "Titan Development corp") | Name tokens may be CamelCase; suffixes match in lower case; CamelCase names count without a suffix | Follow-ups naming these companies link to their scenario |
| Different companies sharing a first word linked ("Apex BioTech" → "Apex Manufacturing"; latent: "Vanguard Industrial" vs "Vanguard Energy") | The identity is the whole name. A short form ("Vanguard") refers to an entity only when the message names no other entity with that first word | Similar names stay separate; "For Vanguard Energy, recompute…" still links |
| Percentages counted as a new scenario's figures | Percentages and rates are parameters (`scenario_figures`) | A new rate does not detach a follow-up |

**Also found:** the older "task without its own figures" rule linked conceptual questions ("explain why…") to the previous calculation. It now applies to computational verbs only (calculate, compute, determine, prepare, record…).

**Results:** all 30 original follow-ups and paraphrases, all 13 scenarios alone and in one chat, and every acceptance check pass. Full suite: **3,624 passed, 0 failed**, 23 xfailed (20 known figure gaps, the open truncation item, 2 earlier).

**Still open (not complete):**
- **P1:** the standard path discards a truncated answer (pinned as a strict expected failure).
- **P2:** no clarification is asked when "that amount" could mean figures from several earlier scenarios; it resolves to the most recent.
- The model-assisted rewrite fallback is not designed.
- The running server is still the old `1984fa9`.
- Live numerical verification has not been run.

## Standard-path truncation and ambiguous references (22 Oct)

### P1 — truncated answers on the standard path
**Path traced:**
1. `groq_adapter._create` sees `finish_reason="length"` and raised `ProviderResponseIncomplete`, discarding the text.
2. The gateway passes the typed error up.
3. Orchestration audits it and returns `unavailable` ("Not answered — please try again").

**Change:**
- The exception now carries `partial_text` (prose only; a cut-off tool call carries none).
- On the standard path, `partial_output.usable_partial` keeps only finished statements: it cuts back to the last finished sentence or complete table row and drops an unfinished equation, a dangling list number or heading, a half row, or an open code/chart block. It returns nothing below 160 characters of finished text.
- A usable partial goes through **every normal release check**, gets "Incomplete answer: … Only its finished part is shown; any unfinished calculation or conclusion was left out." (so completeness is `partial`), ends with a visible "stopped here" note, and is **never cached**.
- An unusable partial fails exactly as before.
- The agent path is unchanged (tested).

### P2 — ambiguous "that amount"
A bare quantity reference ("that amount", "this figure", "these figures") with figures from **more than one earlier scenario** now returns `kind="ambiguous"`. The pipeline asks, before any model call:

> Earlier messages set out more than one scenario with figures:
> • $120,000 — "Nexus Corp sells a server for $120,000 and maintenance…"
> • $180,000 — "Our company's taxable profit for 2026 is $180,000."
> Which amount or scenario do you mean?

The reply is matched to one candidate by a figure ("the $180,000 profit") or wording ("the Nexus contract"). Only that scenario, plus the question, is used.

It is not asked when:
- only one scenario has figures;
- the previous message states exactly one amount;
- "these/those figures" (collective) follows a scenario that asked nothing;
- the company is named.

Unchanged: unrelated questions stay standalone, and conceptual questions are only linked when they directly follow a scenario that asked nothing (existing rule).

**Results:** 7 files changed in this round; no verification, claim-check or source-governance code touched.
- Full backend: **3,646 passed, 0 failed**, 22 xfailed (20 known figure gaps, 2 earlier).
- Frontend: 227 passed; `tsc` clean.

## Proposal (not implemented): model-assisted rewrite fallback

**Purpose:** resolve the messages the deterministic resolver cannot decide. It must not run on every request.

**When it runs (bounded):**
- Only when the resolver is uncertain: a message with a reference word and no resolved anchor, or a near-tie between candidate scenarios.
- Never for first turns, clear standalone or scenario-only messages, named-party links or clarification replies.
- Expected: a small share of turns. Measure the trigger rate offline on the fixtures before enabling.

**How:**
- A single call to the small model (gpt-oss-20b), low reasoning, ~300 output tokens, 3 s timeout, temperature 0.
- Input: the current message and the last few user messages, truncated.
- Output is constrained JSON: `{"depends_on": [turn ids], "standalone_question": "...", "confidence": 0–1}`.

**Safeguards:**
- Turn ids are validated against history.
- The rewrite may only cite figures already present in the chosen turns (checked deterministically).
- Below a confidence threshold, the same clarification as P2 is asked.
- On timeout, error or spend limit, the deterministic result is used.
- Runs in shadow mode first (logged, not used) and is compared with the deterministic decision on the 30 paraphrases, the 13 scenarios and mixed chats.

**Cost control:** per-request token cap; counted in the request budget; a feature flag, off by default.

**Acceptance before enabling:**
- No regression on the resolver suites.
- Lower ambiguity-question rate without new wrong links.
- Cost per 100 requests measured.
- Separate approval for any live run.

## Review fixes: ambiguity flow end to end (22 Oct)

The review traced the clarification through the real page and found three defects. All are fixed and tested on the history shape the page sends.

| Defect | Fix |
|---|---|
| The page replays only answers with text, so the clarification never returns; a reply such as "The $180,000 profit." was treated as standalone | The choice is read from the user's messages: a short reply (≤ 12 words, not a new calculation) naming exactly one candidate scenario, right after an ambiguous question |
| The choice was not kept: the next "Now …" follow-up went back to the other scenario | The question and reply are re-linked to the chosen scenario; "Now …" anchors the previous message's scenario, not the latest message with figures |
| "And …" follow-ups sent the whole chat (pre-existing) | They use the previous message's scenario; the whole history is kept only when that scenario has no figures |
| "it" not understood | "it"/"them" as the object of a task ("journal entry for it", "record it") refers back; "Why is it important …" does not (and "why" questions no longer count as calculations) |

An answered clarification (which lists every candidate) is no longer passed to the model.

**Results:**
- Targeted: 173 passed.
- Full backend (CI command): **3,658 passed, 0 failed**, 30 skipped, 22 xfailed (20 known figure gaps, 2 earlier).
- Frontend: 227 passed; `tsc` and lint clean.
- 22 files changed against the base; no conflict markers or stray files.
- No commit, push or model call.

## Live check failures, fixed offline (22 Oct)

The approved live check (5 questions, 70,760 tokens) refused Nexus, EPS and
LCNRV, removed correct DuPont figures and showed raw LaTeX, and answered WACC
with "inputs unavailable". Diagnosed and fixed with no model calls
(`tests/test_live_check_oct22_offline.py`).

| Failure | Root cause | Status | Fix |
| --- | --- | --- | --- |
| Nexus, EPS, LCNRV refused | The harness ran as role `ACCOUNTANT`, which no permission set names. Every tool call was refused ("Policy refused 'calculate' (role_not_allowed)…") and the model answered with the out-of-scope text in its own words (curly apostrophe). Every real role may calculate. | Probable (mechanism reproduced offline; model reaction not re-run) | Harness uses `Admin`. Tests: all 13 scenarios pass every backend scope check; real roles may calculate; an unknown role is still refused. |
| — | Agent calls sent `reasoning_effort="low"` by default (added in this branch) | Possible contributor, unproven | Opt-in via `AGENT_REASONING_EFFORT` (default empty = provider default, as on main) |
| WACC "inputs unavailable" | Same refused tools, plus the planner read "2,000,000 outstanding shares" / "shares of common stock" as a market-data lookup for an invented company | Probable | Share-capital wording no longer plans `get_market_data`; "fiscal year" no longer plans an economic indicator. Real lookups (share price, ticker, market cap) unchanged. |
| DuPont $1,750,000 / $3,100,000 removed | No rule for the average of two figures on one line of the question | Confirmed | Average of two money amounts on one line, within 2× of each other. Fabricated acceptance 44 → 45 of 12,352. |
| DuPont 26.74% removed | `= **26.74 %**`: bold and a spaced % stopped the equation being read | Confirmed | `plain_arithmetic()` shared by the figure check and the arithmetic check. The arithmetic check also missed every wrong bold result before. |
| Raw `\underbrace` | `latex_to_plain` did not handle it | Confirmed | `\underbrace`/`\overbrace` → "X [label]"; `\boxed`, `\mathbf`, aligned rows, `{,}` inside fractions. "&" outside aligned rows kept. |
| (found on the way) "2026," read as an operand | Number token kept its trailing comma, so the year filter missed it | Confirmed | Comma stripped before the year test |
| (found on the way) wrong WACC steps accepted | A figure whose own statement shows its equation could be rescued by a pair of other numbers on the line | Confirmed | That equation decides: it must hold on verified inputs. If it does not hold, the arithmetic check removes it and names the correct result. Formula constants 1, 2, 100 and a stated % written as a fraction (0.21) count as verified inputs. |

Not verified: what the model now answers. A further live test needs approval.

## 18-answer manual review, fixed offline (22 Oct)

A manual review of 18 answers from the worktree build (port 3001) found
three separate failure types. Fixed with no model calls
(`tests/test_review_oct22_offline.py`, fixture `review_questions_20261022.json`
with the 6 new questions and hand-derived answer keys for all 18; the
13-question fixture is unchanged).

**1. Figure check deleting correct work**
- Agent checks run on LaTeX-free text (`\$468{,}000` was read as "$468").
- An amount at a rate in the same statement (`| $7,000,000 | 7% | $490,000 |`).
- A table cell that adds or subtracts verified cells of its row (NPV EBIT,
  cash flow) and a column total under its addends (LBO total interest).
- An amount the question states at a percentage it states (MACRS depreciation).
- A percentage restating a verified decimal (0.103218 → 10.32%).
- Tried and removed: two steps within one question line (+111 of 14,312
  fabricated accepted; £18 + 6,000/6,000 "verified" £19).
- Measured on 14,312 fabricated figures: 1.56% → 1.70% accepted, none lost.
- Known gap (pre-existing): the one-step rule accepts a wrong cell reachable as
  one operation from a row figure and any verified figure (EBIT 150,000 =
  200,000 − 50,000 NWC).

**2. Evidence policy**
- Supplied figures labelled "current … is $X", "a $3,000 … threshold" and the
  line item "Current Income Tax Payable" are no longer lookups (FX, Benford,
  Apex were strict).
- A supplied scenario that names a framework (US GAAP, ASC, PCAOB) without
  needing a statutory lookup gets `PROFESSIONAL_APPLICATION_INSTRUCTION`
  (answer every part from professional knowledge; no statutory rates, thresholds
  or deadlines the question does not give), is not forced to search first, and
  is labelled "General explanation — not source-verified" when uncited.
- Still strict: the spin-off's US tax-code treatment (jurisdiction-specific),
  the convertible (its "current underlying stock price"), and genuine lookups.
- Planner: a supplied interest rate is not an economic indicator; a scenario
  with ≥ 3 own figures and no live/listing wording plans no market lookup;
  converting a bond into shares is not a currency conversion.

**3. Formatting**
- Tool remarks removed ("(tool – “NRV total A”)", "(derived manually)",
  sentences about "the exact calculation tool").
- `\tau`, `\beta` and other Greek letters, `\big`, `\log`, `\sqrt`, `_{x}`.
- "General explanation:" replaces the whole sentence, not its tail.
- A blank line after a bold heading line.

**4. Reasoning errors (not fixable offline)**
Apex ignored the NOL ($315,000 payable instead of $105,000; $273,000 expense
instead of $147,000); the recap's interest coverage was wrong (4.22×, not
3.33 → 2.33); DuPont's 2025 averages were invented; LCNRV wrote "12 Dec".
These pass every check. Answer keys are in the fixture; the grader catches the
saved Apex answer. Verifying any improvement needs an approved live run.

**Also fixed:** `execution.py` read `AGENT_REASONING_EFFORT` from settings
objects that do not have it (a test fake), which hung the full suite.

Backend 3,819 passed, 0 failed (30 skipped, 22 xfailed).

## Pre-PR fixes from the diff review (22 Oct)

- **D1 — tool-tag cleanup deleted real text.** The pattern removed any
  parenthesis with "tool" before a dash or colon and any sentence naming "a
  calculation tool": "(a machine tool: cost $50,000)" lost its figure. Now
  only Kriton's own forms go: "(tool – “label”)", "(calculated with tool –
  see calculation “label”)", "(derived manually)" and sentences about "the
  exact calculation tool". Ordinary prose is kept (tested).
- **D2 — removal notes counted as content.** `review_release` ignored only the
  new "did not match its own calculation" note; the "could not be checked"
  note counted as content, so an answer of notes alone could be shown.
  `claim_verification.is_removal_note` covers both and is used there and by
  the agent's `_substantive`. Notes alone go to review; content beside a note
  is kept.
- **R2 — mixed answers unlabelled.** The general-explanation label needed the
  whole answer to cite nothing. A professional-application or general-guidance
  answer that cites some sources and explains the rest uncited now carries
  `MIXED_SOURCES_NOTE` (statements without a source reference are professional
  knowledge; cited ones are supported by their source; calculations are checked
  separately). All-cited answers get no label; all-uncited keep
  `GENERAL_EXPLANATION_NOTE`.
- **Grader** (`tests/answer_key.py`): regular expressions per point; whole
  numbers only; the convertible's $2 must sit beside "premium", the LBO's 0
  beside "sponsor equity"; "nonrecognized" is never read as "recognized"; the
  LCNRV date is checked; known wrong values and reasoning are contradictions
  (Apex NOL ignored, recap 3.33 → 2.33, DuPont's invented FY2024 balances,
  "12 Dec"). Keyword points (controls, VIE) show coverage, not correctness.

### Answer keys awaiting accountant review (not validated)

| Scenario | Assumption in the key | Alternative |
| --- | --- | --- |
| Dividend recap | Cash-on-cash = $610,400 ÷ $2,000,000 = 30.52%; the dividend is a return of capital | $3,000,000 ÷ $2,000,000 = 150% |
| Carve-out | Matrix sells existing shares: NCI $300,000, APIC $200,000 | NewTech issues shares: NCI $400,000, APIC $100,000; parent-only treatment unresolved |
| WACC | Exact YTM (≈10.33%) and approximation (≈10.32%) both accepted | "YTM method" may require the exact yield only |
| NPV | No salvage, no tax shield on the $138,240 remaining book value | Including the $29,030 shield changes FCF Y4 and NPV |

Recorded in the fixture's `review_status`; values unchanged until confirmed.

## Final review follow-ups (22 Oct)

The external diff review returned "Fix before PR" for R1; fixed offline.

- **R1 — confirming a current rate.** "Is the current repo rate at 6.5%?" and
  "Is the current exchange rate of 83 INR per USD correct?" did not require
  sources (already so on the pushed base). `calculation_service.verifies_current_fact`
  recognises a sentence that asks whether a current rate, price, threshold or
  limit is right (an "is/are/confirm/check/verify" opener, or a question ending
  "correct / still in force / up to date"), with a time word and a fact word.
  Such a question is a lookup and never a supplied scenario. Giving a rate to
  work with ("the current spot rate is $1.35", "using the current repo rate of
  6.5%, compute …") is unchanged. Of 301 benchmark and fixture questions, none
  changed decision. End to end, an uncited "Yes, it is correct" is not
  released; the answer says the evidence does not establish it.
- **R2 — citation placement.** Detection is per sentence and per table row: a
  sentence without its own [REF-N] counts as uncited, so a paragraph cited
  only at its end has its earlier sentences labelled (conservative), and a
  marker on its own line cites nothing. The label stays answer-level; tests
  pin each placement.
- **D3 — bold results** are now read by the arithmetic check (behaviour change,
  for the PR description): a wrong bold result is flagged where it previously
  passed unchecked; correct bold results and bold prose are unaffected (tested).

### Second review round
- **R1 paraphrases.** "Could you verify whether the current repo rate is
  6.5%?", "Kindly confirm the current GST rate …", "I need to know whether …"
  were missed (no recognised opener). A verifying verb anywhere now counts when
  a time word follows it ("verify … current", "confirm … latest"); the order
  keeps "Using the current repo rate of 6.5%, compute … and check that the
  interest is correct" a calculation. 301 benchmark and fixture questions:
  none changed.
- **R2 short claims.** A six-word minimum let "Titan consolidates Silo."
  through unlabelled. Statements are now skipped for what they are — headings,
  lead-ins ending in ":", table header rows, separators, removal notes,
  calculations, fragments under three words — not for their length.

### Third review round (v3)
- **R2 two-word claims.** A three-word minimum still skipped complete
  assertions such as "Rates increased.". A two-word sentence now counts when it
  ends like a sentence and its last word is a past tense or a verb from a short
  list ("Titan qualifies.", "Revenue rose."); pointers and labels ("See
  above.", "Not applicable.", "Journal entries.", "Key points.") and one-word
  replies ("Yes.") do not. A two-word claim whose verb is not in the list and
  not in the past tense is still skipped.

### Fourth review round (v4)
- **R1 both directions.** Five phrasings with no time word ("Is the repo rate
  6.5%?", "Repo rate still 6.5%?", "…, isn't it?") were not recognised by
  `verifies_current_fact`; on this branch and on the base they were already
  strict by an older route (the words "repo", "GST"), so the release outcome
  was safe, but the detector now recognises yes/no questions, tag questions
  and "<rate> still/now <figure>?" with a stated figure. In the other
  direction the v3 detector sent five calculation questions on a supplied rate
  to strict sourcing (a regression against the base): "I know the current rate
  is 7%; compute …", "does the current exchange rate of $1.12 create a gain",
  "is the current price of $45 above book value". Bare "know" and "tell me" no
  longer count (only "know whether/if", "tell me whether/if"), and a sentence
  that asks about a calculation on the rate (compute, apply, create, above,
  below, use, gain, …) is never a confirmation. Two such questions ("applied
  correctly in the schedule", "if the tax rate is 21%") stay strict exactly as
  on the base. Safe-direction edge: a yes/no question about a stated rate
  ("Is the 7% coupon rate on the bond fixed?") now needs a source.
  301 benchmark and fixture questions: none changed.
- **Backend lint.** No backend linter is configured (CI lints the frontend
  only; ruff and flake8 are not installed). The missing blank lines before
  `_is_short_claim` are fixed; long lines follow the existing code's style.
- **Test counts** below were run with `TZ=UTC`, as CI runs.

## Frontend change in this branch (Ask Kriton chat URL)

`frontend/app/ask-kriton/page.tsx`, `frontend/lib/ask-kriton-storage.ts`,
`frontend/tests/ask-kriton-chat-url.test.ts`. Behaviour change: opening plain
`/ask-kriton` (dashboard, sidebar, page links) now starts a new chat instead
of reopening the most recent one; the open chat is written into the address
as `?chat=<id>`, so a reload or a shared link keeps it, and an unknown id is
ignored. Reported on 22 Oct ("I open Ask Kriton from the dashboard and it
shows the previous chat"). It can be split into its own PR; it has no backend
dependency. Covered by the 4 tests in `ask-kriton-chat-url.test.ts` (part of
the 227 frontend tests).

## Final state (supersedes earlier sections where they differ)

This log is append-only; for the PR description use this section.
- **Reasoning effort:** agent calls send no `reasoning_effort` by default
  (provider default, as on main); `AGENT_REASONING_EFFORT=low` opts in. The
  earlier "low by default" fix was reverted.
- **Conversation resolver:** companies match by whole name, including
  CamelCase names and lowercase suffixes, not only "Inc/Ltd" suffixes;
  "that amount" with several earlier scenarios asks which one is meant.
- **Figure check:** equation shown → that equation decides; rate × amount,
  row arithmetic, column totals, stated amount × stated rate, averages of two
  same-line amounts, percentages restating verified decimals. G1 remains.
- **Arithmetic check:** reads bold and spaced-% results (D3).
- **Evidence policy:** supplied scenarios under a named framework are
  answered from professional knowledge with `PROFESSIONAL_APPLICATION_INSTRUCTION`
  and labelled (`GENERAL_EXPLANATION_NOTE` when uncited, `MIXED_SOURCES_NOTE`
  when partly cited); confirming a current rate, price, threshold or limit
  always needs a current source (R1).
- **Cleanup:** only Kriton's own tool tags are removed (D1); removal notes are
  never answer content (D2).
- **Tests (TZ=UTC):** backend 3,943 passed, 0 failed, 30 skipped, 22 xfailed;
  review tests 216 passed; frontend 227/227, typecheck, lint, build pass.

### Fifth round (v6)
- **FX test time zone (fixed).** `test_batched_calculator.py` dated its ECB
  rate with the local date while the freshness check uses UTC; between 00:00
  and 05:30 IST two tests failed (also on the base). The fixture now uses the
  UTC date. Test-only change; the full suite passes with `TZ=Asia/Kolkata` and
  `TZ=UTC` (3,943 passed, 0 failed, 30 skipped, 22 xfailed).
- **Blank lines** after `is_removal_note` in `claim_verification.py`.

### Manual test, 23 Oct (port 3001) — offline fixes
A read-only look at the audit records (`audit_events`, `SET TRANSACTION READ
ONLY`) showed why four answers came back as "The generated explanation could
not be verified. Here is the verified working":
- **Dividend model:** the arithmetic check reported "1.728/(1.092) equals 1.58,
  not 1.45" — the bold clean-up (D3) removed the power operator `**`. Fixed:
  `**` between a digit or ")" and a digit or "(" is kept. A regression of this
  branch, now tested.
- **Hedge, TDR, cash conversion cycle:** any one mismatch in the agent's
  answer replaced the whole explanation (TDR and CCC also hit the step limit
  first). Now only the statements with a disproved figure are removed, the
  correct result is named in the limitations ("did not match its own
  calculation"), and the bare working is shown only when nothing else is left.
Routing fixes (none of 301 benchmark and fixture source decisions changed):
- "materiality threshold … is set at $750,000" is the user's figure.
- An accounting or audit task on supplied facts (≥ 2 figures) that plans a
  search is answered from professional knowledge even with no named standard
  (inventory count observation).
- A supplied exchange rate ("1.10 USD per EUR", "₹83.20 per USD", "the current
  spot rate is 5.00 BRL per $1") is used: no live-rate fetch, no "latest rate"
  gate, and the conversion plans the calculator. "Do not retrieve a live rate"
  and "without checking the current repo rate" are instructions, not requests.
  Live-rate requests ("at today's rate", "Convert it to pounds at the latest
  rate") still fetch it — the benchmark comparison caught "convert it to
  pounds" losing its fetch after the convertible-bond change, fixed here.
- A supplied interest or inflation rate ("from 8% down to 4%", "inflation in
  Brazil … 6.0%") no longer plans an economic-indicator lookup.
Answer keys added for pension (PBO 4,837,500; funded −267,500), segments
(profit threshold 137,000; 75% test on external revenue, 94%) and TDR (gain
480,000; 0% effective rate), all **awaiting accountant review**; the saved
wrong answers are recorded as contradictions. These are model reasoning
errors; no offline check fixes them.
Tests: `tests/test_manual_oct23_offline.py`; backend 3,985 passed, 0 failed
(30 skipped, 22 xfailed) under IST and UTC.

### Release checklist: still open, not solved
- R1: confirmation detection is pattern-based (opener, verifying verb before
  a time word, or a closing "correct / still in force" question, with a fact
  word). It was tested on 16 phrasings and 301 benchmark questions; untested
  phrasings may still be read as supplied figures and escape the source
  requirement.
- R2: two-word claims are recognised from a verb list and past tenses only.
- G1: the one-step rule can accept a wrong figure reachable as one operation
  from a same-line figure and any verified figure; 1.7% of synthetic
  fabricated figures pass overall.
- R2: the mixed-sources label is answer-level, not per sentence.
- Seven answer keys await an accountant (recap, carve-out, WACC, NPV,
  pension, segments, TDR).
- Model reasoning errors seen on 23 Oct (pension PBO, segment test bases, TDR
  gain vs loss, IAS 2 NRV) pass every arithmetic check; they need an
  accounting-method review step or a stronger model, tested live.
- A wrong result written with the power operator ("1.09**2") is not checked
  by the arithmetic check (as on the base).
- Controls and VIE keys measure coverage only; verify by hand before using
  them as quality gates. Passing the grader is not an accounting-quality
  certification.
- Live-model reasoning (Apex NOL, recap coverage, DuPont invented balances,
  LCNRV date) is unverified until an approved live run.
- The convertible question still plans an unneeded market-data lookup.
- The 13-question acceptance fixture was created in this branch, not a
  baseline file; `backend/evals` is byte-identical to the base.

# Durable conversation inputs and numerical identity — 19 October 2026

## Implemented

Kriton now has a server-side turn ledger keyed by authenticated tenant, user and conversation. Inputs are retained after the safety and certification checks, before model generation. Supported application calculations are saved independently of whether the written answer succeeds. A failed model response therefore does not erase the inputs needed by the next request.

The request flow hydrates missing history from that ledger. Supported statement scenarios retain their original baseline and explicit percentage revisions. Browser history cannot silently replace an established server statement baseline; new corrections must be supplied in the current query. Verified application results can also enter the context for a relevant narrative follow-up, clearly identified as earlier calculations that require recalculation when inputs change.

Memory retains at most 64 turns per user/conversation, reserving a slot for the last structured state or explicit context reset. Turn expiry is 30 days. Expired rows are excluded from reads and removed by the bounded workspace retention job or subsequent conversation cleanup. Queries longer than the 8,000-character history allowance are not silently truncated into durable inputs. They continue through the existing request path without this persistence guarantee.

No assistant prose, client-submitted calculation snapshot, permission or externally asserted current rule is promoted into a verified application fact. The application still screens restored history. Database reads and writes explicitly scope tenant, user and conversation; PostgreSQL RLS uses tenant and user predicates for both reading and writing. The new foreign keys allow private memory to be removed with its owning user or tenant.

## Numerical verification

Application calculation facts now carry a stable fact ID, source query, metric, Decimal value, kind, currency and supported period/scenario identity. A metric such as current ratio remains a metric; its name alone does not make it a current-period value.

The release checker additionally verifies conclusive table cells against their metric and explicit period/scenario. It detects a valid operating-profit number placed in a gross-profit row, reversed current/prior or original/revised columns, wrong currency, and money relabelled as a percentage. Display precision is explicit: trailing zeroes in a whole-pound amount do not authorize rounding to the nearest thousand. Existing equation, citation and attribution checks remain in place for other shapes. Ambiguous headings and multi-number workings are not guessed by the new checker.

This is typed identity for supported application calculations, not a complete dependency graph for every free-form tool result or financial document. General agent calculations retain their existing calculator receipts and verification paths.

## Database activation

Local compatibility update: when the existing development-only fingerprint
override is enabled, an absent memory table now permits startup with supplied
history. Existing-table security checks remain mandatory. See the
[startup repair](kriton-startup-timeout-repair-2026-10-19.md). Production still
requires the migration and the normal fingerprint checks.

The additive migration is `a6t7u8v9w0x1_conversation_turns`, following `z5s6t7u8v9w0`. It creates the private `conversation_turns` table and installs PostgreSQL RLS. It does not rewrite existing tenant or user data. The existing setup routine also includes the table in security-policy verification and the startup fingerprint.

The migration was tested against a temporary local SQLite database, including a second upgrade invocation. **It has not been applied to the shared database.** Production PostgreSQL RLS execution and live migration have not been verified here. Durable memory requires database preparation before activation. Until the table is available, memory reads/writes report a safe warning and the answer flow can use supplied history; production startup still requires its normal schema fingerprint checks.

The repository's database preparation entry point, run against the reviewed target environment, is:

```sh
cd backend
.venv/bin/python scripts/setup_database.py
```

That command performs migrations, compatibility setup, security-policy verification and fingerprint preparation. It was not executed against the user's configured database during this work.

## Validation

The focused storage, migration and typed-fact checks pass using local temporary SQLite databases and scripted model failures. They cover recovery of both manufacturing scenarios with no browser history after a failed first answer, isolation by tenant/user/conversation, replay deduplication, expiry and physical retention, long-conversation compaction, browser-history conflicts, narrative context, exact numeric identity, currencies, units and rounding.

Final backend suite: **3,190 passed**, 21 skipped and 2 expected failures, with 128 warnings primarily from existing mocks and dependencies. The migration chain has one head (`a6t7u8v9w0x1`); whitespace and unresolved-merge checks passed. No Groq calls or tokens were used. No frontend code changed in this phase.

## Remaining work

Shared provider-capacity scheduling across workers and a complete typed dependency graph for arbitrary agent calculations remain separate architecture work. Live answer quality still requires manual testing in the prepared environment; passing scripted tests does not establish equivalence to ChatGPT or Claude.

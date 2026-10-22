# Local startup failure behind the timeout report

The user reported a timeout for a short revenue/profit/cash-flow question,
request `idem-1792400058239-we0hpy`. This ID did not appear in the local
backend request logs. The frontend uses its timeout message for both a
server timeout and its own 120-second abort, so the wording alone does not
establish that question processing or a provider request started.

The local development backend log showed repeated startup failures at
`_verify_security_policies`. A read-only PostgreSQL catalogue inspection
confirmed that `conversation_turns` was the only missing table and tenant
policy among the tenant-scoped tables. The new durable-memory migration
had not been applied. A local health request timed out even though the
development reloader retained the listening socket.

The earlier memory implementation supplied runtime missing-schema fallback
but made the new table mandatory at startup. That incompatibility prevented
the fallback from being reached. The repair allows an absent memory table
only when the existing local-development schema-fingerprint override is
enabled. Supplied history remains available through the existing DAO
fallback. If the memory table exists, RLS and its policy remain mandatory.
All other required policies remain mandatory. Production still requires
the migration and the normal schema fingerprint.

Startup failures now identify the table names with missing policies.
No schema or application data was changed. Durable server memory still
requires the reviewed migration before it is available.

After automatic reload, `/health/live` returned HTTP 200 with
`{"status":"alive"}` and `/health/ready` returned HTTP 200 with
`{"status":"ready"}`. Focused startup, memory and migration tests passed
(32 tests). The full offline backend suite passed: 3,201 passed, 21 skipped,
2 expected failures and 130 warnings. No model-provider calls were made. This verifies recovery of
the local server, not a live answer to the user's question or availability
of another deployment the browser might be configured to use.

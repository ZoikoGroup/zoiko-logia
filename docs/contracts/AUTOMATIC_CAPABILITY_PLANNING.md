# Automatic capability planning

Users provide a natural-language request, optional context, and optional
attachments. They do not have to select a workflow name.

The planner uses request structure and intent signals to select a broad,
versioned task contract and compose a plan from registered capabilities:

- `document.retrieve`
- `document.extract`
- `source.research`
- `policy.lookup`
- `numeric.calculate`
- `numeric.compare`
- `evidence.cite`
- `chart.generate`
- `response.compose`

The plan is descriptive, not authoritative. It cannot invent tools. Task
contracts validate required context, engagement authorization protects every
professional operation, and the existing orchestration deadline bounds
execution.

Jurisdiction and framework are independent context values. They do not create
country-specific workflow types. Arbitrary jurisdictions and frameworks can be
represented; execution depends on retrieval finding eligible authoritative
sources for that context.

When exactly one engagement is authorized, professional work may select it
automatically. When several are available, the system asks for scope rather
than guessing. Document content is never inspected to bypass authorization.

The API returns `workflow_plan` with:

- `task_type`: internal validation family;
- `detection`: automatic or explicit compatibility override;
- `confidence`: bounded planner confidence;
- `reason_codes`: observable decision signals;
- `steps`: registered capabilities and their reasons.

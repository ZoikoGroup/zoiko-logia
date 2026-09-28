# Real evaluation and release qualification

**Contract version:** `f8.1`

Release qualification uses actual candidate executions and human judgments.
Gold-answer safety checks, empty-dataset defaults, fixed metric values and
simulated promotion evidence are prohibited.

## Dataset controls

- Datasets are tenant-owned, versioned and assigned to a development or release split.
- Cases record trusted task context, expected sources, claims and calculations,
  acceptable statuses, risk, jurisdiction, language, document family and reviewer provenance.
- Frozen datasets are immutable through the evaluation API.
- Exact query/document-family/source fingerprints are checked across splits.

## Candidate execution

The submitted candidate manifest is canonically hashed and must equal the
declared configuration hash. Every case invokes the real Ask Kriton
orchestration path. The result stores the actual response, route, evidence IDs,
latency, mechanical source metrics and operational failure state.

An empty dataset is `NOT_EVALUATED`; it never receives synthetic metrics.

## Review and scoring

Every executed case requires a qualified reviewer judgment before finalization.
Judgments record verdict, metric scores, critical errors, notes and optional
adjudication. Final metrics are computed only from executions and judgments.
Slice scorecards are emitted for jurisdiction, risk and language.

## Promotion gates

Promotion requires a complete reviewed run, matching manifest hash, passed
contamination scan, all thresholds, no observed critical error and the approved
minimum case count (300 unless the ratified threshold set specifies otherwise).
Mandatory failures cannot be overridden through residual-risk acceptance.
The authenticated release approver, not a request-body identity, is recorded.

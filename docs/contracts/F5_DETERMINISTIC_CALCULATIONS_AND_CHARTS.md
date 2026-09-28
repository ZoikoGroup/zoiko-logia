# Deterministic calculations, statistics and charts

## Invariants

- Authoritative arithmetic uses `Decimal`, explicit rounding and a versioned rule.
- Completed calculation runs are tenant-scoped, persisted and append-only.
- The model may explain a result but cannot replace its stored value.
- Verified chart values originate only from a calculation result or typed live observation.
- Legacy model-authored chart fences remain supported for compatibility but are not labelled verified.
- Division by zero, malformed provider values and incompatible observation units fail closed.

## Implemented operations

- explicit arithmetic (`+`, `-`, `*`, `/`);
- sum and difference engine operations;
- percentage and percentage change;
- variance (`actual - budget`);
- straight-line depreciation.

Every result records its operation, `:v1` rule version, inputs, output, unit,
`ROUND_HALF_UP` mode, scale and calculation ID.

## Typed statistics

Frankfurter exchange-rate observations and DBnomics/World Bank observations now
carry indicator, decimal value, unit, period, provider, URL and freshness fields.
When a visual is requested, compatible observations can produce a backend-owned
verified chart. Provider prose remains available for citations and backwards
compatibility.

## Remaining release work

- bind spreadsheet values to exact sheet/row/cell evidence IDs;
- matching and reconciliation with explicit unmatched items;
- currency conversion using a verified dated FX observation;
- persist all live observations independently of answer records;
- add official policy-rate and national-statistics connectors;
- qualify rounding and numeric tolerances with domain owners;
- run golden boundary and end-to-end numeric/chart evaluations.

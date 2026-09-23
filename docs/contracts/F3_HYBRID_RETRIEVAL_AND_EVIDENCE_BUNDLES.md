# Hybrid retrieval and evidence-bundle contract

## Implemented baseline

- The server creates a bounded, versioned retrieval plan.
- Candidate source metadata is filtered by tenant boundary, approval state,
  jurisdiction, framework, effective date, revocation, supersession and the
  explicit retrieval right before passage content is loaded.
- Lexical passage ranking is deterministic and limited to a fixed top-k.
- Model-transmission and display/summary rights are checked independently
  after retrieval.
- Selected passages carry stable source/version/passage IDs, locators, hashes,
  rank, score and retrieval method.
- Exclusions and source conflicts are explicit bundle data.
- The final manifest and its entries are tenant-scoped and append-only.
- Replay reloads the selected passage IDs and verifies each content hash.

## Failure behavior

- Unknown, denied, expired, revoked, superseded or context-inapplicable rights
  exclude the candidate before its content is ranked.
- No matching eligible passage produces insufficient/restricted evidence; it
  does not silently promote a source title into model evidence.
- A passage missing during replay, or whose hash differs, is an integrity
  failure and cannot be supplied to the model.
- Conflicting selected source versions produce `conflicting_sources`.

## Deliberately not claimed

The current production-capable baseline is lexical. Vector retrieval remains
disabled until an embedding index, source-right filtering at its candidate
boundary, an expert-labelled evaluation set and a measured rollout threshold
exist. Web and live-data connectors remain separately labelled external
evidence; they are not silently represented as registered governing sources.

## Release requirements

Apply Alembic revision `n3g4h5i6j7k8`, register an owner-approved passage
corpus with explicit rights, run retrieval evaluation by jurisdiction and
framework, and confirm that excluded passage text never appears in captured
model payloads.

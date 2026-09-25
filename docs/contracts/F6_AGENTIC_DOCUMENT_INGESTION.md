# Agentic document ingestion contract

**Contract version:** `f6.1`

The ingestion agent is bounded to registered capabilities. It first attempts
native extraction. OCR is selected only for scan-like PDF/PPTX failures and
only through an approved adapter. Uploads can be staged in private object
storage and processed by a Celery worker; broker messages contain identifiers,
never document bytes. OCR output is `needs_review`; it never enters retrieval
automatically.

## States

`pending → extracting → ready | needs_review | failed`

Only `ready` documents are retrievable. `needs_review` represents potentially
useful but unapproved evidence; `failed` represents corrupt, unsupported, or
otherwise unusable input.

## Recorded evidence

Each document records its content hash, job ID, parser version, method,
coverage, confidence, processing plan, review reason, and processing time.
Chunks retain a locator, structured location placeholder, confidence, and
immutable original content alongside optional reviewer correction metadata.

## Safety boundaries

- Native extraction bypasses OCR.
- No configured OCR adapter means explicit `needs_review`, not silent failure.
- OCR output requires reviewer approval before publication.
- Retrieval continues to require `status == ready` and tenant/user scope.
- The agent cannot override authorization, retention, resource limits, or
  evidence publication rules.

## Worker and OCR configuration

`DOCUMENT_ASYNC_INGESTION=true` stages the original before dispatching
`documents.process`. Redis is the broker/result backend. A broker dispatch
failure falls back to processing the already-staged document in the API process
so an upload is not stranded.

`DOCUMENT_OCR_URL` enables the provider-neutral HTTPS adapter. The endpoint
receives base64 content, extension, and selected targets and returns `segments`
with `locator`, `text`, and optional `tabular`. `DOCUMENT_OCR_API_KEY` remains
worker-side. OCR output remains review-gated.

`GET /kriton-workspace/attachments/{id}/review` returns original review chunks.
`POST` to the same path records corrections and an approval/rejection decision.
Corrections retain original content, reviewer, reason, and timestamp.

## Remaining production slice

An approved OCR service still must provide true page/region targeting,
per-region confidence, residency/retention guarantees, and cost limits. Malware
scanning and a richer reviewer UI remain deployment gates.

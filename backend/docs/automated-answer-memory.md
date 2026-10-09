# Automated answer memory

Ratings are signals, not evidence or model training. Positive feedback saves
memory only after successful validation and an explicit authoritative release
check, with no degraded or escalated outcome. External evidence is retained
as original URLs with SHA-256 content fingerprints in source_refs.

Negative feedback, including numerical questions, retires matching memory and starts a bounded correction
through the normal answer pipeline. Only changed, verified corrections with
source snapshots are saved. Memory is untrusted guidance and receives no
citation IDs. Every fingerprint must match independently retrieved evidence
before reuse. Memory expires after 90 days; tenants, amounts, historical years
and opposite questions are isolated. Normal release checks still apply.

A failed verifier returns an evidence gap for lower-risk valid requests.
Existing high-risk and safety failures retain the review route. Successful
release checks are explicitly audited.

Limitations: comparison covers retrieved snippets, not whole-page monitoring.
Legacy memory without fingerprints and governed-only answers are withheld.
Background corrections are in-process and do not survive worker restart.
This does not introduce durable jobs or update model weights. Feedback is not
an independent accuracy benchmark. Regression tests cover feedback, tenant
isolation, dates, source changes, missing provenance and verifier outages.

On a repeated exact question, the latest persisted rating for that user supplies an untrusted rejection critique when it is negative. This survives loss of an in-process correction task and changes the model-answer cache input. Numerical corrections are not saved as reusable factual memory. A thumbs-up does not imply that an incomplete answer is correct; incomplete tax coverage and explicit evidence gaps cannot enter reusable memory.

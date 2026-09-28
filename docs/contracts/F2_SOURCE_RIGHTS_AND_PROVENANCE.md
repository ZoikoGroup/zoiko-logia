# Source rights and provenance contract

**Contract version:** `f2.1`

## Invariants

1. Every governed source has a stable source identity and one or more exact versions.
2. A version is identified by its SHA-256 content hash. Duplicate non-empty hashes are rejected per tenant.
3. Approved version content and its passages are immutable. Lifecycle state and append-only rights decisions remain separately changeable.
4. Every passage has a stable ID, exact locator, sequence, language, content hash, and translation lineage when applicable.
5. Customer uploads remain customer evidence and never become governing sources through this registry.
6. Rights are evaluated for an exact version, operation, tenant, jurisdiction, framework, effective date, and time.
7. A missing, expired, unknown, revoked, superseded, or inapplicable right is a denial.
8. Rights changes append a higher `rights_version`; previous decisions are preserved.
9. Retrieval checks `retrieval` rights before returning candidates. Model context checks `model_transmission` independently. Display and summary rights determine exposure.
10. Source use is recorded against bundles and released answers so revocation can identify affected artifacts without rewriting historical records.

## Operations

The controlled operation vocabulary is:

- `ingestion`
- `indexing`
- `retrieval`
- `model_transmission`
- `display`
- `summary`
- `export`
- `retention`
- `training`

An allow decision for one operation never implies permission for another.

## Registration and approval

Registration validates file type/size or URL syntax, computes the original-byte hash, rejects duplicate content, extracts passages, and creates an explicit allow/deny row for every operation. Omitted rights become `deny / RIGHT_UNKNOWN`.

A different user must approve the version. Approval requires:

- a non-empty content hash;
- at least one indexed passage; and
- current explicit allow decisions for retrieval, model transmission, and display.

## Lifecycle

- `supersedes` marks the earlier version `SUPERSEDED` and links it to its replacement.
- revocation marks a version `WITHDRAWN` with timestamp and reason.
- the expiry lifecycle action marks approved/active versions past `effective_to` as `EXPIRED`.
- impact lookup returns preserved bundle and answer usage records for a version.

## Security boundary

Tenant-private sources are restricted to their tenant. Globally shared sources remain readable across tenants, but rights and provenance writes require the owning tenant context. PostgreSQL RLS backs these application checks.

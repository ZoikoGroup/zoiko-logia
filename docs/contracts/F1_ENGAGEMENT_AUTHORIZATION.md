# F1 engagement authorization

F1 introduces tenant-owned engagements, memberships, and versioned
operation grants. Authorization is deny-by-default and evaluated server-side.

## Operations

- `ask`
- `document.read`
- `document.write`
- `model.transmit`
- `audit.replay`
- `export`

An explicit deny overrides an allow. Expired grants, inactive engagements,
revoked memberships, cross-tenant memberships, and missing operation grants
all deny access with stable reason codes.

## Request enforcement

Professional Ask Kriton workflows require an engagement. Before idempotency
lookup or provider work, orchestration verifies `ask`, `model.transmit`, and,
when attachments are present, `document.read`. Idempotency keys are scoped by
engagement so a same-tenant key cannot return another engagement's response.

Documents are stamped with `engagement_id`. Personal legacy documents retain a
null engagement and remain uploader-only. Engagement documents are visible only
to active engagement members with the required service-layer grant; PostgreSQL
RLS independently checks active membership.

Audit replay rechecks the current `audit.replay` grant. Revocation therefore
blocks later replay access without rewriting the historical audit record.

## Administration

- `GET /api/v1/engagements` lists engagements where the caller has `ask`.
- `POST /api/v1/engagements` creates a tenant engagement (tenant admin).
- `POST /api/v1/engagements/{id}/members` adds a member and explicit grants.
- `DELETE /api/v1/engagements/{id}/members/{user_id}` revokes membership.

Schema changes are owned by Alembic revision `l1f2g3h4i5j6`.

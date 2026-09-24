"""Fine-grained permission registry (Section 2).

Every gateable operation gets one dotted permission string here. The
ROLE_PERMISSIONS table maps the product's literal role names (Admin is set at
provision time, the six role-table roles come from scripts/seed_dev_user.py) to
the permissions they carry. Roles not listed — and new permissions not assigned
to a role — deny by default: a role gains a capability only by being named in
this table.

This is the single source of truth require_permission() checks against, and the
test suite asserts the matrix exactly, so any intended change to who-can-do-what
lands here (and in its test), not scattered across router decorators.
"""

from app.domains.identity.models import User

# ── Permission vocabulary ────────────────────────────────────────────────────
# Naming mirrors the operation vocabulary already in identity/authorization.py
# (document.read, model.transmit, ...) so an operation-level F1 grant and a
# module-level role permission read as one language.

SOURCE_READ = "source.read"          # list sources, expiring, jurisdiction summary
SOURCE_MANAGE = "source.manage"      # create source, approve source version (maker-checker)
SUPPORT_READ = "support.read"        # list tickets, list/get incidents + stats
SUPPORT_MANAGE = "support.manage"    # create/update tickets, incident action + close
MODEL_MANAGE = "model.manage"        # model & prompt registry: list, approve, test-run
AUDIT_CORRECT = "audit.correct"      # issue compensating events (ledger corrections)

ALL_PERMISSIONS = frozenset({
    SOURCE_READ,
    SOURCE_MANAGE,
    SUPPORT_READ,
    SUPPORT_MANAGE,
    MODEL_MANAGE,
    AUDIT_CORRECT,
})

# ── Role → permission matrix (approved product mapping) ─────────────────────
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    # Tenant admin — the role /auth/provision assigns the first signer. Carries
    # everything so an existing Admin behaves exactly as it did before this
    # registry existed (Admin was previously the only role with any access).
    "Admin": ALL_PERMISSIONS,
    # "Full read/write across all modules" (seed description).
    "Governance Ops Lead": frozenset({
        SOURCE_READ, SOURCE_MANAGE,
        SUPPORT_READ, SUPPORT_MANAGE,
        MODEL_MANAGE, AUDIT_CORRECT,
    }),
    # "Source licensing" (seed description).
    "Source Admin": frozenset({SOURCE_READ, SOURCE_MANAGE}),
    # Ontology & syllabus — no registry-gated endpoint exists yet.
    "Syllabus Admin": frozenset(),
    # "Jurisdiction rollout" — needs the jurisdiction/source readiness views.
    "Jurisdiction Lead": frozenset({SOURCE_READ}),
    # "Risk policy, Evaluation gates, Model & prompt registry".
    "Risk Admin": frozenset({MODEL_MANAGE}),
    # "Read-only access for audit purposes" — reads, never writes.
    "System Auditor": frozenset({SOURCE_READ, SUPPORT_READ}),
}


def permissions_for_role(role: str) -> frozenset[str]:
    """Permissions a role carries. Unknown roles get none — deny by default."""
    return ROLE_PERMISSIONS.get(role, frozenset())


def user_has_permission(user: User, permission: str) -> bool:
    return permission in permissions_for_role(user.role)
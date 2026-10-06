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
SAFETY_READ = "safety.read"
SAFETY_MANAGE = "safety.manage"
REVIEW_READ = "review.read"          # list Ask Kriton review cases (escalations, user-reported answers)
REVIEW_RESOLVE = "review.resolve"    # approve / correct / reject a review case; corrections become gold cases
# Evaluation datasets, thresholds, runs and release promotion. Previously gated
# by the review permissions, so granting a reviewer the review queue would also
# have let them promote a release.
EVALUATION_READ = "evaluation.read"
EVALUATION_MANAGE = "evaluation.manage"

ALL_PERMISSIONS = frozenset({
    SOURCE_READ,
    SOURCE_MANAGE,
    SUPPORT_READ,
    SUPPORT_MANAGE,
    MODEL_MANAGE,
    AUDIT_CORRECT,
    SAFETY_READ, SAFETY_MANAGE,
    REVIEW_READ, REVIEW_RESOLVE,
    EVALUATION_READ, EVALUATION_MANAGE,
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
        SAFETY_READ, SAFETY_MANAGE,
        REVIEW_READ, REVIEW_RESOLVE,
        EVALUATION_READ, EVALUATION_MANAGE,
    }),
    # "Source licensing" (seed description).
    "Source Admin": frozenset({SOURCE_READ, SOURCE_MANAGE}),
    # Ontology & syllabus — no registry-gated endpoint exists yet.
    "Syllabus Admin": frozenset(),
    # "Jurisdiction rollout" — needs the jurisdiction/source readiness views.
    "Jurisdiction Lead": frozenset({SOURCE_READ}),
    # "Risk policy, Evaluation gates, Model & prompt registry".
    # Review queue: provisional assignment — confirm who the reviewers are.
    "Risk Admin": frozenset({
        MODEL_MANAGE, SAFETY_READ, SAFETY_MANAGE, REVIEW_READ, REVIEW_RESOLVE,
        EVALUATION_READ, EVALUATION_MANAGE,
    }),
    # Subject-matter reviewer: works the review queue only — reads cases and
    # their evidence, and approves/corrects/rejects them (an approval or
    # correction becomes a gold evaluation case). Deliberately nothing else:
    # no source, model, safety or audit-ledger permissions.
    "SME Reviewer": frozenset({REVIEW_READ, REVIEW_RESOLVE}),
    # "Read-only access for audit purposes" — reads, never writes.
    "System Auditor": frozenset({SOURCE_READ, SUPPORT_READ, SAFETY_READ, REVIEW_READ, EVALUATION_READ}),
}


def permissions_for_role(role: str) -> frozenset[str]:
    """Permissions a role carries. Unknown roles get none — deny by default."""
    return ROLE_PERMISSIONS.get(role, frozenset())


def user_has_permission(user: User, permission: str) -> bool:
    return permission in permissions_for_role(user.role)

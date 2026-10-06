"""Repair databases stamped with an earlier p5i6j7k8l9m0, and scope legacy gold cases.

An earlier revision of p5i6j7k8l9m0 was applied before the migration gained
query_answer_records, the tenant/category columns, its indexes and its RLS
policies. Alembic will not re-run a revision it has stamped, so those databases
stayed incomplete and failed the startup security check. p5's upgrade is
idempotent (every step checks what exists), so it is simply run again here.

Gold cases created before tenant scoping sit in the unscoped
"kriton-reviewed-gold" dataset, which blocks release. Each is moved to its
tenant's dataset only when exactly one resolved review case for the same
question identifies that tenant; anything ambiguous stays put and keeps
blocking release until a person assigns it.

Revision ID: q6j7k8l9m0n1
Revises: p5i6j7k8l9m0
"""
import importlib.util
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "q6j7k8l9m0n1"
down_revision = "p5i6j7k8l9m0"
branch_labels = None
depends_on = None

_LEGACY_GOLD = "kriton-reviewed-gold"


def _p5_upgrade():
    path = Path(__file__).with_name("p5i6j7k8l9m0_governed_answer_release.py")
    spec = importlib.util.spec_from_file_location("p5_governed_answer_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.upgrade()


def upgrade():
    _p5_upgrade()
    bind = op.get_bind()
    legacy = bind.execute(sa.text(
        "SELECT id, query_text FROM benchmark_cases WHERE dataset_id = :legacy"
    ), {"legacy": _LEGACY_GOLD}).all()
    for case_id, query_text in legacy:
        tenants = {row[0] for row in bind.execute(sa.text(
            "SELECT DISTINCT tenant_id FROM review_cases "
            "WHERE query_text = :query AND status = 'resolved' "
            "AND reviewer_decision IN ('approved', 'corrected')"
        ), {"query": query_text})}
        if len(tenants) != 1:
            continue
        tenant_id = tenants.pop()
        dataset_id = f"{_LEGACY_GOLD}:{tenant_id}"
        if not bind.execute(sa.text("SELECT 1 FROM evaluation_datasets WHERE id = :id"), {"id": dataset_id}).first():
            bind.execute(sa.text(
                "INSERT INTO evaluation_datasets (id, version, status, domain, tenant_id) "
                "VALUES (:id, '1', 'ACTIVE', 'ask_kriton', :tenant)"
            ), {"id": dataset_id, "tenant": tenant_id})
        bind.execute(sa.text(
            "UPDATE benchmark_cases SET dataset_id = :dataset, tenant_id = :tenant WHERE id = :id"
        ), {"dataset": dataset_id, "tenant": tenant_id, "id": case_id})
    if legacy and not bind.execute(sa.text(
        "SELECT 1 FROM benchmark_cases WHERE dataset_id = :legacy"
    ), {"legacy": _LEGACY_GOLD}).first():
        bind.execute(sa.text("DELETE FROM evaluation_datasets WHERE id = :legacy"), {"legacy": _LEGACY_GOLD})


def downgrade():
    # Reviewed gold cases are kept; see p5i6j7k8l9m0.downgrade.
    pass

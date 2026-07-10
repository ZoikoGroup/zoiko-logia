from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Import hub: every domain's models.py must be imported here so Base.metadata
# (and, later, Alembic autogenerate) sees all tables.
from app.domains.identity import models as identity_models  # noqa: E402,F401
from app.domains.support_incident import models as support_incident_models  # noqa: E402,F401
from app.domains.learning_cpd import models as learning_cpd_models  # noqa: E402,F401
from app.domains.source_library import models as source_library_models  # noqa: E402,F401
from app.domains.model_gateway import models as model_gateway_models  # noqa: E402,F401
from app.domains.risk_safety import models as risk_safety_models  # noqa: E402,F401
from app.domains.evaluation import models as evaluation_models  # noqa: E402,F401
from app.domains.audit_ledger import models as audit_ledger_models  # noqa: E402,F401
from app.orchestration import models as orchestration_models  # noqa: E402,F401


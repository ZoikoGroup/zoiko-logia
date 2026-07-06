from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Import hub: every domain's models.py must be imported here so Base.metadata
# (and, later, Alembic autogenerate) sees all tables.
from app.domains.identity import models as identity_models  # noqa: E402,F401

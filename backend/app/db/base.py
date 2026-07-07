# Declarative base for all SQLAlchemy ORM models.
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all database models across every domain."""
    pass

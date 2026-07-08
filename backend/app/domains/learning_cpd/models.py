import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class SyllabusPathway(Base):
    __tablename__ = "syllabus_pathways"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    body: Mapped[str] = mapped_column(String, nullable=False)
    qualification: Mapped[str] = mapped_column(String, nullable=False)
    module: Mapped[str] = mapped_column(String, nullable=False)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    learning_outcome: Mapped[str] = mapped_column(String, nullable=False)


class TopicMapNode(Base):
    __tablename__ = "topic_map_nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    prerequisites: Mapped[str] = mapped_column(String, nullable=False, default="")
    standards_summary: Mapped[str] = mapped_column(String, nullable=False, default="")

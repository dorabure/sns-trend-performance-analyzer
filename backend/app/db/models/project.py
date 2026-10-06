import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text, UniqueConstraint, true, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, Timestamps


class Project(Timestamps, Base):
    __tablename__ = "projects"
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    data_mode: Mapped[str] = mapped_column(String(16), server_default=text("'DEMO'"))
    __table_args__ = (CheckConstraint("data_mode IN ('DEMO', 'LIVE')", name="data_mode"),)


class ProjectPlatform(CreatedAt, Base):
    __tablename__ = "project_platforms"
    project_platform_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(20))
    __table_args__ = (
        CheckConstraint("platform IN ('X', 'INSTAGRAM')", name="platform"),
        UniqueConstraint("project_id", "platform", name="uq_project_platforms_project_platform"),
    )

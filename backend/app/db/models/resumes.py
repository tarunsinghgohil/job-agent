"""Resume library: documents, immutable versions, evidence, and embeddings."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    JSONColumn,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    Vector,
)

EMBEDDING_DIM = 1536


class Resume(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A named resume line, e.g. 'Frontend React'. Content lives in versions."""

    __tablename__ = "resumes"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tags: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    role_focus: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    industry_focus: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    skill_focus: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String(32))

    versions: Mapped[list["ResumeVersion"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
        order_by="ResumeVersion.version_number.desc()",
        foreign_keys="ResumeVersion.resume_id",
    )


class ResumeVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An immutable snapshot: an uploaded file or a generated tailored draft."""

    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint("resume_id", "version_number", name="uq_resume_version_number"),
    )

    resume_id: Mapped[str] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    label: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    origin: Mapped[str] = mapped_column(String(40), default="upload", nullable=False)

    # Stored file. storage_path is a random name; original_filename is display only.
    storage_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    original_filename: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)

    extracted_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sections: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    extracted_skills: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    parse_error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Populated when this version was generated for a specific job.
    tailored_for_job_id: Mapped[str | None] = mapped_column(String(32), index=True)
    generation_notes: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)

    resume: Mapped[Resume] = relationship(back_populates="versions", foreign_keys=[resume_id])
    chunks: Mapped[list["ResumeChunk"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class ResumeChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Embedded slice of resume text, retrieved as grounding evidence for AI."""

    __tablename__ = "resume_chunks"

    resume_version_id: Mapped[str] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    section: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str] = mapped_column(String(80), default="", nullable=False)

    version: Mapped[ResumeVersion] = relationship(back_populates="chunks")


class ResumeEvidence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Links a concrete claim to the resume text that supports it.

    Generation is only allowed to assert claims that resolve to a row here,
    which is the mechanism behind the 'never invent facts' rule.
    """

    __tablename__ = "resume_evidence"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    resume_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="SET NULL"), index=True
    )
    career_fact_id: Mapped[str | None] = mapped_column(
        ForeignKey("career_facts.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40), default="skill", nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

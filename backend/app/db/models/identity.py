"""User identity, authentication sessions, and the canonical career profile."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONColumn, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped["CareerProfile"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per issued refresh token, so sessions can be listed and revoked."""

    __tablename__ = "user_sessions"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    user: Mapped[User] = relationship(back_populates="sessions")


class CareerProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "career_profiles"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    headline: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    location: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    links: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)

    total_experience_years: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    domains: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    preferred_roles: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    preferred_industries: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)

    notice_period: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    current_ctc_lpa: Mapped[float | None] = mapped_column(Float)
    expected_ctc_lpa: Mapped[float | None] = mapped_column(Float)
    work_authorization: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    work_authorization_note: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    open_to_relocation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="profile")
    experiences: Mapped[list["Experience"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="Experience.sort_order"
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="Project.sort_order"
    )
    education: Mapped[list["Education"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="Education.sort_order"
    )
    profile_skills: Mapped[list["ProfileSkill"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    facts: Mapped[list["CareerFact"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class Skill(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Canonical skill vocabulary, shared by profile skills and job skills."""

    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    aliases: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)


class ProfileSkill(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "profile_skills"
    __table_args__ = (UniqueConstraint("profile_id", "skill_id", name="uq_profile_skill"),)

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("career_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False
    )
    years: Mapped[float | None] = mapped_column(Float)
    proficiency: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence_note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    profile: Mapped[CareerProfile] = relationship(back_populates="profile_skills")
    skill: Mapped[Skill] = relationship(lazy="joined")


class Experience(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "experiences"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("career_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    employment_type: Mapped[str] = mapped_column(String(50), default="full_time", nullable=False)
    location: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    highlights: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    tech_stack: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    profile: Mapped[CareerProfile] = relationship(back_populates="experiences")


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "projects"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("career_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    url: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    tech_stack: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    highlights: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    profile: Mapped[CareerProfile] = relationship(back_populates="projects")


class Education(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "education"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("career_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    institution: Mapped[str] = mapped_column(String(200), nullable=False)
    degree: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    field_of_study: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    start_year: Mapped[int | None] = mapped_column(Integer)
    end_year: Mapped[int | None] = mapped_column(Integer)
    grade: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    profile: Mapped[CareerProfile] = relationship(back_populates="education")


class CareerFact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Atomic, citable claims. AI generation may only assert what exists here."""

    __tablename__ = "career_facts"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("career_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), default="summary", nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_ref: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tags: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)

    profile: Mapped[CareerProfile] = relationship(back_populates="facts")

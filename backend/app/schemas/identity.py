"""Auth and career-profile schemas."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel, TimestampedModel


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(ORMModel):
    id: str
    email: str
    full_name: str
    is_owner: bool
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class SessionOut(ORMModel):
    id: str
    user_agent: str
    ip_address: str
    created_at: datetime
    expires_at: datetime


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------
class ExperienceIn(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    employment_type: str = "full_time"
    location: str = ""
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    description: str = ""
    highlights: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    sort_order: int = 0


class ExperienceOut(ExperienceIn, TimestampedModel):
    id: str


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = ""
    description: str = ""
    url: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    sort_order: int = 0


class ProjectOut(ProjectIn, TimestampedModel):
    id: str


class EducationIn(BaseModel):
    institution: str = Field(min_length=1, max_length=200)
    degree: str = ""
    field_of_study: str = ""
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)
    grade: str = ""
    sort_order: int = 0


class EducationOut(EducationIn, TimestampedModel):
    id: str


class ProfileSkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    years: float | None = Field(default=None, ge=0, le=60)
    proficiency: str = ""
    is_primary: bool = False
    evidence_note: str = ""


class ProfileSkillOut(ORMModel):
    id: str
    name: str
    slug: str
    category: str = ""
    years: float | None = None
    proficiency: str = ""
    is_primary: bool = False
    evidence_note: str = ""


class CareerFactIn(BaseModel):
    kind: str = "summary"
    statement: str = Field(min_length=1)
    detail: str = ""
    source_ref: str = ""
    confidence: float = Field(default=1.0, ge=0, le=1)
    is_verified: bool = True
    tags: list[str] = Field(default_factory=list)


class CareerFactOut(CareerFactIn, TimestampedModel):
    id: str


class ProfileIn(BaseModel):
    full_name: str = ""
    headline: str = ""
    summary: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: dict[str, str] = Field(default_factory=dict)
    total_experience_years: float = Field(default=0.0, ge=0, le=70)
    domains: list[str] = Field(default_factory=list)
    preferred_roles: list[str] = Field(default_factory=list)
    preferred_industries: list[str] = Field(default_factory=list)
    notice_period: str = ""
    current_ctc_lpa: float | None = Field(default=None, ge=0)
    expected_ctc_lpa: float | None = Field(default=None, ge=0)
    work_authorization: bool = True
    work_authorization_note: str = ""
    open_to_relocation: bool = False


class ProfileOut(ProfileIn, TimestampedModel):
    id: str
    experiences: list[ExperienceOut] = Field(default_factory=list)
    projects: list[ProjectOut] = Field(default_factory=list)
    education: list[EducationOut] = Field(default_factory=list)
    skills: list[ProfileSkillOut] = Field(default_factory=list)
    facts: list[CareerFactOut] = Field(default_factory=list)

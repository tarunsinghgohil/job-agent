"""Resume library schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, TimestampedModel


class ResumeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    role_focus: list[str] = Field(default_factory=list)
    industry_focus: list[str] = Field(default_factory=list)
    skill_focus: list[str] = Field(default_factory=list)
    is_active: bool = True


class ResumeVersionOut(TimestampedModel):
    id: str
    version_number: int
    label: str
    origin: str
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    parse_status: str
    parse_error: str
    extracted_skills: list[str] = Field(default_factory=list)
    tailored_for_job_id: str | None = None
    generation_notes: dict[str, Any] = Field(default_factory=dict)
    chunk_count: int = 0


class ResumeVersionDetailOut(ResumeVersionOut):
    extracted_text: str = ""
    sections: dict[str, str] = Field(default_factory=dict)


class ResumeOut(TimestampedModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    role_focus: list[str] = Field(default_factory=list)
    industry_focus: list[str] = Field(default_factory=list)
    skill_focus: list[str] = Field(default_factory=list)
    is_active: bool
    is_default: bool
    current_version_id: str | None = None
    version_count: int = 0
    versions: list[ResumeVersionOut] = Field(default_factory=list)


class TailorRequest(BaseModel):
    job_id: str
    base_version_id: str | None = None
    save_as_version: bool = False


class TailorResult(BaseModel):
    job_id: str
    resume_id: str
    summary: str = ""
    highlights: list[str] = Field(default_factory=list)
    skills_order: list[str] = Field(default_factory=list)
    changed_sections: list[dict[str, Any]] = Field(default_factory=list)
    omitted: list[str] = Field(default_factory=list)
    unsupported_requests: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    saved_version_id: str | None = None
    original_text: str = ""

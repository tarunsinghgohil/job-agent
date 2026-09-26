"""Domain enumerations.

Stored as plain strings so that adding a value never requires a database
migration of a native ENUM type.
"""
from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    NEW = "new"
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    QUEUED = "queued"
    APPLIED = "applied"
    ARCHIVED = "archived"


class MatchDecision(StrEnum):
    HIGH_PRIORITY = "HIGH_PRIORITY"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class ApplicationStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    PREPARED = "prepared"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    FAILED = "failed"
    WITHDRAWN = "withdrawn"
    INTERVIEW = "interview"
    OFFER = "offer"
    CLOSED = "closed"


TERMINAL_APPLICATION_STATUSES = frozenset(
    {
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.CLOSED,
    }
)


class AnswerState(StrEnum):
    VERIFIED = "verified"
    INFERRED = "inferred"
    NEEDS_REVIEW = "needs_review"


class RuleOperator(StrEnum):
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    IN = "in"
    NOT_IN = "not_in"
    GTE = "gte"
    LTE = "lte"
    GT = "gt"
    LT = "lt"
    BETWEEN = "between"
    REGEX = "regex"


class RuleField(StrEnum):
    TITLE = "title"
    COMPANY = "company"
    LOCATION = "location"
    DESCRIPTION = "description"
    INDUSTRY = "industry"
    EMPLOYMENT_TYPE = "employment_type"
    SALARY_LPA = "salary_lpa"
    EXPERIENCE_MIN = "experience_min"
    EXPERIENCE_MAX = "experience_max"
    SOURCE = "source"
    REMOTE = "remote"
    SKILLS = "skills"


class SourceAdapterType(StrEnum):
    REMOTIVE = "remotive"
    ADZUNA = "adzuna"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    RSS = "rss"
    MANUAL = "manual"


class SourceHealth(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    DISABLED = "disabled"


class AgentRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NotificationChannelType(StrEnum):
    EMAIL = "email"
    TELEGRAM = "telegram"
    SLACK = "slack"
    WHATSAPP = "whatsapp"


class NotificationEventType(StrEnum):
    HIGH_MATCH_JOB = "high_match_job"
    DAILY_DIGEST = "daily_digest"
    APPLICATION_READY = "application_ready"
    APPLICATION_SUBMITTED = "application_submitted"
    INTEGRATION_FAILED = "integration_failed"
    SCHEDULED_RUN_FAILED = "scheduled_run_failed"
    INTERVIEW_ADDED = "interview_added"
    FOLLOWUP_DUE = "followup_due"
    QUOTA_WARNING = "quota_warning"
    WEEKLY_SUMMARY = "weekly_summary"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class EvidenceKind(StrEnum):
    EXPERIENCE = "experience"
    PROJECT = "project"
    SKILL = "skill"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    SUMMARY = "summary"


class ApplicationChannel(StrEnum):
    MANUAL = "manual"
    EMAIL = "email"
    ATS = "ats"
    LINKEDIN = "linkedin"
    COMPANY_PORTAL = "company_portal"


class AssetType(StrEnum):
    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    PORTFOLIO_NOTE = "portfolio_note"
    PITCH = "pitch"

"""Model package.

Importing this module registers every table on ``Base.metadata``. Alembic and
``create_all`` both depend on that, so always import from here rather than from
the individual modules when you need the full metadata.
"""
from app.db.base import Base
from app.db.models.applications import (
    AnswerBankEntry,
    Application,
    ApplicationAnswer,
    ApplicationAsset,
    ApplicationStatusHistory,
    FollowUp,
    Interview,
    Offer,
    Recruiter,
)
from app.db.models.automation import (
    AgentDefinition,
    AgentRun,
    AgentRunStep,
    AICache,
    AIUsage,
    Schedule,
)
from app.db.models.identity import (
    CareerFact,
    CareerProfile,
    Education,
    Experience,
    ProfileSkill,
    Project,
    Skill,
    User,
    UserSession,
)
from app.db.models.hunt import HuntConfig, HuntResult
from app.db.models.jobs import Job, JobEvent, JobMatch, JobSkill, JobSource
from app.db.models.ops import (
    AuditLog,
    EncryptedSecret,
    NotificationChannel,
    NotificationEvent,
    NotificationPreference,
    SystemSetting,
)
from app.db.models.preferences import JobPreference, MatchRule, SavedSearch
from app.db.models.resumes import Resume, ResumeChunk, ResumeEvidence, ResumeVersion

__all__ = [
    "Base",
    # identity
    "User",
    "UserSession",
    "CareerProfile",
    "Experience",
    "Project",
    "Education",
    "Skill",
    "ProfileSkill",
    "CareerFact",
    # preferences
    "JobPreference",
    "MatchRule",
    "SavedSearch",
    # resumes
    "Resume",
    "ResumeVersion",
    "ResumeChunk",
    "ResumeEvidence",
    # jobs
    "JobSource",
    "Job",
    "JobSkill",
    "JobMatch",
    "JobEvent",
    # job hunt
    "HuntConfig",
    "HuntResult",
    # applications
    "Application",
    "ApplicationStatusHistory",
    "ApplicationAnswer",
    "ApplicationAsset",
    "FollowUp",
    "Recruiter",
    "Interview",
    "Offer",
    "AnswerBankEntry",
    # automation
    "AgentDefinition",
    "AgentRun",
    "AgentRunStep",
    "Schedule",
    "AIUsage",
    "AICache",
    # ops
    "NotificationChannel",
    "NotificationPreference",
    "NotificationEvent",
    "EncryptedSecret",
    "AuditLog",
    "SystemSetting",
]

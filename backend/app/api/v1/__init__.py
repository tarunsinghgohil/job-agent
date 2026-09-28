"""Version 1 API router aggregation."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routers import (
    answers,
    applications,
    auth,
    automation,
    hunt,
    integrations,
    jobs,
    notifications,
    policy,
    profile,
    resumes,
    sources,
    suggest,
    system,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(profile.router)
api_router.include_router(policy.router)
api_router.include_router(sources.router)
api_router.include_router(jobs.router)
api_router.include_router(hunt.router)
api_router.include_router(resumes.router)
api_router.include_router(answers.router)
api_router.include_router(applications.router)
api_router.include_router(notifications.router)
api_router.include_router(integrations.router)
api_router.include_router(automation.router)
api_router.include_router(suggest.router)
api_router.include_router(system.router)

__all__ = ["api_router"]

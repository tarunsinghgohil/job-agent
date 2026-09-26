"""Command-line operations.

Usage:
    python -m app.cli seed            create the owner account and starter data
    python -m app.cli create-user     add a user interactively
    python -m app.cli reset-db        drop and recreate every table (destructive)
    python -m app.cli backup          write a JSON backup of all data
    python -m app.cli secret-key      print a fresh APP_SECRET_KEY

The seed writes the user's starting job policy into the DATABASE, where it is
editable from the dashboard. It is a starting point, not configuration: the
values are never read from code at runtime.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.security import generate_secret_key
from app.db.models import Base
from app.db.models.applications import AnswerBankEntry
from app.db.models.enums import (
    NotificationChannelType,
    NotificationEventType,
    RuleField,
    RuleOperator,
    SourceAdapterType,
)
from app.db.models.identity import CareerFact, CareerProfile, ProfileSkill, Skill, User
from app.db.models.jobs import JobSource
from app.db.models.ops import NotificationPreference
from app.db.models.preferences import JobPreference, MatchRule
from app.db.models.resumes import Resume
from app.db.session import engine, session_scope
from app.services import answers as answer_service
from app.services.auth import create_user, get_user_by_email
from app.services.normalize import slugify


# --------------------------------------------------------------------------
# Starter data
# --------------------------------------------------------------------------
STARTER_PROFILE: dict[str, Any] = {
    "full_name": "Tarun Singh Gohil",
    "headline": "Frontend Developer | React.js | UI/UX",
    "location": "Jaipur, Rajasthan, India",
    "email": "tarungohil80@gmail.com",
    "links": {
        "linkedin": "https://linkedin.com/in/tarun-singh-gohil",
        "github": "https://github.com/tarunsinghgohil",
    },
    "total_experience_years": 6.0,
    "notice_period": "Immediate / 0 days",
    "current_ctc_lpa": 14.0,
    "expected_ctc_lpa": 16.0,
    "work_authorization": True,
    "open_to_relocation": True,
    "domains": ["Software", "IT", "Healthcare", "Enterprise SaaS"],
    "preferred_roles": [
        "Frontend Developer", "React JS Developer", "Web Developer",
        "UI Developer", "Software Developer",
    ],
    "preferred_industries": ["software", "it", "healthcare"],
}

STARTER_SKILLS: list[tuple[str, float | None, bool]] = [
    ("React", 4.5, True),
    ("TypeScript", 4.0, True),
    ("JavaScript", 6.0, True),
    ("Redux Toolkit", 4.0, False),
    ("Next.js", 3.0, False),
    ("HTML", 6.0, False),
    ("CSS", 6.0, False),
    ("Tailwind CSS", 3.0, False),
    ("REST APIs", 5.0, False),
    ("Node.js", 3.0, False),
    ("Jest", 3.0, False),
    ("Git", 6.0, False),
]

STARTER_PREFERENCES: dict[str, Any] = {
    "target_roles": [
        "Frontend Developer", "React JS Developer", "Web Developer", "UI Developer",
        "Software Developer", "Senior Frontend Engineer", "Frontend Engineer",
    ],
    "preferred_locations": ["Jaipur", "Remote", "Indore"],
    "remote_ok": True,
    "remote_only": False,
    "min_salary_lpa": 14.0,
    "target_salary_lpa": 16.0,
    "currency": "INR",
    "experience_min_years": 3.0,
    "experience_max_years": 6.0,
    "notice_period_days": 0,
    "employment_types": ["full_time"],
    "company_types": ["product_based"],
    "industries": ["software", "it", "healthcare"],
    "must_have_keywords": ["React"],
    "nice_to_have_keywords": [
        "TypeScript", "Redux", "Next.js", "REST APIs", "Tailwind CSS",
        "Testing", "AWS", "Docker", "GraphQL",
    ],
    "excluded_keywords": [],
    "review_threshold": 70,
    "high_priority_threshold": 85,
    "daily_application_cap": 8,
    "approval_required": True,
    "auto_submit_enabled": False,
    "discovery_schedule_cron": "0 8 * * *",
    "timezone": "Asia/Kolkata",
}

STARTER_ANSWERS: list[dict[str, str]] = [
    {"question": "How many years of React experience do you have?", "answer": "4.5 years", "category": "experience"},
    {"question": "How many years of TypeScript experience do you have?", "answer": "4 years", "category": "experience"},
    {"question": "What is your current CTC?", "answer": "14 LPA", "category": "compensation"},
    {"question": "What is your expected CTC?", "answer": "16+ LPA", "category": "compensation"},
    {"question": "What is your notice period?", "answer": "Immediate joiner, 0 days.", "category": "availability"},
    {"question": "Why are you looking for a change?", "answer": "My previous company is closing, so I am looking for a role where I can contribute long term.", "category": "motivation"},
    {"question": "Are you willing to relocate?", "answer": "Yes", "category": "logistics"},
    {"question": "Do you have work authorization?", "answer": "Yes", "category": "logistics"},
]

STARTER_RULES: list[dict[str, Any]] = [
    {
        "name": "React is required",
        "field": RuleField.DESCRIPTION,
        "operator": RuleOperator.CONTAINS,
        "value": {"value": ["react"]},
        "is_hard": True,
        "weight": 0.0,
        "priority": 10,
        "explanation": "React is a must-have for every target role.",
    },
    {
        "name": "Full-time only",
        "field": RuleField.EMPLOYMENT_TYPE,
        "operator": RuleOperator.IN,
        "value": {"value": ["full_time"]},
        "is_hard": True,
        "weight": 0.0,
        "priority": 20,
        "explanation": "Only full-time roles are in scope.",
    },
    {
        "name": "Bonus for a testing culture",
        "field": RuleField.DESCRIPTION,
        "operator": RuleOperator.CONTAINS,
        "value": {"value": ["jest", "cypress", "playwright", "testing library"]},
        "is_hard": False,
        "weight": 3.0,
        "priority": 100,
        "explanation": "Teams that test are a better fit.",
    },
]

STARTER_SOURCES: list[dict[str, Any]] = [
    {
        "name": "Remotive",
        "adapter_type": SourceAdapterType.REMOTIVE,
        "config": {"search": "react"},
        "enabled": True,
        "priority": 10,
        "schedule_cron": "0 8 * * *",
    },
    {
        "name": "Manual entry",
        "adapter_type": SourceAdapterType.MANUAL,
        "config": {},
        "enabled": True,
        "priority": 900,
    },
]


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_seed(args: argparse.Namespace) -> int:
    email = args.email or settings.bootstrap_email
    password = args.password or settings.bootstrap_password

    if not email:
        print("No email given. Pass --email or set BOOTSTRAP_EMAIL in .env.", file=sys.stderr)
        return 2
    if not password:
        password = getpass.getpass("Password for the owner account: ")
    if not password:
        print("A password is required.", file=sys.stderr)
        return 2

    with session_scope() as db:
        user = get_user_by_email(db, email)
        if user is None:
            user = create_user(
                db, email, password,
                full_name=STARTER_PROFILE["full_name"], is_owner=True,
            )
            print(f"Created owner account: {email}")
        else:
            print(f"Owner account already exists: {email}")

        created = _seed_user_data(db, user)
        for label, count in created.items():
            print(f"  {label}: {count}")

    print("\nSeed complete. Start the API and sign in with that account.")
    return 0


def _seed_user_data(db: Any, user: User) -> dict[str, int]:
    """Idempotent: re-running never duplicates rows."""
    counts: dict[str, int] = {}

    profile = db.execute(
        select(CareerProfile).where(CareerProfile.user_id == user.id)
    ).scalar_one_or_none()
    if profile is None:
        profile = CareerProfile(user_id=user.id, **STARTER_PROFILE)
        db.add(profile)
        db.flush()
        counts["profile"] = 1
    else:
        counts["profile"] = 0

    skill_added = 0
    for name, years, primary in STARTER_SKILLS:
        slug = slugify(name)
        skill = db.execute(select(Skill).where(Skill.slug == slug)).scalar_one_or_none()
        if skill is None:
            skill = Skill(name=name, slug=slug)
            db.add(skill)
            db.flush()
        exists = db.execute(
            select(ProfileSkill).where(
                ProfileSkill.profile_id == profile.id, ProfileSkill.skill_id == skill.id
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(
                ProfileSkill(
                    profile_id=profile.id, skill_id=skill.id,
                    years=years, is_primary=primary,
                )
            )
            skill_added += 1
    counts["skills"] = skill_added

    fact_added = 0
    for name, years, _ in STARTER_SKILLS:
        if years is None:
            continue
        statement = f"{years} years of hands-on {name} experience."
        exists = db.execute(
            select(CareerFact).where(
                CareerFact.profile_id == profile.id, CareerFact.statement == statement
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(
                CareerFact(
                    profile_id=profile.id, kind="skill", statement=statement,
                    source_ref="seed", is_verified=True, tags=[name],
                )
            )
            fact_added += 1
    counts["career_facts"] = fact_added

    prefs = db.execute(
        select(JobPreference).where(JobPreference.user_id == user.id)
    ).scalar_one_or_none()
    if prefs is None:
        prefs = JobPreference(
            user_id=user.id,
            scoring_weights=JobPreference.default_weights(),
            **STARTER_PREFERENCES,
        )
        db.add(prefs)
        counts["preferences"] = 1
    else:
        counts["preferences"] = 0

    rule_added = 0
    for spec in STARTER_RULES:
        exists = db.execute(
            select(MatchRule).where(
                MatchRule.user_id == user.id, MatchRule.name == spec["name"]
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(MatchRule(user_id=user.id, **{
                **spec,
                "field": str(spec["field"]),
                "operator": str(spec["operator"]),
            }))
            rule_added += 1
    counts["rules"] = rule_added

    answer_added = 0
    for spec in STARTER_ANSWERS:
        key = answer_service.normalize_question(spec["question"])
        exists = db.execute(
            select(AnswerBankEntry).where(
                AnswerBankEntry.user_id == user.id, AnswerBankEntry.normalized_key == key
            )
        ).scalar_one_or_none()
        if exists is None:
            answer_service.upsert_entry(
                db, user.id, spec["question"], spec["answer"],
                category=spec["category"], source="seed", state="verified",
            )
            answer_added += 1
    counts["answers"] = answer_added

    source_added = 0
    for spec in STARTER_SOURCES:
        exists = db.execute(
            select(JobSource).where(
                JobSource.user_id == user.id, JobSource.name == spec["name"]
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(JobSource(user_id=user.id, **{
                **spec, "adapter_type": str(spec["adapter_type"]),
            }))
            source_added += 1
    counts["job_sources"] = source_added

    resume = db.execute(
        select(Resume).where(Resume.user_id == user.id)
    ).scalars().first()
    if resume is None:
        db.add(
            Resume(
                user_id=user.id,
                name="Master — Frontend React",
                description="Upload your PDF or DOCX to this resume line.",
                role_focus=["Frontend Developer", "React JS Developer", "UI Developer"],
                industry_focus=["software", "it", "healthcare"],
                skill_focus=["React", "TypeScript", "Redux Toolkit", "Next.js"],
                is_default=True,
                is_active=True,
            )
        )
        counts["resumes"] = 1
    else:
        counts["resumes"] = 0

    notif = db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user.id)
    ).scalar_one_or_none()
    if notif is None:
        db.add(
            NotificationPreference(
                user_id=user.id,
                event_routing={
                    str(NotificationEventType.HIGH_MATCH_JOB): [str(NotificationChannelType.EMAIL)],
                    str(NotificationEventType.DAILY_DIGEST): [str(NotificationChannelType.EMAIL)],
                    str(NotificationEventType.FOLLOWUP_DUE): [str(NotificationChannelType.EMAIL)],
                },
                quiet_hours_start="22:00",
                quiet_hours_end="07:00",
                timezone=STARTER_PREFERENCES["timezone"],
            )
        )
        counts["notification_preferences"] = 1
    else:
        counts["notification_preferences"] = 0

    from app.agents.registry import ensure_agent_definitions

    counts["agents"] = len(ensure_agent_definitions(db, user.id))
    return counts


def cmd_create_user(args: argparse.Namespace) -> int:
    email = args.email or input("Email: ").strip()
    password = args.password or getpass.getpass("Password: ")
    with session_scope() as db:
        user = create_user(db, email, password, full_name=args.name or "", is_owner=args.owner)
        print(f"Created user {user.email} (owner={user.is_owner}).")
    return 0


def cmd_reset_db(args: argparse.Namespace) -> int:
    if not args.yes:
        confirm = input(
            f"This DROPS every table in {settings.resolved_database_url()}.\n"
            "Type 'reset' to continue: "
        )
        if confirm.strip().lower() != "reset":
            print("Aborted.")
            return 1

    Base.metadata.drop_all(engine)
    print("All tables dropped.")
    print("Now run: python -m alembic upgrade head")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    target = Path(args.output or "backup.json")
    payload: dict[str, Any] = {"tables": {}}

    with session_scope() as db:
        for table in Base.metadata.sorted_tables:
            rows = db.execute(table.select()).mappings().all()
            payload["tables"][table.name] = [
                {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
                for row in rows
            ]

    target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    total = sum(len(v) for v in payload["tables"].values())
    print(f"Wrote {total} rows across {len(payload['tables'])} tables to {target}.")
    return 0


def cmd_secret_key(_args: argparse.Namespace) -> int:
    print(generate_secret_key())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="Create the owner account and starter data")
    seed.add_argument("--email")
    seed.add_argument("--password")
    seed.set_defaults(func=cmd_seed)

    create = sub.add_parser("create-user", help="Create an additional user")
    create.add_argument("--email")
    create.add_argument("--password")
    create.add_argument("--name", default="")
    create.add_argument("--owner", action="store_true")
    create.set_defaults(func=cmd_create_user)

    reset = sub.add_parser("reset-db", help="Drop every table (destructive)")
    reset.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    reset.set_defaults(func=cmd_reset_db)

    backup = sub.add_parser("backup", help="Write a JSON backup of all data")
    backup.add_argument("--output", "-o")
    backup.set_defaults(func=cmd_backup)

    key = sub.add_parser("secret-key", help="Print a fresh APP_SECRET_KEY")
    key.set_defaults(func=cmd_secret_key)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

"""Seed values for a new HuntConfig and helpers to load and validate one.

The seed mirrors the 3x Job Hunt brief (Remote India -> Jaipur -> Hybrid
Jaipur -> Other India, 5.5+ years, React-centred roles). Nothing here is
enforced: every value is copied into the user's row and edited from the UI.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.hunt import HuntConfig

WORK_MODES = ("remote", "hybrid", "onsite")
TIER_KINDS = ("apply_first", "review")
SENIORITY_LEVELS = ("intern", "junior", "mid", "senior", "lead")
SEMANTIC_MODES = ("off", "local", "embeddings")

HUNT_AGENT_KEY = "job_hunt"
DEFAULT_SCHEDULE_CRON = "0 2,8,14,20 * * *"  # every 6 hours, IST-friendly slots

DEFAULT_TARGET_ROLES = [
    "Senior React Developer",
    "Frontend Developer",
    "Frontend Engineer",
    "React Developer",
    "UI Engineer",
    "JavaScript Developer",
    "TypeScript Developer",
    "Next.js Developer",
    "MERN Stack Developer",
    "Full Stack Developer",
]

DEFAULT_SKILLS = [
    "React.js",
    "JavaScript",
    "TypeScript",
    "Next.js",
    "Redux Toolkit",
    "Zustand",
    "Tailwind CSS",
    "Node.js",
    "Express.js",
    "MongoDB",
    "Python",
    "Django",
    "REST APIs",
    "GraphQL",
    "PostgreSQL",
    "MySQL",
    "Docker",
    "AWS",
    "AI/LLM",
    "RAG",
]

# Title words that put a role in the candidate's job family even when it does
# not literally match a target role ("Software Engineer - Frontend").
DEFAULT_ROLE_KEYWORDS = [
    "react",
    "frontend",
    "front end",
    "ui",
    "javascript",
    "typescript",
    "next.js",
    "mern",
    "full stack",
    "fullstack",
    "web developer",
    "web engineer",
]

DEFAULT_EXCLUDED_SENIORITY = ["intern", "junior"]

DEFAULT_LOCATION_TIERS: list[dict[str, Any]] = [
    {
        "name": "Remote India",
        "group": "Remote",
        "work_modes": ["remote"],
        "places": ["India"],
        "kind": "apply_first",
    },
    {
        "name": "Jaipur",
        "group": "Jaipur",
        "work_modes": ["onsite"],
        "places": ["Jaipur"],
        "kind": "apply_first",
    },
    {
        "name": "Hybrid Jaipur",
        "group": "Jaipur",
        "work_modes": ["hybrid"],
        "places": ["Jaipur"],
        "kind": "apply_first",
    },
    {
        "name": "Other India",
        "group": "Other India",
        "work_modes": ["onsite", "hybrid"],
        "places": ["India"],
        "kind": "review",
    },
]

# Places that mean "in India". Used to recognise "Bengaluru, Karnataka" as an
# Indian location and "Remote - Pune" as remote-within-India.
DEFAULT_COUNTRY_PLACES = [
    "India", "Bengaluru", "Bangalore", "Hyderabad", "Pune", "Mumbai", "Navi Mumbai",
    "Thane", "Delhi", "New Delhi", "Delhi NCR", "NCR", "Gurugram", "Gurgaon", "Noida",
    "Greater Noida", "Faridabad", "Chennai", "Kolkata", "Ahmedabad", "Gandhinagar",
    "Jaipur", "Jodhpur", "Udaipur", "Indore", "Bhopal", "Chandigarh", "Mohali",
    "Panchkula", "Kochi", "Cochin", "Thiruvananthapuram", "Trivandrum", "Coimbatore",
    "Madurai", "Nagpur", "Nashik", "Lucknow", "Kanpur", "Bhubaneswar", "Vadodara",
    "Surat", "Rajkot", "Mysuru", "Mysore", "Mangaluru", "Visakhapatnam", "Vijayawada",
    "Dehradun", "Guwahati", "Patna", "Ranchi", "Raipur", "Goa",
    "Rajasthan", "Karnataka", "Maharashtra", "Telangana", "Tamil Nadu", "Kerala",
    "Uttar Pradesh", "Haryana", "Gujarat", "West Bengal", "Madhya Pradesh", "Punjab",
    "Andhra Pradesh", "Odisha",
]


def default_weights() -> dict[str, float]:
    """Relative weights; the score is normalised, so they need not sum to 100."""
    return {
        "location": 20.0,
        "role": 20.0,
        "skills": 25.0,
        "experience": 15.0,
        "freshness": 10.0,
        "semantic": 5.0,
        "apply_link": 5.0,
    }


def seed_values() -> dict[str, Any]:
    return {
        "experience_years": 5.5,
        "target_roles": list(DEFAULT_TARGET_ROLES),
        "skills": list(DEFAULT_SKILLS),
        "role_keywords": list(DEFAULT_ROLE_KEYWORDS),
        "excluded_seniority": list(DEFAULT_EXCLUDED_SENIORITY),
        "location_tiers": [dict(t) for t in DEFAULT_LOCATION_TIERS],
        "country": "India",
        "country_places": list(DEFAULT_COUNTRY_PLACES),
        "accept_worldwide_remote": True,
        "auto_queries": True,
        "custom_queries": [],
        "excluded_queries": [],
        "max_queries": 20,
        "results_per_query": 25,
        "max_age_days": 30,
        "apply_first_threshold": 65,
        "min_skill_overlap": 0.4,
        "weights": default_weights(),
        "semantic_mode": "local",
        "respect_policy_filters": True,
        "notify_new_matches": True,
    }


def clean_tier(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce one tier dict from the UI into the stored shape."""
    name = str(raw.get("name") or "").strip()[:120] or "Unnamed tier"
    modes = [m for m in (raw.get("work_modes") or []) if m in WORK_MODES] or list(WORK_MODES)
    places = []
    for place in raw.get("places") or []:
        text = str(place).strip()[:120]
        if text and text.lower() not in (p.lower() for p in places):
            places.append(text)
    kind = raw.get("kind") if raw.get("kind") in TIER_KINDS else "apply_first"
    group = str(raw.get("group") or "").strip()[:120] or name
    return {"name": name, "group": group, "work_modes": modes, "places": places, "kind": kind}


def load_config(db: Session, user_id: str) -> HuntConfig:
    """Return the user's HuntConfig, creating it from the seed on first use."""
    config = db.scalar(select(HuntConfig).where(HuntConfig.user_id == user_id))
    if config is None:
        config = HuntConfig(user_id=user_id, **seed_values())
        db.add(config)
        db.flush()
    return config


def effective_weights(config: Any) -> dict[str, float]:
    weights = default_weights()
    for key, value in dict(getattr(config, "weights", None) or {}).items():
        if key in weights:
            try:
                weights[key] = max(0.0, float(value))
            except (TypeError, ValueError):
                continue
    return weights


def breakdown_max(config: Any) -> dict[str, float]:
    """Points each factor can contribute to the 0..100 hunt score."""
    weights = effective_weights(config)
    if getattr(config, "semantic_mode", "local") == "off":
        weights["semantic"] = 0.0
    total = sum(weights.values()) or 1.0
    return {k: round(v * 100.0 / total, 2) for k, v in weights.items()}


__all__ = [
    "breakdown_max",
    "DEFAULT_COUNTRY_PLACES",
    "DEFAULT_LOCATION_TIERS",
    "DEFAULT_SCHEDULE_CRON",
    "HUNT_AGENT_KEY",
    "SEMANTIC_MODES",
    "SENIORITY_LEVELS",
    "TIER_KINDS",
    "WORK_MODES",
    "clean_tier",
    "default_weights",
    "effective_weights",
    "load_config",
    "seed_values",
]

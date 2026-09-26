"""Career profile: the canonical, user-editable source of candidate facts."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import Context, CurrentProfile, DbSession
from app.core.errors import NotFoundError
from app.db.models.identity import (
    CareerFact,
    Education,
    Experience,
    ProfileSkill,
    Project,
    Skill,
)
from app.schemas.common import MessageResponse
from app.schemas.identity import (
    CareerFactIn,
    CareerFactOut,
    EducationIn,
    EducationOut,
    ExperienceIn,
    ExperienceOut,
    ProfileIn,
    ProfileOut,
    ProfileSkillIn,
    ProfileSkillOut,
    ProjectIn,
    ProjectOut,
)
from app.services import audit
from app.services.normalize import slugify

router = APIRouter(prefix="/profile", tags=["profile"])

_PROFILE_FIELDS = list(ProfileIn.model_fields.keys())


def _skill_out(ps: ProfileSkill) -> ProfileSkillOut:
    return ProfileSkillOut(
        id=ps.id,
        name=ps.skill.name if ps.skill else "",
        slug=ps.skill.slug if ps.skill else "",
        category=ps.skill.category if ps.skill else "",
        years=ps.years,
        proficiency=ps.proficiency,
        is_primary=ps.is_primary,
        evidence_note=ps.evidence_note,
    )


def _serialize(profile: Any) -> ProfileOut:
    return ProfileOut(
        id=profile.id,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        **{f: getattr(profile, f) for f in _PROFILE_FIELDS},
        experiences=[ExperienceOut.model_validate(e) for e in profile.experiences],
        projects=[ProjectOut.model_validate(p) for p in profile.projects],
        education=[EducationOut.model_validate(e) for e in profile.education],
        skills=[_skill_out(s) for s in profile.profile_skills],
        facts=[CareerFactOut.model_validate(f) for f in profile.facts],
    )


@router.get("", response_model=ProfileOut)
def get_profile(profile: CurrentProfile) -> ProfileOut:
    return _serialize(profile)


@router.put("", response_model=ProfileOut)
def update_profile(
    payload: ProfileIn, db: DbSession, profile: CurrentProfile, ctx: Context
) -> ProfileOut:
    changes: dict[str, Any] = {}
    for name, value in payload.model_dump().items():
        if getattr(profile, name, None) != value:
            changes[name] = value
            setattr(profile, name, value)

    db.flush()
    if changes:
        audit.record(
            db,
            action="profile.update",
            user_id=ctx.user_id,
            actor=ctx.actor,
            entity_type="career_profile",
            entity_id=profile.id,
            summary=f"Updated profile fields: {', '.join(sorted(changes))}",
            after=changes,
            ip_address=ctx.ip_address,
        )
    return _serialize(profile)


# --------------------------------------------------------------------------
# Generic child-collection handling
# --------------------------------------------------------------------------
def _owned(db: Any, model: Any, item_id: str, profile_id: str) -> Any:
    item = db.get(model, item_id)
    if item is None or item.profile_id != profile_id:
        raise NotFoundError("That record does not exist.")
    return item


@router.get("/experiences", response_model=list[ExperienceOut])
def list_experiences(profile: CurrentProfile) -> list[ExperienceOut]:
    return [ExperienceOut.model_validate(e) for e in profile.experiences]


@router.post("/experiences", response_model=ExperienceOut, status_code=201)
def add_experience(
    payload: ExperienceIn, db: DbSession, profile: CurrentProfile, ctx: Context
) -> ExperienceOut:
    item = Experience(profile_id=profile.id, **payload.model_dump())
    db.add(item)
    db.flush()
    audit.record(
        db, action="profile.experience.create", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="experience", entity_id=item.id,
        summary=f"Added experience: {item.title} at {item.company}",
    )
    return ExperienceOut.model_validate(item)


@router.put("/experiences/{item_id}", response_model=ExperienceOut)
def update_experience(
    item_id: str, payload: ExperienceIn, db: DbSession, profile: CurrentProfile, ctx: Context
) -> ExperienceOut:
    item = _owned(db, Experience, item_id, profile.id)
    for name, value in payload.model_dump().items():
        setattr(item, name, value)
    db.flush()
    audit.record(
        db, action="profile.experience.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="experience", entity_id=item.id, summary=f"Updated experience: {item.title}",
    )
    return ExperienceOut.model_validate(item)


@router.delete("/experiences/{item_id}", response_model=MessageResponse)
def delete_experience(
    item_id: str, db: DbSession, profile: CurrentProfile, ctx: Context
) -> MessageResponse:
    item = _owned(db, Experience, item_id, profile.id)
    db.delete(item)
    audit.record(
        db, action="profile.experience.delete", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="experience", entity_id=item_id, summary="Deleted an experience entry",
    )
    return MessageResponse(message="Experience removed.")


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(profile: CurrentProfile) -> list[ProjectOut]:
    return [ProjectOut.model_validate(p) for p in profile.projects]


@router.post("/projects", response_model=ProjectOut, status_code=201)
def add_project(
    payload: ProjectIn, db: DbSession, profile: CurrentProfile, ctx: Context
) -> ProjectOut:
    item = Project(profile_id=profile.id, **payload.model_dump())
    db.add(item)
    db.flush()
    audit.record(
        db, action="profile.project.create", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="project", entity_id=item.id, summary=f"Added project: {item.name}",
    )
    return ProjectOut.model_validate(item)


@router.put("/projects/{item_id}", response_model=ProjectOut)
def update_project(
    item_id: str, payload: ProjectIn, db: DbSession, profile: CurrentProfile, ctx: Context
) -> ProjectOut:
    item = _owned(db, Project, item_id, profile.id)
    for name, value in payload.model_dump().items():
        setattr(item, name, value)
    db.flush()
    audit.record(
        db, action="profile.project.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="project", entity_id=item.id, summary=f"Updated project: {item.name}",
    )
    return ProjectOut.model_validate(item)


@router.delete("/projects/{item_id}", response_model=MessageResponse)
def delete_project(
    item_id: str, db: DbSession, profile: CurrentProfile, ctx: Context
) -> MessageResponse:
    item = _owned(db, Project, item_id, profile.id)
    db.delete(item)
    audit.record(
        db, action="profile.project.delete", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="project", entity_id=item_id, summary="Deleted a project",
    )
    return MessageResponse(message="Project removed.")


@router.get("/education", response_model=list[EducationOut])
def list_education(profile: CurrentProfile) -> list[EducationOut]:
    return [EducationOut.model_validate(e) for e in profile.education]


@router.post("/education", response_model=EducationOut, status_code=201)
def add_education(
    payload: EducationIn, db: DbSession, profile: CurrentProfile, ctx: Context
) -> EducationOut:
    item = Education(profile_id=profile.id, **payload.model_dump())
    db.add(item)
    db.flush()
    audit.record(
        db, action="profile.education.create", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="education", entity_id=item.id, summary=f"Added education: {item.institution}",
    )
    return EducationOut.model_validate(item)


@router.put("/education/{item_id}", response_model=EducationOut)
def update_education(
    item_id: str, payload: EducationIn, db: DbSession, profile: CurrentProfile, ctx: Context
) -> EducationOut:
    item = _owned(db, Education, item_id, profile.id)
    for name, value in payload.model_dump().items():
        setattr(item, name, value)
    db.flush()
    return EducationOut.model_validate(item)


@router.delete("/education/{item_id}", response_model=MessageResponse)
def delete_education(
    item_id: str, db: DbSession, profile: CurrentProfile, ctx: Context
) -> MessageResponse:
    item = _owned(db, Education, item_id, profile.id)
    db.delete(item)
    return MessageResponse(message="Education entry removed.")


# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------
@router.get("/skills", response_model=list[ProfileSkillOut])
def list_skills(profile: CurrentProfile) -> list[ProfileSkillOut]:
    return [_skill_out(s) for s in profile.profile_skills]


@router.post("/skills", response_model=ProfileSkillOut, status_code=201)
def add_skill(
    payload: ProfileSkillIn, db: DbSession, profile: CurrentProfile, ctx: Context
) -> ProfileSkillOut:
    slug = slugify(payload.name)
    skill = db.execute(select(Skill).where(Skill.slug == slug)).scalar_one_or_none()
    if skill is None:
        skill = Skill(name=payload.name.strip(), slug=slug)
        db.add(skill)
        db.flush()

    existing = next((ps for ps in profile.profile_skills if ps.skill_id == skill.id), None)
    if existing is None:
        existing = ProfileSkill(profile_id=profile.id, skill_id=skill.id)
        db.add(existing)

    existing.years = payload.years
    existing.proficiency = payload.proficiency
    existing.is_primary = payload.is_primary
    existing.evidence_note = payload.evidence_note
    db.flush()
    db.refresh(existing)

    audit.record(
        db, action="profile.skill.upsert", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="profile_skill", entity_id=existing.id,
        summary=f"Set skill {skill.name}" + (f" at {payload.years} years" if payload.years else ""),
    )
    return _skill_out(existing)


@router.put("/skills/{item_id}", response_model=ProfileSkillOut)
def update_skill(
    item_id: str, payload: ProfileSkillIn, db: DbSession, profile: CurrentProfile, ctx: Context
) -> ProfileSkillOut:
    item = _owned(db, ProfileSkill, item_id, profile.id)
    item.years = payload.years
    item.proficiency = payload.proficiency
    item.is_primary = payload.is_primary
    item.evidence_note = payload.evidence_note
    db.flush()
    return _skill_out(item)


@router.delete("/skills/{item_id}", response_model=MessageResponse)
def delete_skill(
    item_id: str, db: DbSession, profile: CurrentProfile, ctx: Context
) -> MessageResponse:
    item = _owned(db, ProfileSkill, item_id, profile.id)
    db.delete(item)
    return MessageResponse(message="Skill removed.")


# --------------------------------------------------------------------------
# Career facts (the evidence AI generation is allowed to cite)
# --------------------------------------------------------------------------
@router.get("/facts", response_model=list[CareerFactOut])
def list_facts(profile: CurrentProfile) -> list[CareerFactOut]:
    return [CareerFactOut.model_validate(f) for f in profile.facts]


@router.post("/facts", response_model=CareerFactOut, status_code=201)
def add_fact(
    payload: CareerFactIn, db: DbSession, profile: CurrentProfile, ctx: Context
) -> CareerFactOut:
    item = CareerFact(profile_id=profile.id, **payload.model_dump())
    db.add(item)
    db.flush()
    audit.record(
        db, action="profile.fact.create", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="career_fact", entity_id=item.id,
        summary=f"Added career fact: {item.statement[:80]}",
    )
    return CareerFactOut.model_validate(item)


@router.delete("/facts/{item_id}", response_model=MessageResponse)
def delete_fact(
    item_id: str, db: DbSession, profile: CurrentProfile, ctx: Context
) -> MessageResponse:
    item = _owned(db, CareerFact, item_id, profile.id)
    db.delete(item)
    audit.record(
        db, action="profile.fact.delete", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="career_fact", entity_id=item_id, summary="Deleted a career fact",
    )
    return MessageResponse(message="Fact removed.")

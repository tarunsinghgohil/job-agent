"""The required AI functions (spec section 7).

Every function here:
  * fences the job description as untrusted data,
  * retrieves stored evidence before generating anything about the candidate,
  * returns the evidence ids it used so the audit trail can cite them,
  * refuses to assert anything the evidence does not support.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.identity import CareerProfile
from app.db.models.jobs import Job
from app.services.ai.client import (
    GROUNDING_RULE,
    UNTRUSTED_PREAMBLE,
    AIError,
    AIService,
    wrap_untrusted,
)
from app.services.ai.rag import Evidence, render_evidence_block, retrieve_evidence
from app.services.normalize import norm_text

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Prompt context builders
# --------------------------------------------------------------------------
def profile_brief(profile: CareerProfile | None) -> str:
    """Compact, factual candidate summary. Only stored values, never inferred."""
    if profile is None:
        return "(no career profile on file)"
    bits = [f"{profile.full_name or 'The candidate'}"]
    if profile.headline:
        bits.append(f"- {profile.headline}")
    lines = [" ".join(bits)]
    if profile.total_experience_years:
        lines.append(f"Total experience: {profile.total_experience_years} years.")
    if profile.location:
        lines.append(f"Based in {profile.location}.")
    lines.append(f"Open to relocation: {'yes' if profile.open_to_relocation else 'no'}.")
    if profile.notice_period:
        lines.append(f"Notice period: {profile.notice_period}.")
    if profile.current_ctc_lpa:
        lines.append(f"Current CTC: {profile.current_ctc_lpa} LPA.")
    if profile.expected_ctc_lpa:
        lines.append(f"Expected CTC: {profile.expected_ctc_lpa} LPA.")
    skills = [ps.skill.name for ps in (profile.profile_skills or []) if ps.skill]
    if skills:
        lines.append(f"Skills on file: {', '.join(skills[:60])}.")
    return "\n".join(lines)


def job_brief(job: Job) -> str:
    """Job metadata we trust (from structured fields), excluding the free text."""
    salary = ""
    if job.salary_min_lpa or job.salary_max_lpa:
        lo, hi = job.salary_min_lpa, job.salary_max_lpa
        salary = f"{lo}-{hi} LPA" if lo and hi and lo != hi else f"{lo or hi} LPA"
    return "\n".join(
        [
            f"Title: {job.title}",
            f"Company: {job.company}",
            f"Location: {job.location}{' (remote)' if job.is_remote else ''}",
            f"Salary: {salary or 'not stated'}",
            f"Employment type: {job.employment_type}",
            f"Industry: {job.industry or 'not stated'}",
            f"Source: {job.source_name}",
        ]
    )


def _evidence_for(
    db: Session, user_id: str, query: str, *, limit: int = 8, resume_id: str | None = None
) -> tuple[list[Evidence], str]:
    evidence = retrieve_evidence(db, user_id, query, limit=limit, resume_id=resume_id)
    return evidence, render_evidence_block(evidence)


# --------------------------------------------------------------------------
# 1. Job extraction
# --------------------------------------------------------------------------
def extract_job_facts(ai: AIService, job: Job) -> dict[str, Any]:
    """Pull structured fields out of an unstructured posting."""
    system = (
        "You extract structured facts from job postings. "
        f"{UNTRUSTED_PREAMBLE} "
        "Report only what the posting states. Use null when it does not say."
    )
    user = (
        f"{job_brief(job)}\n\n"
        f"{wrap_untrusted(job.description)}\n\n"
        "Return JSON with keys: required_skills (array of strings), "
        "preferred_skills (array of strings), responsibilities (array of up to 5 strings), "
        "experience_min_years (number or null), experience_max_years (number or null), "
        "employment_type (string or null), is_remote (boolean or null), "
        "seniority (string or null), industry (string or null)."
    )
    return ai.complete_json(
        function="job_extraction",
        system=system,
        user=user,
        required_keys=("required_skills", "preferred_skills"),
        cheap=True,
    )


# --------------------------------------------------------------------------
# 2. Skill normalization
# --------------------------------------------------------------------------
def normalize_skills(ai: AIService, raw_skills: list[str]) -> dict[str, Any]:
    """Map messy skill strings onto canonical names, e.g. 'ReactJS' -> 'React'."""
    if not raw_skills:
        return {"skills": []}
    system = (
        "You normalize technology skill names to their canonical form. "
        "Do not invent skills that are not in the input list. "
        "Merge obvious synonyms."
    )
    user = (
        f"Normalize these skill strings: {raw_skills}\n\n"
        "Return JSON with key 'skills': an array of objects "
        "{raw, canonical, category}. Category is one of: language, framework, "
        "library, tool, platform, database, practice, other."
    )
    return ai.complete_json(
        function="skill_normalization", system=system, user=user,
        required_keys=("skills",), cheap=True,
    )


# --------------------------------------------------------------------------
# 3. Semantic match
# --------------------------------------------------------------------------
def semantic_match(
    db: Session, ai: AIService, user_id: str, job: Job, profile: CareerProfile | None,
    deterministic_score: float, deterministic_decision: str,
) -> dict[str, Any]:
    """AI second opinion. Advisory only: hard filters still have final say."""
    evidence, evidence_block = _evidence_for(
        db, user_id, f"{job.title} {job.description[:1500]}", limit=8
    )
    system = (
        "You are a blunt careers analyst. Judge fit honestly and do not flatter. "
        f"{UNTRUSTED_PREAMBLE} {GROUNDING_RULE}"
    )
    user = (
        f"Candidate:\n{profile_brief(profile)}\n\n"
        f"Stored evidence about the candidate (cite these ids):\n{evidence_block}\n\n"
        f"Job:\n{job_brief(job)}\n\n{wrap_untrusted(job.description)}\n\n"
        f"A deterministic keyword scorer rated this {deterministic_score:.0f}/100 "
        f"({deterministic_decision}). That scorer only counts keywords, so correct it "
        "where it is wrong, but do not argue with hard requirements.\n\n"
        "Return JSON with keys: ai_score (integer 0-100), "
        "verdict (STRONG_FIT, WORTH_APPLYING or WEAK_FIT), "
        "reasons (array of exactly 3 short strings), "
        "gaps (array of up to 3 requirements the candidate does not meet; [] if none), "
        "pitch (one sentence under 30 words to open an application with), "
        "evidence_used (array of the evidence ids you relied on)."
    )
    data = ai.complete_json(
        function="semantic_match", system=system, user=user,
        required_keys=("ai_score", "verdict", "reasons"),
    )
    data["evidence"] = [e.as_dict() for e in evidence]
    return data


# --------------------------------------------------------------------------
# 4. Resume recommendation
# --------------------------------------------------------------------------
def resume_advice(
    db: Session, ai: AIService, user_id: str, job: Job,
    profile: CareerProfile | None, resume_names: list[str],
) -> dict[str, Any]:
    evidence, evidence_block = _evidence_for(db, user_id, f"{job.title} {job.description[:1200]}")
    system = (
        "You are a resume coach. Be concrete and specific to this job. "
        f"{UNTRUSTED_PREAMBLE} {GROUNDING_RULE}"
    )
    user = (
        f"Candidate:\n{profile_brief(profile)}\n\n"
        f"Stored evidence:\n{evidence_block}\n\n"
        f"Available resume variants: {resume_names or ['(none)']}\n\n"
        f"Job:\n{job_brief(job)}\n\n{wrap_untrusted(job.description)}\n\n"
        "Return JSON with keys: recommended_resume (string chosen from the variants listed, "
        "or null if none exist), emphasize (array of 3-5 specific things already in the "
        "evidence to move higher), downplay (array of up to 3 things to shorten; [] if none), "
        "headline (a resume headline under 15 words), "
        "evidence_used (array of evidence ids)."
    )
    data = ai.complete_json(
        function="resume_recommendation", system=system, user=user,
        required_keys=("emphasize",),
    )
    data["evidence"] = [e.as_dict() for e in evidence]
    return data


# --------------------------------------------------------------------------
# 5. Resume tailoring
# --------------------------------------------------------------------------
def tailor_resume(
    db: Session, ai: AIService, user_id: str, job: Job,
    profile: CareerProfile | None, base_text: str, resume_id: str | None = None,
) -> dict[str, Any]:
    evidence, evidence_block = _evidence_for(
        db, user_id, f"{job.title} {job.description[:1500]}", limit=12, resume_id=resume_id
    )
    system = (
        "You tailor an existing resume to a specific job. You may reorder, reword and "
        "re-emphasise existing content. You may NOT add any employer, title, date, "
        "degree, certification, metric or skill that is absent from the base resume "
        f"and the stored evidence. {UNTRUSTED_PREAMBLE} {GROUNDING_RULE}"
    )
    user = (
        f"Candidate:\n{profile_brief(profile)}\n\n"
        f"Stored evidence:\n{evidence_block}\n\n"
        f"Base resume text:\n---\n{base_text[:12000]}\n---\n\n"
        f"Target job:\n{job_brief(job)}\n\n{wrap_untrusted(job.description)}\n\n"
        "Return JSON with keys: summary (a rewritten 2-3 sentence professional summary), "
        "highlights (array of 4-6 tailored bullet points, each traceable to the base "
        "resume or evidence), skills_order (array of skills in the order they should "
        "appear), changed_sections (array of {section, change, rationale}), "
        "omitted (array of things you deliberately left out), "
        "unsupported_requests (array of job requirements you could NOT support from the "
        "evidence -- be honest here, this is how the user learns their real gaps), "
        "evidence_used (array of evidence ids)."
    )
    data = ai.complete_json(
        function="resume_tailoring", system=system, user=user,
        required_keys=("summary", "highlights"), cache_ttl_hours=0,
    )
    data["evidence"] = [e.as_dict() for e in evidence]
    data["validation"] = validate_generated_claims(data, evidence, base_text)
    return data


def validate_generated_claims(
    data: dict[str, Any], evidence: list[Evidence], base_text: str
) -> dict[str, Any]:
    """Flag generated text containing entities absent from the source material.

    A deterministic backstop for the 'never invent facts' rule: the model is
    instructed not to fabricate, and this catches it when it does anyway.
    """
    corpus = norm_text(" ".join([base_text] + [e.content for e in evidence]))
    generated_parts: list[str] = []
    for key in ("summary", "highlights", "skills_order"):
        value = data.get(key)
        if isinstance(value, str):
            generated_parts.append(value)
        elif isinstance(value, list):
            generated_parts.extend(str(v) for v in value)
    generated = " ".join(generated_parts)

    import re

    suspicious: list[str] = []
    # Numbers that look like claims (percentages, multipliers, large counts).
    for token in set(re.findall(r"\b\d+(?:\.\d+)?%|\b\d+x\b|\b\d{3,}\b", generated)):
        if norm_text(token) not in corpus:
            suspicious.append(token)
    # Year-like tokens not present in the source.
    for token in set(re.findall(r"\b(?:19|20)\d{2}\b", generated)):
        if token not in corpus:
            suspicious.append(token)

    return {
        "ok": not suspicious,
        "unsupported_tokens": sorted(suspicious)[:20],
        "note": (
            "These values appear in the generated text but not in the base resume or "
            "retrieved evidence. Review them before using this draft."
            if suspicious
            else "No unsupported figures detected."
        ),
    }


# --------------------------------------------------------------------------
# 6. Cover letter
# --------------------------------------------------------------------------
def cover_letter(
    db: Session, ai: AIService, user_id: str, job: Job, profile: CareerProfile | None
) -> dict[str, Any]:
    evidence, evidence_block = _evidence_for(db, user_id, f"{job.title} {job.description[:1200]}")
    system = (
        "You write short, specific cover letters in the candidate's voice. Under 200 words. "
        "Plain text, no markdown, no salutation placeholders like [Name]. "
        f"{UNTRUSTED_PREAMBLE} {GROUNDING_RULE}"
    )
    user = (
        f"Candidate:\n{profile_brief(profile)}\n\n"
        f"Stored evidence:\n{evidence_block}\n\n"
        f"Job:\n{job_brief(job)}\n\n{wrap_untrusted(job.description)}\n\n"
        "Write the letter. Open with a specific reason this role fits, not "
        "'I am writing to apply'. Cite two concrete skills the posting actually asks for "
        "and the evidence actually supports. State availability. Close in one short line.\n\n"
        "Return JSON with keys: letter (the full text), "
        "evidence_used (array of evidence ids)."
    )
    data = ai.complete_json(
        function="cover_letter", system=system, user=user,
        required_keys=("letter",), cache_ttl_hours=0,
    )
    data["evidence"] = [e.as_dict() for e in evidence]
    return data


# --------------------------------------------------------------------------
# 7. Question answering
# --------------------------------------------------------------------------
def answer_question(
    db: Session, ai: AIService, user_id: str, question: str,
    profile: CareerProfile | None, known_answers: list[tuple[str, str]],
    job: Job | None = None,
) -> dict[str, Any]:
    evidence, evidence_block = _evidence_for(db, user_id, question, limit=6)
    known = "\n".join(f"Q: {q}\nA: {a}" for q, a in known_answers) or "(none on file)"
    job_ctx = (
        f"\n\nThis question is for this job:\n{job_brief(job)}\n\n{wrap_untrusted(job.description)}"
        if job
        else ""
    )
    system = (
        "You draft job application answers in the candidate's own voice. Direct and "
        "concrete, under 80 words, no preamble, no surrounding quotation marks. "
        f"{UNTRUSTED_PREAMBLE} {GROUNDING_RULE} "
        "Never contradict an answer the candidate has already given."
    )
    user = (
        f"Candidate:\n{profile_brief(profile)}\n\n"
        f"Stored evidence:\n{evidence_block}\n\n"
        f"Answers already given -- match this tone, never contradict these facts:\n{known}"
        f"{job_ctx}\n\n"
        f"Draft an answer to: {question}\n\n"
        "Return JSON with keys: answer (string), confidence (number 0-1), "
        "needs_review (boolean -- true if you had to infer anything), "
        "evidence_used (array of evidence ids)."
    )
    data = ai.complete_json(
        function="question_answering", system=system, user=user,
        required_keys=("answer",), cache_ttl_hours=0,
    )
    data["evidence"] = [e.as_dict() for e in evidence]
    return data


# --------------------------------------------------------------------------
# 8. Job summary
# --------------------------------------------------------------------------
def summarize_job(ai: AIService, job: Job) -> dict[str, Any]:
    system = (
        "You summarize job postings for a busy candidate. "
        f"{UNTRUSTED_PREAMBLE}"
    )
    user = (
        f"{job_brief(job)}\n\n{wrap_untrusted(job.description)}\n\n"
        "Return JSON with keys: summary (3 sentences maximum), "
        "must_haves (array of up to 5 hard requirements), "
        "red_flags (array of up to 3 concerns; [] if none)."
    )
    return ai.complete_json(
        function="job_summary", system=system, user=user,
        required_keys=("summary",), cheap=True,
    )


# --------------------------------------------------------------------------
# 9. Rejection reason summary
# --------------------------------------------------------------------------
def summarize_rejections(ai: AIService, rejected: list[dict[str, Any]]) -> dict[str, Any]:
    if not rejected:
        return {"themes": [], "summary": "No rejections to analyse yet."}
    system = "You find patterns in why job applications were rejected. Be direct."
    user = (
        f"Rejected applications and their recorded reasons:\n{rejected[:60]}\n\n"
        "Return JSON with keys: summary (2 sentences), "
        "themes (array of {theme, count, example}), "
        "suggested_actions (array of up to 5 concrete changes)."
    )
    return ai.complete_json(
        function="rejection_summary", system=system, user=user,
        required_keys=("summary",), cheap=True,
    )


# --------------------------------------------------------------------------
# 10. Weekly optimization suggestions
# --------------------------------------------------------------------------
def weekly_suggestions(ai: AIService, stats: dict[str, Any]) -> dict[str, Any]:
    system = (
        "You advise on job-search strategy from real funnel numbers. Be specific and "
        "quantitative. Suggest changes to search configuration; never claim to have "
        "made a change yourself."
    )
    user = (
        f"This week's funnel:\n{stats}\n\n"
        "Return JSON with keys: summary (2-3 sentences), "
        "suggestions (array of {title, rationale, setting_to_change}), "
        "warnings (array of up to 3; [] if none)."
    )
    return ai.complete_json(
        function="weekly_optimization", system=system, user=user,
        required_keys=("summary", "suggestions"),
    )

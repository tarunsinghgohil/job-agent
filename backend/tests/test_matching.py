"""Matching engine: hard filters, weighted scoring, thresholds, explanations."""
from __future__ import annotations

import pytest

from app.db.models.enums import MatchDecision, RuleField, RuleOperator
from app.db.models.preferences import JobPreference
from app.services.matching import recommend_resume, score_job


class FakePrefs:
    """Stand-in for a JobPreference row, so these stay pure unit tests."""

    def __init__(self, **overrides):
        self.target_roles = ["Frontend Developer", "React JS Developer"]
        self.preferred_locations = ["Jaipur", "Remote", "Indore"]
        self.remote_ok = True
        self.remote_only = False
        self.min_salary_lpa = 14.0
        self.target_salary_lpa = 16.0
        self.experience_min_years = 3.0
        self.experience_max_years = 6.0
        self.employment_types = ["full_time"]
        self.industries = ["software", "it", "healthcare"]
        self.preferred_companies = []
        self.excluded_companies = []
        self.must_have_keywords = ["React"]
        self.nice_to_have_keywords = ["TypeScript", "Redux", "Next.js", "Jest"]
        self.excluded_keywords = []
        self.review_threshold = 70
        self.high_priority_threshold = 85
        self.scoring_weights = JobPreference.default_weights()
        self.semantic_scoring_enabled = False
        self.semantic_weight = 0.2
        for key, value in overrides.items():
            setattr(self, key, value)


class FakeRule:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "rule-1")
        self.name = kwargs.get("name", "test rule")
        self.field = kwargs["field"]
        self.operator = kwargs["operator"]
        self.value = kwargs["value"]
        self.weight = kwargs.get("weight", 0.0)
        self.is_hard = kwargs.get("is_hard", False)
        self.enabled = kwargs.get("enabled", True)
        self.priority = kwargs.get("priority", 100)
        self.explanation = kwargs.get("explanation", "")
        self.case_sensitive = kwargs.get("case_sensitive", False)


def good_job(**overrides) -> dict:
    job = {
        "title": "Senior Frontend Developer",
        "company": "Example Product Co",
        "location": "Remote",
        "is_remote": True,
        "description": (
            "Build interfaces with React, TypeScript, Redux and Next.js. "
            "Testing with Jest expected. 4 to 6 years of experience."
        ),
        "industry": "software",
        "employment_type": "full_time",
        "salary_min_lpa": 16.0,
        "salary_max_lpa": 20.0,
        "experience_min_years": 4.0,
        "experience_max_years": 6.0,
        "source_name": "test",
    }
    job.update(overrides)
    return job


# --------------------------------------------------------------------------
# Hard filters
# --------------------------------------------------------------------------
def test_missing_must_have_keyword_forces_reject():
    job = good_job(
        title="Backend Engineer",
        description="Build services in Go and Postgres. No frontend work.",
    )
    result = score_job(job, FakePrefs())

    assert result.decision == MatchDecision.REJECT
    assert any("required keywords" in r for r in result.hard_fail_reasons)


def test_salary_below_floor_forces_reject_even_with_perfect_skills():
    job = good_job(salary_min_lpa=8.0, salary_max_lpa=10.0)
    result = score_job(job, FakePrefs())

    assert result.decision == MatchDecision.REJECT
    assert any("below the 14.0 LPA minimum" in r for r in result.hard_fail_reasons)


def test_unknown_salary_does_not_trigger_the_floor():
    """Most feeds omit salary; treating that as zero would bury good jobs."""
    job = good_job(salary_min_lpa=None, salary_max_lpa=None)
    result = score_job(job, FakePrefs())

    assert not any("minimum" in r for r in result.hard_fail_reasons)
    assert result.decision != MatchDecision.REJECT


def test_excluded_keyword_forces_reject():
    prefs = FakePrefs(excluded_keywords=["unpaid"])
    job = good_job(description=good_job()["description"] + " This is an unpaid internship.")
    result = score_job(job, prefs)

    assert result.decision == MatchDecision.REJECT
    assert any("unpaid" in r for r in result.hard_fail_reasons)


def test_excluded_company_forces_reject():
    prefs = FakePrefs(excluded_companies=["Example Product Co Pvt Ltd"])
    result = score_job(good_job(), prefs)

    assert result.decision == MatchDecision.REJECT
    assert any("excluded list" in r for r in result.hard_fail_reasons)


def test_experience_above_configured_maximum_forces_reject():
    job = good_job(experience_min_years=10.0, experience_max_years=15.0)
    result = score_job(job, FakePrefs())

    assert result.decision == MatchDecision.REJECT
    assert any("above the configured maximum" in r for r in result.hard_fail_reasons)


def test_wrong_employment_type_forces_reject():
    result = score_job(good_job(employment_type="contract"), FakePrefs())

    assert result.decision == MatchDecision.REJECT
    assert any("Employment type" in r for r in result.hard_fail_reasons)


def test_unlisted_location_forces_reject_when_not_remote():
    job = good_job(location="Bengaluru", is_remote=False)
    result = score_job(job, FakePrefs())

    assert result.decision == MatchDecision.REJECT
    assert any("not in the preferred list" in r for r in result.hard_fail_reasons)


def test_remote_only_rejects_onsite_roles():
    prefs = FakePrefs(remote_only=True)
    job = good_job(location="Jaipur", is_remote=False)
    result = score_job(job, prefs)

    assert result.decision == MatchDecision.REJECT
    assert any("Remote-only" in r for r in result.hard_fail_reasons)


def test_hard_failure_beats_a_high_score():
    """Deterministic rules have final authority over an otherwise great job."""
    prefs = FakePrefs(excluded_keywords=["nightshift"])
    job = good_job(description=good_job()["description"] + " Requires nightshift cover.")
    result = score_job(job, prefs)

    assert result.deterministic_score > 70
    assert result.decision == MatchDecision.REJECT


# --------------------------------------------------------------------------
# Scoring and thresholds
# --------------------------------------------------------------------------
def test_strong_job_reaches_high_priority():
    result = score_job(good_job(), FakePrefs())

    assert result.decision == MatchDecision.HIGH_PRIORITY
    assert result.score >= 85
    assert "React" in result.matched_skills


def test_score_never_exceeds_one_hundred():
    prefs = FakePrefs(
        scoring_weights={k: 100.0 for k in JobPreference.default_weights()}
    )
    result = score_job(good_job(), prefs)

    assert result.score <= 100.0


def test_threshold_changes_move_the_decision():
    job = good_job(description="A React role. Nothing else specified.", title="Web Developer")
    lenient = score_job(job, FakePrefs(review_threshold=10, high_priority_threshold=20))
    strict = score_job(job, FakePrefs(review_threshold=95, high_priority_threshold=99))

    assert lenient.decision == MatchDecision.HIGH_PRIORITY
    assert strict.decision == MatchDecision.REJECT


def test_weights_are_editable_and_actually_applied():
    zeroed = FakePrefs(scoring_weights={**JobPreference.default_weights(), "role_fit": 0.0})
    baseline = score_job(good_job(), FakePrefs())
    adjusted = score_job(good_job(), zeroed)

    assert adjusted.breakdown["role_fit"] == 0.0
    assert adjusted.score < baseline.score


def test_breakdown_sums_to_the_deterministic_score():
    result = score_job(good_job(), FakePrefs())

    assert result.deterministic_score == pytest.approx(sum(result.breakdown.values()), abs=0.01)


def test_explanation_is_populated_and_mentions_the_decision():
    result = score_job(good_job(), FakePrefs())

    assert result.explanation
    assert result.decision in result.explanation


def test_rejection_explanation_leads_with_the_reason():
    result = score_job(good_job(salary_min_lpa=5, salary_max_lpa=6), FakePrefs())

    assert result.explanation.startswith("Rejected:")


# --------------------------------------------------------------------------
# Semantic blending
# --------------------------------------------------------------------------
def test_semantic_score_is_ignored_unless_enabled():
    result = score_job(good_job(), FakePrefs(), semantic_score=10.0)

    assert result.score == result.deterministic_score


def test_semantic_score_blends_when_enabled():
    prefs = FakePrefs(semantic_scoring_enabled=True, semantic_weight=0.5)
    result = score_job(good_job(), prefs, semantic_score=0.0)

    assert result.score == pytest.approx(result.deterministic_score * 0.5, abs=0.01)


def test_semantic_score_cannot_rescue_a_hard_failure():
    prefs = FakePrefs(semantic_scoring_enabled=True, semantic_weight=1.0)
    job = good_job(salary_min_lpa=3, salary_max_lpa=4)
    result = score_job(job, prefs, semantic_score=100.0)

    assert result.decision == MatchDecision.REJECT


# --------------------------------------------------------------------------
# User rules
# --------------------------------------------------------------------------
def test_hard_user_rule_can_reject():
    rule = FakeRule(
        field=RuleField.DESCRIPTION,
        operator=RuleOperator.CONTAINS,
        value={"value": ["graphql"]},
        is_hard=True,
        explanation="GraphQL is required for this search.",
    )
    result = score_job(good_job(), FakePrefs(), [rule])

    assert result.decision == MatchDecision.REJECT
    assert "GraphQL is required for this search." in result.hard_fail_reasons


def test_soft_user_rule_adds_its_weight():
    rule = FakeRule(
        field=RuleField.DESCRIPTION,
        operator=RuleOperator.CONTAINS,
        value={"value": ["jest"]},
        weight=5.0,
    )
    without = score_job(good_job(), FakePrefs())
    with_rule = score_job(good_job(), FakePrefs(), [rule])

    assert with_rule.breakdown.get("custom_rules") == 5.0
    assert with_rule.score >= without.score


def test_disabled_rule_is_skipped():
    rule = FakeRule(
        field=RuleField.DESCRIPTION,
        operator=RuleOperator.CONTAINS,
        value={"value": ["graphql"]},
        is_hard=True,
        enabled=False,
    )
    result = score_job(good_job(), FakePrefs(), [rule])

    assert result.decision != MatchDecision.REJECT


def test_rule_results_are_reported_for_the_ui():
    rule = FakeRule(
        field=RuleField.TITLE,
        operator=RuleOperator.CONTAINS,
        value={"value": ["frontend"]},
        weight=2.0,
    )
    result = score_job(good_job(), FakePrefs(), [rule])

    assert len(result.rule_results) == 1
    assert result.rule_results[0]["passed"] is True


# --------------------------------------------------------------------------
# Resume recommendation
# --------------------------------------------------------------------------
class FakeResume:
    def __init__(self, id, name, role_focus=(), skill_focus=(), industry_focus=(), default=False):
        self.id = id
        self.name = name
        self.role_focus = list(role_focus)
        self.skill_focus = list(skill_focus)
        self.industry_focus = list(industry_focus)
        self.is_default = default
        self.is_active = True


def test_recommends_the_best_matching_resume():
    frontend = FakeResume("r1", "Frontend", role_focus=["Frontend Developer"],
                          skill_focus=["React", "TypeScript"])
    backend = FakeResume("r2", "Backend", role_focus=["Backend Engineer"],
                         skill_focus=["Go", "Postgres"])

    resume_id, reason = recommend_resume(good_job(), [frontend, backend])

    assert resume_id == "r1"
    assert "Frontend" in reason


def test_falls_back_to_the_default_resume():
    generic = FakeResume("r1", "General", default=True)
    resume_id, reason = recommend_resume(good_job(), [generic])

    assert resume_id == "r1"
    assert "default" in reason.lower()


def test_no_resumes_yields_no_recommendation():
    assert recommend_resume(good_job(), []) == (None, "")

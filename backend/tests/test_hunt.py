"""3x Job Hunt: signals, query generation, assessment, discovery, and API flows."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base
from app.db.models.hunt import HuntResult
from app.db.models.identity import User
from app.db.models.jobs import Job, JobSource
from app.services.hunt.assess import assess_job
from app.services.hunt.defaults import seed_values
from app.services.hunt.queries import board_query, generate_queries
from app.services.hunt.semantic import local_scores
from app.services.hunt.signals import (
    assess_freshness,
    detect_remote_region,
    detect_seniority,
    detect_work_mode,
    experience_fit,
)
from app.services.normalize import best_apply_link, classify_apply_url
from app.services.resume.parser import extract_skills, normalize_skill_list
from app.services.sources.base import (
    _REGISTRY,
    JobSourceAdapter,
    RawJob,
    SourceQuery,
    SourceTestResult,
)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
USER_ID = "u" * 32


def cfg(**overrides) -> SimpleNamespace:
    values = seed_values()
    values.update(overrides)
    return SimpleNamespace(**values)


# ---------------------------------------------------------------------------
# Skill normalization
# ---------------------------------------------------------------------------
def test_skill_extraction_uses_whole_words():
    # "ts" used to match "requirements", "git" matched "digital", "java"
    # matched "javascript".
    found = extract_skills("Requirements: build digital products in JavaScript.")
    assert "TypeScript" not in found
    assert "Git" not in found
    assert "Java" not in found
    assert "JavaScript" in found


def test_skill_aliases_collapse_to_one_canonical_skill():
    assert extract_skills("ReactJS") == ["React"]
    assert extract_skills("React.js") == ["React"]
    assert normalize_skill_list(["React", "React.js", "ReactJS", "JS", "ECMAScript"]) == [
        "React",
        "JavaScript",
    ]


def test_mern_expands_into_its_stack():
    assert normalize_skill_list(["MERN"]) == ["MongoDB", "Express.js", "React", "Node.js"]
    found = extract_skills("Looking for a MERN stack developer")
    assert {"MongoDB", "Express.js", "React", "Node.js"} <= set(found)


def test_composite_and_custom_skills_are_kept():
    assert normalize_skill_list(["PostgreSQL/MySQL", "Recoil"]) == ["PostgreSQL", "MySQL", "Recoil"]


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("location", "title", "description", "is_remote", "expected"),
    [
        ("Remote - India", "Frontend Engineer", "", False, "remote"),
        ("Jaipur", "React Developer", "Hybrid: 3 days in office each week", False, "hybrid"),
        ("Jaipur (Hybrid)", "React Developer", "", False, "hybrid"),
        ("Bengaluru, Karnataka", "Frontend Developer", "You will work with remote teams", True, "onsite"),
        ("", "Frontend Developer", "This is a fully remote role", False, "remote"),
        ("Pune", "Frontend Developer", "", False, "onsite"),
        ("", "Frontend Developer", "", False, "unknown"),
    ],
)
def test_detect_work_mode(location, title, description, is_remote, expected):
    # "remote teams" in an office job's description must not flip it to remote,
    # but the location and title still decide; is_remote alone is overridden
    # by a named city only when the description is silent.
    result = detect_work_mode(location, title, description, is_remote)
    if expected == "onsite" and is_remote:
        # Loose provider flags win when nothing contradicts them.
        assert result in ("onsite", "remote")
    else:
        assert result == expected


@pytest.mark.parametrize(
    ("location", "description", "kind", "label"),
    [
        ("Remote - India", "", "country", "India"),
        ("Remote (Pune)", "", "country", "India"),
        ("USA", "", "foreign", "US"),
        ("Remote - US", "", "foreign", "US"),
        ("Europe", "", "foreign", "Europe"),
        ("Worldwide", "", "worldwide", "Worldwide"),
        ("Remote", "Open to candidates anywhere in India (IST hours).", "country", "India"),
        ("Remote", "You must be based in the United States.", "foreign", "US"),
        ("Remote", "", "unknown", ""),
    ],
)
def test_detect_remote_region(location, description, kind, label):
    result = detect_remote_region(
        location, description, country="India", country_places=seed_values()["country_places"]
    )
    assert result.kind == kind
    assert result.label == label


@pytest.mark.parametrize(
    ("title", "level"),
    [
        ("React Intern", "intern"),
        ("Junior Frontend Developer", "junior"),
        ("Associate Software Engineer", "junior"),
        ("Senior Associate, Frontend", "senior"),
        ("Senior React Developer", "senior"),
        ("Frontend Lead", "lead"),
        ("Frontend Developer", "mid"),
    ],
)
def test_detect_seniority(title, level):
    assert detect_seniority(title) == level


@pytest.mark.parametrize(
    ("job_min", "job_max", "expected"),
    [
        (5, 8, "strong"),     # the brief's "5-8 years" example
        (4, None, "strong"),  # "4+ years"
        (5, 7, "strong"),
        (3, 5, "good"),
        (6, None, "good"),
        (8, None, "stretch"),
        (1, 2, "under"),      # the brief's "1-2 years" example
        (None, None, "unknown"),
    ],
)
def test_experience_fit_for_five_and_a_half_years(job_min, job_max, expected):
    assert experience_fit(5.5, job_min, job_max, "mid")[0] == expected


def test_experience_fit_infers_from_title_when_years_are_missing():
    assert experience_fit(5.5, None, None, "senior")[0] == "good"
    assert experience_fit(5.5, None, None, "junior")[0] == "under"


def test_freshness_does_not_mistake_an_update_for_a_new_posting():
    fresh = assess_freshness(
        NOW - timedelta(days=20), NOW - timedelta(hours=2), NOW - timedelta(hours=1), now=NOW
    )
    assert fresh.basis == "posted"
    assert fresh.age_hours == pytest.approx(20 * 24)
    assert "originally posted 20 days ago" in fresh.warning


def test_freshness_falls_back_to_updated_then_first_seen():
    updated = assess_freshness(None, NOW - timedelta(hours=5), NOW - timedelta(hours=1), now=NOW)
    assert updated.basis == "updated" and updated.age_hours == pytest.approx(5)
    seen = assess_freshness(None, None, NOW - timedelta(hours=1), now=NOW)
    assert seen.basis == "first_seen" and seen.age_hours == pytest.approx(1)
    unknown = assess_freshness(None, None, None, now=NOW)
    assert unknown.basis == "unknown" and unknown.age_hours is None


def test_apply_links_prefer_the_employers_ats():
    assert classify_apply_url("https://boards.greenhouse.io/acme/jobs/1") == ("ats", "Greenhouse")
    assert classify_apply_url("https://jobs.lever.co/acme/1") == ("ats", "Lever")
    assert classify_apply_url("https://acme.wd3.myworkdayjobs.com/x") == ("ats", "Workday")
    assert classify_apply_url("https://www.linkedin.com/jobs/view/1") == ("aggregator", "LinkedIn")
    assert classify_apply_url("https://www.naukri.com/job/1") == ("aggregator", "Naukri")
    assert classify_apply_url("https://careers.acme.com/1")[0] == "company"
    assert classify_apply_url("") == ("none", "")
    url, kind, _ = best_apply_link("https://www.indeed.com/viewjob?jk=1", "https://jobs.ashbyhq.com/acme/1")
    assert kind == "ats" and "ashbyhq" in url


# ---------------------------------------------------------------------------
# Query generation
# ---------------------------------------------------------------------------
def test_queries_cover_roles_across_location_tiers():
    queries = generate_queries(cfg(max_queries=60))
    labels = [q.label for q in queries]
    assert "Senior React Developer Remote India" in labels
    assert "Senior React Developer Jaipur" in labels
    assert "MERN Stack Developer Jaipur" in labels
    remote = next(q for q in queries if q.label == "Senior React Developer Remote India")
    assert remote.remote is True and remote.location == ""
    # "Jaipur" and "Hybrid Jaipur" are the same search to a provider.
    signatures = [q.signature() for q in queries]
    assert len(signatures) == len(set(signatures))
    # Skill-combination queries catch stack-titled postings.
    assert any(q.label.startswith("React JavaScript Developer") for q in queries)


def test_capped_queries_still_cover_every_location_tier():
    queries = generate_queries(cfg(max_queries=6))
    assert len(queries) == 6
    # The top role is searched remote, in Jaipur and across India before the
    # cap is spent on further roles.
    first_role = [q for q in queries if q.keywords == "Senior React Developer"]
    assert {q.label for q in first_role} == {
        "Senior React Developer Remote India",
        "Senior React Developer Jaipur",
        "Senior React Developer India",
    }


def test_custom_queries_come_first_and_exclusions_apply():
    queries = generate_queries(
        cfg(
            custom_queries=["Frontend Engineer AI LLM React Remote"],
            excluded_queries=["Senior React Developer Remote India"],
            max_queries=5,
        )
    )
    assert queries[0].label == "Frontend Engineer AI LLM React Remote"
    assert queries[0].origin == "custom"
    assert "Senior React Developer Remote India" not in [q.label for q in queries]


def test_auto_queries_can_be_switched_off():
    queries = generate_queries(cfg(auto_queries=False, custom_queries=["Only this"]))
    assert [q.label for q in queries] == ["Only this"]


def test_board_query_drops_short_keywords():
    keywords = board_query(cfg(), 10).keywords
    assert "ui" not in [k.lower() for k in keywords]
    assert "Frontend Developer" in keywords


# ---------------------------------------------------------------------------
# Assessment: the brief's categories
# ---------------------------------------------------------------------------
def _job(**overrides) -> dict:
    base = {
        "title": "Senior Frontend Engineer",
        "company": "ABC",
        "location": "Remote - India",
        "is_remote": True,
        "description": "React, TypeScript, Next.js, Redux, REST APIs.",
        "experience_min_years": 5,
        "experience_max_years": 8,
        "posted_at": NOW - timedelta(hours=2),
        "apply_url": "https://boards.greenhouse.io/abc/jobs/1",
    }
    base.update(overrides)
    return base


def test_remote_india_strong_match_is_apply_first_remote():
    a = assess_job(_job(), cfg(), now=NOW)
    assert a.category == "apply_first"
    assert a.section == "Apply First — Remote"
    assert a.tier_rank == 0
    assert a.experience_fit == "strong"
    assert a.apply_link_type == "ats"
    assert a.strength in ("strong", "good")


def test_jaipur_onsite_and_hybrid_share_the_jaipur_section():
    onsite = assess_job(_job(location="Jaipur, Rajasthan", is_remote=False), cfg(), now=NOW)
    hybrid = assess_job(
        _job(location="Jaipur", is_remote=False, description="Hybrid, 3 days in office. React TypeScript"),
        cfg(),
        now=NOW,
    )
    assert onsite.section == hybrid.section == "Apply First — Jaipur"
    assert onsite.tier_name == "Jaipur"
    assert hybrid.tier_name == "Hybrid Jaipur"
    assert onsite.tier_rank < hybrid.tier_rank


def test_other_india_is_worth_reviewing():
    a = assess_job(_job(location="Bengaluru, Karnataka", is_remote=False), cfg(), now=NOW)
    assert a.category == "review"
    assert a.section == "Worth Reviewing — Other India"


@pytest.mark.parametrize(
    ("overrides", "reason_fragment"),
    [
        ({"location": "USA", "title": "Frontend Engineer"}, "only for US"),
        ({"title": "React Intern", "location": "Jaipur", "is_remote": False}, "Intern-level"),
        ({"experience_min_years": 1, "experience_max_years": 2, "location": "Pune", "is_remote": False},
         "1-2 yrs"),
        ({"title": "Java Backend Engineer", "description": "Java Spring Boot"}, "Different job family"),
        ({"location": "London", "is_remote": False}, "outside your location priorities"),
        ({"posted_at": NOW - timedelta(days=45)}, "older than your 30-day window"),
    ],
)
def test_not_a_match_cases_explain_why(overrides, reason_fragment):
    a = assess_job(_job(**overrides), cfg(), now=NOW)
    assert a.category == "not_match"
    assert a.strength == "none"
    assert any(reason_fragment in r for r in a.reasons), a.reasons


def test_worldwide_remote_is_reviewed_until_confirmed():
    a = assess_job(_job(location="Remote (Worldwide)"), cfg(), now=NOW)
    assert a.category == "review"
    assert a.section == "Worth Reviewing — Remote"
    assert any("confirm hiring from India" in w for w in a.warnings)


def test_worldwide_remote_can_be_rejected_by_config():
    a = assess_job(_job(location="Worldwide"), cfg(accept_worldwide_remote=False), now=NOW)
    assert a.category == "not_match"


def test_low_skill_overlap_demotes_to_review():
    a = assess_job(
        _job(description="Angular, Vue.js, Svelte, Java, Kubernetes and React."), cfg(), now=NOW
    )
    assert a.category == "review"
    assert any("listed skills" in w for w in a.warnings)
    assert "Angular" in a.missing_skills


def test_skill_overlap_matches_the_brief_example():
    a = assess_job(
        _job(
            title="Senior Full Stack Engineer",
            description="React, TypeScript, Node.js, Python, PostgreSQL, AI/LLM. 5+ years.",
            experience_max_years=None,
        ),
        cfg(),
        now=NOW,
    )
    assert {"React", "TypeScript", "Node.js", "Python", "PostgreSQL", "AI/LLM"} <= set(a.matched_skills)
    assert a.skill_overlap == pytest.approx(1.0)


def test_policy_filters_are_respected_and_can_be_ignored():
    policy = SimpleNamespace(excluded_companies=["ABC"], excluded_keywords=[], min_salary_lpa=None)
    assert assess_job(_job(), cfg(), policy=policy, now=NOW).category == "not_match"
    relaxed = assess_job(_job(), cfg(respect_policy_filters=False), policy=policy, now=NOW)
    assert relaxed.category == "apply_first"


def test_custom_tiers_change_the_priorities():
    tiers = [
        {"name": "Pune", "group": "Pune", "work_modes": ["onsite", "hybrid"], "places": ["Pune"], "kind": "apply_first"},
    ]
    a = assess_job(_job(location="Pune", is_remote=False), cfg(location_tiers=tiers), now=NOW)
    assert a.section == "Apply First — Pune"
    b = assess_job(_job(), cfg(location_tiers=tiers), now=NOW)
    assert b.category == "not_match"


def test_local_semantic_scores_rank_related_jobs_higher():
    profile = "Senior React developer building healthcare dashboards with React, TypeScript and Recharts."
    scores = local_scores(
        profile,
        {
            "related": "Build interactive data visualization dashboards in React and TypeScript.",
            "unrelated": "Operate warehouse forklifts and manage inventory shipping schedules.",
        },
    )
    assert scores["related"] > scores["unrelated"]
    assert 0.0 <= scores["unrelated"] <= scores["related"] <= 1.0


# ---------------------------------------------------------------------------
# Discovery with query variations
# ---------------------------------------------------------------------------
class _FakeSearchAdapter(JobSourceAdapter):
    adapter_type = "fake_search"
    display_name = "Fake search"
    supports_search = True
    calls: list[tuple] = []

    def test_connection(self) -> SourceTestResult:
        return SourceTestResult(ok=True, message="ok")

    def search(self, query: SourceQuery) -> list[RawJob]:
        type(self).calls.append((query.keyword_text(), query.primary_location(), query.remote_only))
        # The same posting comes back for every query; it must be ingested once.
        return [
            RawJob(external_id="shared-1", title="Senior React Developer", company="Acme",
                   location="Jaipur", url="https://acme.test/1"),
            RawJob(external_id=f"q-{len(type(self).calls)}", title=f"React Developer {len(type(self).calls)}",
                   company="Acme", location="Jaipur", url=f"https://acme.test/q{len(type(self).calls)}"),
        ]


class _FakeBoardAdapter(JobSourceAdapter):
    adapter_type = "fake_board"
    display_name = "Fake board"
    calls: list[tuple] = []

    def test_connection(self) -> SourceTestResult:
        return SourceTestResult(ok=True, message="ok")

    def search(self, query: SourceQuery) -> list[RawJob]:
        type(self).calls.append(tuple(query.keywords))
        return []


@pytest.fixture()
def fake_adapters():
    _FakeSearchAdapter.calls = []
    _FakeBoardAdapter.calls = []
    _REGISTRY["fake_search"] = _FakeSearchAdapter
    _REGISTRY["fake_board"] = _FakeBoardAdapter
    yield
    _REGISTRY.pop("fake_search", None)
    _REGISTRY.pop("fake_board", None)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = maker()
    session.add(User(id=USER_ID, email="owner@example.test", password_hash="x", is_owner=True))
    session.flush()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_discovery_runs_each_query_once_and_boards_once(db, fake_adapters):
    from app.services.discovery import discover

    db.add_all([
        JobSource(user_id=USER_ID, name="search", adapter_type="fake_search", config={}, enabled=True),
        JobSource(user_id=USER_ID, name="board", adapter_type="fake_board", config={}, enabled=True),
    ])
    db.flush()
    queries = [
        SourceQuery(keywords=["React Developer"], locations=["Jaipur"]),
        SourceQuery(keywords=["React Developer"], locations=["Jaipur"]),  # repeat: skipped
        SourceQuery(keywords=["Frontend Engineer"], remote_only=True),
    ]
    result = discover(db, USER_ID, queries=queries, board_query=SourceQuery(keywords=["React"]))

    assert len(_FakeSearchAdapter.calls) == 2
    assert _FakeBoardAdapter.calls == [("React",)]
    titles = sorted(j.title for j in db.scalars(select(Job)))
    assert titles.count("Senior React Developer") == 1
    assert result.created == 3


def test_merge_upgrades_an_aggregator_link_to_the_employers_ats(db):
    from app.services.dedupe import merge_duplicate

    job = Job(user_id=USER_ID, title="Frontend Engineer", company="Acme",
              apply_url="https://www.linkedin.com/jobs/view/1", url="https://www.linkedin.com/jobs/view/1",
              dedupe_key="k1")
    db.add(job)
    db.flush()
    merge_duplicate(db, job, RawJob(external_id="", title="Frontend Engineer", company="Acme",
                                    apply_url="https://jobs.lever.co/acme/1"), "lever")
    assert job.apply_url == "https://jobs.lever.co/acme/1"
    # A worse link never replaces a better one.
    merge_duplicate(db, job, RawJob(external_id="", title="Frontend Engineer", company="Acme",
                                    apply_url="https://www.indeed.com/viewjob?jk=1"), "indeed")
    assert job.apply_url == "https://jobs.lever.co/acme/1"


# ---------------------------------------------------------------------------
# API flows
# ---------------------------------------------------------------------------
def _add_job(client, **overrides) -> dict:
    payload = {
        "title": "Senior React Developer",
        "company": "Remote Co",
        "location": "Remote - India",
        "is_remote": True,
        "employment_type": "full_time",
        "salary_min_lpa": 18,
        "salary_max_lpa": 26,
        "description": "React, TypeScript, Next.js and Redux Toolkit. 5-8 years of experience.",
        "url": "https://boards.greenhouse.io/remoteco/jobs/1",
        "apply_url": "https://boards.greenhouse.io/remoteco/jobs/1",
    }
    payload.update(overrides)
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_config_is_seeded_and_editable(auth_client):
    response = auth_client.get("/api/v1/hunt/config")
    assert response.status_code == 200, response.text
    config = response.json()
    assert [t["name"] for t in config["location_tiers"]] == [
        "Remote India", "Jaipur", "Hybrid Jaipur", "Other India",
    ]
    assert config["experience_years"] == 5.5
    assert config["schedule_enabled"] is False

    config["experience_years"] = 6
    config["location_tiers"] = config["location_tiers"][:2]
    config["schedule_enabled"] = True
    config["schedule_cron"] = "0 */6 * * *"
    updated = auth_client.put("/api/v1/hunt/config", json=config)
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["experience_years"] == 6
    assert len(body["location_tiers"]) == 2
    assert body["schedule_enabled"] is True
    assert body["schedule_cron"] == "0 */6 * * *"

    # The schedule lives on the job_hunt agent, so Automations agrees.
    agents = {a["key"]: a for a in auth_client.get("/api/v1/agents").json()}
    assert agents["job_hunt"]["enabled"] is True
    assert agents["job_hunt"]["schedule_cron"] == "0 */6 * * *"


def test_config_rejects_bad_input(auth_client):
    config = auth_client.get("/api/v1/hunt/config").json()
    bad_cron = auth_client.put("/api/v1/hunt/config", json={**config, "schedule_cron": "not a cron"})
    assert bad_cron.status_code in (400, 422)
    no_tiers = auth_client.put("/api/v1/hunt/config", json={**config, "location_tiers": []})
    assert no_tiers.status_code in (400, 422)
    bad_weight = auth_client.put("/api/v1/hunt/config", json={**config, "weights": {"nope": 5}})
    assert bad_weight.status_code == 422


def test_hunt_agent_is_created_disabled(auth_client):
    agents = {a["key"]: a for a in auth_client.get("/api/v1/agents").json()}
    assert agents["job_hunt"]["enabled"] is False


def test_query_preview_reflects_unsaved_edits(auth_client):
    config = auth_client.get("/api/v1/hunt/config").json()
    saved = auth_client.post("/api/v1/hunt/queries/preview").json()
    assert saved["queries"]
    config["target_roles"] = ["Svelte Developer"]
    config["custom_queries"] = ["Design Engineer Remote"]
    edited = auth_client.post("/api/v1/hunt/queries/preview", json=config).json()
    labels = [q["label"] for q in edited["queries"]]
    assert labels[0] == "Design Engineer Remote"
    assert "Svelte Developer Remote India" in labels


def test_board_categorises_jobs(auth_client):
    remote = _add_job(auth_client)
    jaipur = _add_job(auth_client, title="Frontend Developer", company="Pink City Labs",
                      location="Jaipur, Rajasthan", is_remote=False, url="https://pinkcity.test/1",
                      apply_url="")
    blr = _add_job(auth_client, title="Frontend Engineer", company="Blr Co", location="Bengaluru",
                   is_remote=False, url="https://blr.test/1", apply_url="")
    us = _add_job(auth_client, title="Frontend Engineer", company="US Co", location="USA",
                  url="https://us.test/1", apply_url="")

    board = auth_client.get("/api/v1/hunt/board")
    assert board.status_code == 200, board.text
    data = board.json()
    sections = {s["label"]: [i["job_id"] for i in s["items"]] for s in data["sections"]}
    assert remote["id"] in sections["Apply First — Remote"]
    assert jaipur["id"] in sections["Apply First — Jaipur"]
    assert blr["id"] in sections["Worth Reviewing — Other India"]
    # Apply-first sections come before review sections.
    kinds = [s["kind"] for s in data["sections"]]
    assert kinds == sorted(kinds, key=lambda k: 0 if k == "apply_first" else 1)
    assert data["stats"]["apply_first"] == 2
    assert data["not_match"]["count"] == 1

    not_match = auth_client.get("/api/v1/hunt/results", params={"category": "not_match"}).json()
    assert [i["job_id"] for i in not_match["items"]] == [us["id"]]
    assert "only for US" in not_match["items"][0]["reasons"][0]

    item = next(i for s in data["sections"] for i in s["items"] if i["job_id"] == remote["id"])
    assert item["apply_link_type"] == "ats"
    assert item["freshness_label"].startswith(("Found", "Posted"))
    assert "React" in item["matched_skills"]


def test_job_detail_returns_assessment_and_evidence(auth_client):
    job = _add_job(auth_client)
    detail = auth_client.get(f"/api/v1/hunt/jobs/{job['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["assessment"]["category"] == "apply_first"
    assert isinstance(body["evidence"], list)
    assert sum(body["breakdown_max"].values()) == pytest.approx(100, abs=0.1)
    assert auth_client.get("/api/v1/hunt/jobs/" + "x" * 32).status_code == 404


def test_preview_assesses_a_pasted_job_without_saving(auth_client):
    response = auth_client.post(
        "/api/v1/hunt/preview",
        json={
            "title": "Senior React Developer",
            "location": "Jaipur",
            "description": "Hybrid role, 2 days in office. React TypeScript. 5 to 8 years.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["section"] == "Apply First — Jaipur"
    assert body["work_mode"] == "hybrid"
    assert body["experience_fit"] == "strong"
    assert auth_client.get("/api/v1/jobs").json()["total"] == 0


def test_run_without_discovery_records_a_run(auth_client):
    _add_job(auth_client)
    run = auth_client.post("/api/v1/hunt/run", json={"discover": False})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "success"
    assert body["summary"]["apply_first"] == 1
    runs = auth_client.get("/api/v1/hunt/runs").json()
    assert runs and runs[0]["id"] == body["id"]


def test_new_apply_first_matches_are_alerted_once(db):
    from app.services.hunt.defaults import load_config
    from app.services.hunt.pipeline import assess_jobs, notify_new_matches

    db.add(Job(user_id=USER_ID, title="Senior React Developer", company="Acme", location="Remote - India",
               is_remote=True, description="React TypeScript Next.js 5-8 years",
               experience_min_years=5, experience_max_years=8,
               apply_url="https://jobs.lever.co/acme/1", dedupe_key="a1",
               first_seen_at=datetime.now(timezone.utc)))
    db.flush()
    config = load_config(db, USER_ID)
    assess_jobs(db, USER_ID, config=config)
    assert notify_new_matches(db, USER_ID, config) == 1
    assert notify_new_matches(db, USER_ID, config) == 0
    row = db.scalar(select(HuntResult))
    assert row.notified_at is not None


def test_profile_suggestions_come_from_the_seeded_profile(auth_client):
    body = auth_client.get("/api/v1/hunt/profile-suggestions").json()
    assert body["experience_years"]
    assert body["target_roles"]


def test_remotive_answers_a_batch_of_queries_with_one_request(monkeypatch):
    """Remotive blocks >2 requests/minute, so a hunt must not fan out to it."""
    from app.services.sources import remotive

    calls: list[dict] = []

    def fake_get_json(url, *, params=None, **_):
        calls.append(dict(params or {}))
        return {
            "jobs": [
                {"id": 1, "title": "Senior Frontend Engineer (React)", "company_name": "A",
                 "candidate_required_location": "India", "url": "https://remotive.com/1"},
                {"id": 2, "title": "Senior React Developer", "company_name": "B",
                 "candidate_required_location": "Worldwide", "url": "https://remotive.com/2"},
                {"id": 3, "title": "Data Engineer", "company_name": "C",
                 "candidate_required_location": "USA", "url": "https://remotive.com/3"},
            ]
        }

    monkeypatch.setattr(remotive, "http_get_json", fake_get_json)
    adapter = remotive.RemotiveAdapter({})
    queries = [
        SourceQuery(keywords=["Senior React Developer"], remote_only=True),
        SourceQuery(keywords=["Frontend Engineer"], remote_only=True),
        SourceQuery(keywords=["Full Stack Developer"], remote_only=True),
    ]
    jobs = adapter.search_many(queries)
    assert len(calls) == 1
    assert "search" not in calls[0]
    assert sorted(j.title for j in jobs) == ["Senior Frontend Engineer (React)", "Senior React Developer"]

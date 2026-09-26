"""End-to-end API flows through the real FastAPI app and an in-memory DB.

These exercise the paths a user actually takes: sign in, edit preferences,
ingest a job, queue and submit an application, manage the answer bank, and the
security-relevant edges (auth required, LinkedIn stays manual, upload
validation, secrets never returned in plaintext).
"""
from __future__ import annotations

import io

from tests.conftest import TEST_PASSWORD


def test_health_is_public():
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_protected_route_requires_auth(client):
    response = client.get("/api/v1/profile")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_login_wrong_password_is_generic(client, owner):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert "incorrect" in response.json()["error"]["message"].lower()


def test_login_then_me(client, owner):
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"


def test_refresh_cookie_is_httponly(client, owner):
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": TEST_PASSWORD},
    )
    cookie = login.headers.get("set-cookie", "")
    assert "refresh_token=" in cookie
    assert "httponly" in cookie.lower()


def test_seeded_preferences_are_visible(auth_client):
    response = auth_client.get("/api/v1/preferences")
    assert response.status_code == 200
    data = response.json()
    assert "React" in data["must_have_keywords"]
    assert data["daily_application_cap"] == 8


def test_update_preferences_persists(auth_client):
    response = auth_client.put(
        "/api/v1/preferences",
        json={
            "target_roles": ["Staff Engineer"],
            "min_salary_lpa": 20,
            "target_salary_lpa": 25,
            "must_have_keywords": ["Python"],
            "review_threshold": 60,
            "high_priority_threshold": 80,
            "daily_application_cap": 3,
        },
    )
    assert response.status_code == 200
    assert response.json()["target_roles"] == ["Staff Engineer"]

    again = auth_client.get("/api/v1/preferences")
    assert again.json()["min_salary_lpa"] == 20


def test_invalid_preferences_range_is_rejected(auth_client):
    response = auth_client.put(
        "/api/v1/preferences",
        json={"review_threshold": 90, "high_priority_threshold": 50},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_manual_job_is_scored_on_creation(sample_job):
    assert sample_job["match"] is not None
    assert sample_job["match"]["decision"] in ("HIGH_PRIORITY", "REVIEW", "REJECT")
    assert sample_job["match"]["score"] >= 0


def test_published_application_email_is_extracted_and_returned(auth_client):
    """Regression: the field was stored but missing from the API response."""
    response = auth_client.post(
        "/api/v1/jobs",
        json={
            "title": "React Developer",
            "company": "MailApply Co",
            "location": "Remote",
            "is_remote": True,
            "employment_type": "full_time",
            "industry": "software",
            "salary_min_lpa": 18,
            "description": (
                "React and TypeScript role. Send your resume to careers@example.com "
                "to apply. 4+ years experience."
            ),
        },
    )
    assert response.status_code == 201
    assert response.json()["application_email"] == "careers@example.com"

    listed = auth_client.get("/api/v1/jobs").json()
    match = next(j for j in listed["items"] if j["company"] == "MailApply Co")
    assert match["application_email"] == "careers@example.com"


def test_job_without_a_published_address_has_an_empty_email(auth_client, sample_job):
    assert sample_job["application_email"] == ""


def test_job_list_includes_match(auth_client, sample_job):
    response = auth_client.get("/api/v1/jobs")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    found = next(j for j in body["items"] if j["id"] == sample_job["id"])
    assert found["match"]["decision"] == sample_job["match"]["decision"]


def test_job_detail_has_skills_and_events(auth_client, sample_job):
    response = auth_client.get(f"/api/v1/jobs/{sample_job['id']}")
    assert response.status_code == 200
    body = response.json()
    assert any(s["skill_name"] == "React" for s in body["skills"])
    assert any(e["event_type"] == "created" for e in body["events"])
    assert any(e["event_type"] == "scored" for e in body["events"])


def test_editing_a_scoring_field_rescoring(auth_client, sample_job):
    response = auth_client.patch(
        f"/api/v1/jobs/{sample_job['id']}",
        json={"salary_min_lpa": 2, "salary_max_lpa": 3},
    )
    assert response.status_code == 200
    assert response.json()["match"]["decision"] == "REJECT"


def test_match_preview_does_not_persist(auth_client):
    before = auth_client.get("/api/v1/jobs").json()["total"]
    response = auth_client.post(
        "/api/v1/match/preview",
        json={"title": "React Developer", "description": "React and TypeScript role."},
    )
    assert response.status_code == 200
    after = auth_client.get("/api/v1/jobs").json()["total"]
    assert after == before


def test_application_queue_and_approve(auth_client, sample_job):
    create = auth_client.post("/api/v1/applications", json={"job_id": sample_job["id"]})
    assert create.status_code == 201
    application = create.json()
    assert application["status"] == "pending_review"

    approve = auth_client.post(f"/api/v1/applications/{application['id']}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"


def test_duplicate_application_for_same_job_is_rejected(auth_client, sample_job):
    first = auth_client.post("/api/v1/applications", json={"job_id": sample_job["id"]})
    assert first.status_code == 201

    second = auth_client.post("/api/v1/applications", json={"job_id": sample_job["id"]})
    assert second.status_code == 409


def test_submit_without_approval_is_blocked(auth_client, sample_job):
    create = auth_client.post("/api/v1/applications", json={"job_id": sample_job["id"]})
    application_id = create.json()["id"]

    submit = auth_client.post(f"/api/v1/applications/{application_id}/submit", json={})
    assert submit.status_code == 403
    assert submit.json()["error"]["code"] == "approval_required"


def test_linkedin_submission_requires_manual_confirmation(auth_client, sample_job):
    create = auth_client.post(
        "/api/v1/applications",
        json={"job_id": sample_job["id"], "channel": "linkedin"},
    )
    application_id = create.json()["id"]
    auth_client.post(f"/api/v1/applications/{application_id}/approve")

    blocked = auth_client.post(f"/api/v1/applications/{application_id}/submit", json={})
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "linkedin_manual_only"

    confirmed = auth_client.post(
        f"/api/v1/applications/{application_id}/submit",
        json={"confirm_manual_submission": True, "reference": "Applied via LinkedIn UI"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "submitted"


def test_daily_application_cap_blocks_further_submissions(auth_client, sample_job):
    auth_client.put("/api/v1/preferences", json={"daily_application_cap": 0})

    create = auth_client.post("/api/v1/applications", json={"job_id": sample_job["id"]})
    application_id = create.json()["id"]
    auth_client.post(f"/api/v1/applications/{application_id}/approve")

    submit = auth_client.post(
        f"/api/v1/applications/{application_id}/submit",
        json={"confirm_manual_submission": True},
    )
    assert submit.status_code == 403
    assert submit.json()["error"]["code"] == "daily_cap_reached"


def test_failed_email_submission_persists_the_failure(auth_client):
    """A bounced send must leave a durable record, not vanish on rollback.

    The route raises to signal the error, and a raised error rolls the
    request's session back — so this asserts the failure survives that.
    """
    created = auth_client.post(
        "/api/v1/jobs",
        json={
            "title": "React Developer",
            "company": "Bounce Co",
            "location": "Remote",
            "is_remote": True,
            "employment_type": "full_time",
            "industry": "software",
            "salary_min_lpa": 18,
            "description": "React TypeScript role. Send your resume to careers@bounce.example.",
        },
    ).json()
    assert created["application_email"] == "careers@bounce.example"

    auth_client.put(
        "/api/v1/preferences",
        json={"approval_required": False, "auto_submit_enabled": True, "daily_application_cap": 8},
    )

    application = auth_client.post(
        "/api/v1/applications", json={"job_id": created["id"], "channel": "email"}
    ).json()

    # SMTP is unconfigured in tests, so the send cannot succeed.
    response = auth_client.post(f"/api/v1/applications/{application['id']}/submit", json={})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "submission_failed"

    after = auth_client.get(f"/api/v1/applications/{application['id']}").json()
    assert after["status"] == "failed"
    assert after["submitted_at"] is None
    assert "not configured" in after["failure_reason"].lower()


def test_answer_bank_crud(auth_client):
    create = auth_client.post(
        "/api/v1/answers",
        json={"question": "Do you know Rust?", "answer": "No, but I am learning it."},
    )
    assert create.status_code == 201
    answer_id = create.json()["id"]

    listed = auth_client.get("/api/v1/answers")
    assert any(a["id"] == answer_id for a in listed.json())

    deleted = auth_client.delete(f"/api/v1/answers/{answer_id}")
    assert deleted.status_code == 200


def test_answer_resolution_prefers_exact_match(auth_client):
    response = auth_client.post(
        "/api/v1/answers/resolve",
        json={"question": "How many years of React experience do you have?", "allow_ai": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resolved_from"] in ("answer_bank", "normalized_key")
    assert "4.5" in body["answer"]


def test_answer_resolution_with_no_match_and_no_ai(auth_client):
    response = auth_client.post(
        "/api/v1/answers/resolve",
        json={"question": "What is your favorite color?", "allow_ai": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resolved_from"] == "none"
    assert body["state"] == "needs_review"


def test_resume_upload_rejects_non_pdf_docx(auth_client):
    resumes = auth_client.get("/api/v1/resumes").json()
    resume_id = resumes[0]["id"]

    response = auth_client.post(
        f"/api/v1/resumes/{resume_id}/versions",
        files={"file": ("resume.txt", io.BytesIO(b"just some text"), "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_type"


def test_resume_upload_accepts_a_real_pdf(auth_client):
    resumes = auth_client.get("/api/v1/resumes").json()
    resume_id = resumes[0]["id"]

    minimal_pdf = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/Resources<<>>/MediaBox[0 0 200 200]"
        b"/Contents 4 0 R>>endobj\n"
        b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 100 Td (React Developer) Tj ET\n"
        b"endstream endobj\ntrailer<</Root 1 0 R>>"
    )
    response = auth_client.post(
        f"/api/v1/resumes/{resume_id}/versions",
        files={"file": ("resume.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "resume.pdf"
    assert body["parse_status"] in ("parsed", "failed")


def test_integrations_never_return_plaintext(auth_client):
    set_response = auth_client.put(
        "/api/v1/integrations/openai_api_key",
        json={"value": "not-a-real-key-value-for-tests-only"},
    )
    assert set_response.status_code == 200
    body = set_response.json()
    assert "not-a-real-key-value-for-tests-only" not in str(body)
    # Only the last four characters may ever be shown.
    assert body["masked_value"].endswith("only")
    assert body["masked_value"].startswith("*")
    assert body["connected"] is True

    listed = auth_client.get("/api/v1/integrations").json()
    dump = str(listed)
    assert "not-a-real-key-value-for-tests-only" not in dump


def test_rules_crud_and_test(auth_client, sample_job):
    create = auth_client.post(
        "/api/v1/rules",
        json={
            "name": "Must mention Jest",
            "field": "description",
            "operator": "contains",
            "value": ["jest"],
            "is_hard": True,
            "weight": 0,
            "explanation": "We only want teams that test.",
        },
    )
    assert create.status_code == 201
    rule_id = create.json()["id"]

    test_response = auth_client.post(
        f"/api/v1/rules/{rule_id}/test", json={"job_id": sample_job["id"]}
    )
    assert test_response.status_code == 200
    assert test_response.json()["passed"] is True

    deleted = auth_client.delete(f"/api/v1/rules/{rule_id}")
    assert deleted.status_code == 200


def test_rescore_all_updates_every_job(auth_client, sample_job):
    auth_client.put("/api/v1/preferences", json={"must_have_keywords": ["Rust"]})
    response = auth_client.post("/api/v1/jobs/rescore-all")
    assert response.status_code == 200
    body = response.json()
    assert body["rescored"] >= 1
    assert body["rejected"] >= 1


def test_dashboard_reflects_state(auth_client, sample_job):
    response = auth_client.get("/api/v1/dashboard")
    assert response.status_code == 200
    counts = response.json()["counts"]
    assert counts["total_jobs"] >= 1


def test_audit_log_records_actions(auth_client, sample_job):
    response = auth_client.get("/api/v1/audit")
    assert response.status_code == 200
    actions = [row["action"] for row in response.json()["items"]]
    assert "job.create" in actions


def test_source_adapters_are_listed(auth_client):
    response = auth_client.get("/api/v1/sources/adapters")
    assert response.status_code == 200
    types = [a["adapter_type"] for a in response.json()]
    assert "remotive" in types
    assert "manual" in types


def test_logout_revokes_session(client, owner):
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": TEST_PASSWORD},
    )
    token = login.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200

    refresh = client.post("/api/v1/auth/refresh")
    assert refresh.status_code == 401

# API Contract — v1

Base URL: `${NEXT_PUBLIC_API_URL}` (default `http://localhost:8000`)
All application routes are prefixed `/api/v1` and require authentication unless marked **public**.

## Conventions

- **Auth:** `Authorization: Bearer <access_token>`. The refresh token is an httpOnly cookie
  (`refresh_token`) set by the server; the browser never reads it.
- **Errors:** every non-2xx response is
  `{"error": {"code": "string", "message": "human readable", "details": {...}}}`.
- **Lists:** paginated endpoints return
  `{"items": [...], "total": int, "page": int, "page_size": int, "pages": int}`.
- **Timestamps:** ISO-8601 UTC strings.
- **IDs:** 32-character hex strings.

---

## Health (public)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | Liveness. `{status, version, environment}` |
| GET | `/health/ready` | Readiness: checks DB connectivity. 503 when not ready. |

## Auth

| Method | Path | Body / Notes |
| --- | --- | --- |
| POST | `/api/v1/auth/login` | **public** `{email, password}` → `{access_token, token_type, expires_in, user}` |
| POST | `/api/v1/auth/refresh` | **public** (cookie) → new access token |
| POST | `/api/v1/auth/logout` | Revokes the current session |
| GET | `/api/v1/auth/me` | Current user |
| POST | `/api/v1/auth/change-password` | `{current_password, new_password}` |
| GET | `/api/v1/auth/sessions` | Active sessions |
| DELETE | `/api/v1/auth/sessions/{id}` | Revoke one session |

## Profile

| Method | Path |
| --- | --- |
| GET / PUT | `/api/v1/profile` |
| GET / POST | `/api/v1/profile/experiences` |
| PUT / DELETE | `/api/v1/profile/experiences/{id}` |
| GET / POST | `/api/v1/profile/projects` |
| PUT / DELETE | `/api/v1/profile/projects/{id}` |
| GET / POST | `/api/v1/profile/education` |
| PUT / DELETE | `/api/v1/profile/education/{id}` |
| GET / POST | `/api/v1/profile/skills` |
| PUT / DELETE | `/api/v1/profile/skills/{id}` |
| GET / POST | `/api/v1/profile/facts` |
| DELETE | `/api/v1/profile/facts/{id}` |

## Preferences & rules

| Method | Path | Notes |
| --- | --- | --- |
| GET / PUT | `/api/v1/preferences` | Includes `scoring_weights` and thresholds |
| GET / POST | `/api/v1/rules` | Dynamic match rules |
| PUT / DELETE | `/api/v1/rules/{id}` | |
| POST | `/api/v1/rules/{id}/test` | `{job_id}` → evaluation result |
| GET / POST | `/api/v1/saved-searches` | |
| PUT / DELETE | `/api/v1/saved-searches/{id}` | |

## Job sources

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/sources/adapters` | Available adapter types + their config JSON schema |
| GET / POST | `/api/v1/sources` | |
| PUT / DELETE | `/api/v1/sources/{id}` | |
| POST | `/api/v1/sources/{id}/test` | Connection test; updates health |
| POST | `/api/v1/sources/{id}/sync` | Runs discovery for that source |

## Jobs

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/jobs` | Query: `status, decision, q, source_id, min_score, page, page_size, sort` |
| POST | `/api/v1/jobs` | Manual ingest; scores immediately |
| GET | `/api/v1/jobs/{id}` | Full detail incl. current match, skills, events |
| PATCH / DELETE | `/api/v1/jobs/{id}` | |
| POST | `/api/v1/jobs/{id}/rescore` | |
| POST | `/api/v1/jobs/rescore-all` | |
| GET | `/api/v1/jobs/{id}/events` | Audit timeline |
| POST | `/api/v1/jobs/discover` | `{source_ids?, saved_search_id?}` → run discovery |
| POST | `/api/v1/jobs/{id}/ai-review` | AI second opinion |
| POST | `/api/v1/jobs/{id}/cover-letter` | |
| POST | `/api/v1/jobs/{id}/resume-advice` | |
| POST | `/api/v1/match/preview` | Score arbitrary text without storing |

## Resumes

| Method | Path | Notes |
| --- | --- | --- |
| GET / POST | `/api/v1/resumes` | |
| GET / PUT / DELETE | `/api/v1/resumes/{id}` | |
| POST | `/api/v1/resumes/{id}/default` | Make default |
| GET | `/api/v1/resumes/{id}/versions` | |
| POST | `/api/v1/resumes/{id}/versions` | multipart upload (`file`) |
| GET | `/api/v1/resumes/versions/{vid}` | Includes extracted text + sections |
| GET | `/api/v1/resumes/versions/{vid}/download` | Streams the file |
| DELETE | `/api/v1/resumes/versions/{vid}` | |
| POST | `/api/v1/resumes/{id}/tailor` | `{job_id}` → tailored draft + evidence + diff |

## Answer bank

| Method | Path | Notes |
| --- | --- | --- |
| GET / POST | `/api/v1/answers` | |
| PUT / DELETE | `/api/v1/answers/{id}` | |
| POST | `/api/v1/answers/resolve` | `{question, job_id?}` → `{answer, state, confidence, resolved_from}` |
| POST | `/api/v1/answers/draft` | AI draft grounded in the bank |

## Applications

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/applications` | Query: `status, q, page, page_size` |
| POST | `/api/v1/applications` | `{job_id, resume_version_id?, channel}` |
| GET / PATCH | `/api/v1/applications/{id}` | |
| POST | `/api/v1/applications/{id}/approve` | |
| POST | `/api/v1/applications/{id}/reject` | `{reason}` |
| POST | `/api/v1/applications/{id}/prepare` | Generates assets + resolves answers |
| POST | `/api/v1/applications/{id}/submit` | See **Submission semantics** below |
| POST | `/api/v1/applications/{id}/status` | `{status, reason}` |
| GET | `/api/v1/applications/{id}/history` | |
| POST | `/api/v1/applications/{id}/answers` | Upsert an answer |
| POST | `/api/v1/applications/{id}/followups` | `{due_date, kind, note}` |
| GET | `/api/v1/followups` | Query: `due_before, include_completed` |
| POST | `/api/v1/followups/{id}/complete` | |

### Submission semantics

`POST /api/v1/applications/{id}/submit` takes
`{confirm_manual_submission: bool, reference?: string}`.

| `confirm_manual_submission` | Behaviour |
| --- | --- |
| `false` | **The agent sends it.** Only the `email` channel supports this, and only when the job has an `application_email` the employer published. Any other channel is refused. |
| `true` | **Records a submission the user made themselves.** Nothing is sent. This is the only option for `linkedin`, `ats` and `company_portal`. |

Refusals return 403 with a specific `error.code`:

| Code | Meaning |
| --- | --- |
| `approval_required` | Still pending review. |
| `daily_cap_reached` | The configured daily application cap is used up. A cap of `0` means "send nothing today" and is enforced, not treated as unlimited. |
| `linkedin_manual_only` | LinkedIn is never automated. |
| `portal_manual_only` | Company portal forms are never driven automatically. |
| `no_authorized_integration` | No authorized ATS integration is configured. |
| `no_application_email` | The email lane was chosen but the posting published no address. |

A delivery failure returns **502 `submission_failed`**. The application is left in
`failed` with `failure_reason` populated and a status-history entry recorded — that
record is committed even though the request returns an error, so a bounced send is
always auditable and can be retried (`failed` → `approved`).

## Notifications

| Method | Path |
| --- | --- |
| GET | `/api/v1/notifications/channels` |
| PUT | `/api/v1/notifications/channels/{channel_type}` |
| POST | `/api/v1/notifications/channels/{channel_type}/test` |
| GET / PUT | `/api/v1/notifications/preferences` |
| GET | `/api/v1/notifications/events` |

## Integrations (encrypted credentials)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/integrations` | Masked values + connection status only |
| PUT | `/api/v1/integrations/{key}` | `{value}` — stores encrypted |
| POST | `/api/v1/integrations/{key}/test` | |
| DELETE | `/api/v1/integrations/{key}` | Disconnect |

## Automation

| Method | Path |
| --- | --- |
| GET | `/api/v1/agents` |
| PUT | `/api/v1/agents/{key}` |
| POST | `/api/v1/agents/{key}/run` |
| GET | `/api/v1/agents/runs` |
| GET | `/api/v1/agents/runs/{id}` |
| GET | `/api/v1/schedules` |
| PUT | `/api/v1/schedules/{key}` |
| POST | `/api/v1/schedules/{key}/run-now` |

## Dashboard, analytics, audit, system

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/dashboard` | All overview widgets in one payload |
| GET | `/api/v1/analytics` | Query: `days` |
| GET | `/api/v1/ai/status` | `{enabled, model, budget_usd, spent_this_month_usd}` |
| GET | `/api/v1/ai/usage` | Query: `days` |
| GET | `/api/v1/audit` | Query: `action, entity_type, page, page_size` |
| GET / PUT | `/api/v1/system/settings` | Feature flags |
| GET | `/api/v1/system/export` | Full JSON export of the user's data |

---

## Key response shapes

```jsonc
// Job (list item)
{
  "id": "…", "title": "…", "company": "…", "location": "…", "is_remote": true,
  "salary_min_lpa": 14, "salary_max_lpa": 18, "employment_type": "full_time",
  "industry": "software", "source_name": "remotive", "url": "…", "status": "new",
  "posted_at": "…", "created_at": "…",
  "match": {
    "score": 87.5, "decision": "HIGH_PRIORITY",
    "deterministic_score": 84.0, "semantic_score": null,
    "breakdown": {"must_have_skills": 25.0, "role_fit": 18.0},
    "hard_fail_reasons": [], "matched_skills": ["React"], "missing_skills": ["GraphQL"],
    "positive_signals": ["Remote"], "explanation": "…",
    "recommended_resume_id": "…", "recommendation_reason": "…"
  }
}

// Dashboard
{
  "counts": {"new_jobs": 0, "high_match": 0, "review": 0, "rejected": 0,
             "application_ready": 0, "pending_approval": 0, "submitted": 0,
             "interviews": 0, "offers": 0, "followups_due": 0},
  "daily_run": {"last_run_at": null, "status": "", "next_run_at": null},
  "integration_health": [{"name": "remotive", "health": "healthy", "last_success_at": null}],
  "ai_usage": {"requests_today": 0, "tokens_today": 0,
               "estimated_cost_month_usd": 0.0, "budget_usd": 25.0},
  "recent_activity": [{"created_at": "…", "action": "…", "summary": "…"}],
  "application_cap": {"used_today": 0, "cap": 8}
}

// Resolved answer
{"question": "…", "answer": "…", "state": "verified|inferred|needs_review",
 "confidence": 0.0, "resolved_from": "answer_bank|override|ai|none",
 "answer_bank_id": "…", "evidence_ids": []}
```

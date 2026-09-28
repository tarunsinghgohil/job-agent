# API Contracts

## Profile
- `GET /api/profile`
- `PUT /api/profile`

## Jobs
- `GET /api/jobs`
- `POST /api/jobs/ingest`
- `GET /api/jobs/{id}`
- `POST /api/jobs/{id}/score`

## Job Hunt (`/api/v1/hunt`)
- `GET /hunt/config`, `PUT /hunt/config` (saves, applies the schedule, re-ranks every job), `POST /hunt/config/reset`
- `GET /hunt/profile-suggestions`
- `POST /hunt/queries/preview` (optional unsaved config body)
- `POST /hunt/run` `{discover: bool}`: runs the `job_hunt` agent and returns the run
- `POST /hunt/assess`: re-rank without searching
- `GET /hunt/board?q=&fresh_within_hours=&limit_per_section=`: stats, ordered sections, not-a-match summary
- `GET /hunt/results?category=apply_first|review|not_match&page=&page_size=`
- `GET /hunt/jobs/{id}`: assessment, resume evidence, per-factor maxima
- `POST /hunt/preview`: assess a pasted job without saving
- `GET /hunt/runs`, `GET /hunt/status`

## Suggestions
- `GET /api/v1/suggest?kind=&q=&limit=`: type-ahead for form fields. Kinds: location, role, skill, title_word, company, industry, employment_type, company_type, keyword, query. Items are `{value, label, hint, source: catalog|yours, exact}`. Static vocabularies live in `services/suggest_data.py`; the user's own profile, preferences, hunt setup and matched jobs rank first.

## Applications
- `GET /api/applications`
- `POST /api/applications`
- `PATCH /api/applications/{id}`
- `POST /api/applications/{id}/prepare`
- `POST /api/applications/{id}/approve`

## Resumes
- `GET /api/resumes`
- `POST /api/resumes`
- `PATCH /api/resumes/{id}`
- `POST /api/resumes/{id}/recommend`

## Settings
- `GET /api/settings/integrations`
- `PUT /api/settings/integrations`
- `GET /api/settings/notifications`
- `PUT /api/settings/notifications`

## Contract rule
API responses should be schema-validated and stable. Provider-specific payloads must not leak into domain APIs.

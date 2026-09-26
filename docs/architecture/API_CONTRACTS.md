# API Contracts

## Profile
- `GET /api/profile`
- `PUT /api/profile`

## Jobs
- `GET /api/jobs`
- `POST /api/jobs/ingest`
- `GET /api/jobs/{id}`
- `POST /api/jobs/{id}/score`

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

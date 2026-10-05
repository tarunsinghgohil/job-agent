# Changelog

## 2026-10-05
- Added `render.yaml` (Render Blueprint: Postgres + API + web). Render's build failed with "open Dockerfile: no such file" because the Dockerfiles live in `backend/` and `frontend/`, not the repo root.
- API listens on `$PORT` when the host sets it (default 8000, so compose is unchanged).
- `postgres://` and `postgresql://` database URLs are rewritten to the psycopg 3 driver.
- New `COOKIE_SAMESITE` setting (default `lax`); set to `none` when the web app and API are on different sites so the refresh cookie is sent.

## 2026-09-27
- Added type-ahead suggestions (`GET /api/v1/suggest`) on every role, location, skill, company, industry, keyword, employment-type and title-word field: Preferences, Resumes, Profile, Add job and the Job Hunt setup. Understands aliases (Bangalore, ReactJS), abbreviations (sr, fe) and typos; Enter on an alias adds the canonical value.
- Added the 3x Job Hunt (`/hunt`): multi-query discovery, ordered location tiers (Remote India → Jaipur → Hybrid Jaipur → Other India by default), experience/skill/freshness/semantic ranking, and an Apply First / Worth Reviewing / Not a Match shortlist. Everything is configurable from the Setup tab. See `docs/product/JOB_HUNT.md`.
- New tables `hunt_configs`, `hunt_results`; new column `jobs.source_updated_at` (migration `b4d8e2f1a9c3`).
- Fixed skill extraction matching inside words ("ts" in "requirements", "git" in "digital", "java" in "javascript"); added MERN/MEAN/PERN expansion and AI/LLM, RAG, Angular, Vue.js and other skills.
- Greenhouse and Ashby no longer store the last-updated time as the posting date.
- Dedupe now upgrades an aggregator apply link to the employer's ATS or careers link when the same job is seen again.
- Remotive answers a batch of hunt queries with a single request.

## 2026-09-15
- Added AI-optimized repository context system.
- Added project/product/architecture/domain/operations/development documentation.
- Seeded current user job preferences and application answer bank.
- Added AI agent instructions and ADRs.

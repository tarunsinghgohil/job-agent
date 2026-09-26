# AI Job Application Agent

> AI-first project navigation: read `AI_CONTEXT.md` first, then `AGENTS.md`, then `docs/README.md`.
> Do not load every documentation file into an AI context window; use the map and task-specific docs.

## Current source of truth
- Product/profile: `docs/product/USER_PROFILE.md`
- Scoring: `docs/product/SCORING_MODEL.md`
- Automation policy: `docs/domain/SOURCE_POLICY.md`
- Architecture: `docs/architecture/SYSTEM_ARCHITECTURE.md`
- Setup: `docs/operations/SETUP.md`

---

# AI Job Application Agent — Tarun Singh Gohil

A personal career automation dashboard built around Tarun's 2026 frontend resume and the job-search rules supplied in this conversation.

## Current build
- Career profile + skills taxonomy seeded from the resume.
- Configurable job preferences and hard/soft matching rules.
- Hybrid-style local scoring engine with React as a hard priority.
- Jobs dashboard with score/decision/breakdown.
- Application queue and tracker.
- Resume library + upload UI.
- Reusable application Answer Bank.
- Notification routing UI for email/Telegram/Slack/WhatsApp targets.
- Settings page for local credentials and integrations.
- Manual job ingestion so the system is useful before a search-provider API is connected.
- Policy-aware LinkedIn approval lane.

## Run locally
1. Install Docker Desktop.
2. Copy `.env.example` to `.env` and optionally add your `OPENAI_API_KEY`.
3. Run: `docker compose up --build`.
4. Open http://localhost:3000
5. API health: http://localhost:8000/health

## Next integration stage
Add one or more approved job-search/ATS provider adapters, then enable the scheduler/agent worker for daily discovery. The matching engine and dashboard are source-agnostic.

## LinkedIn safety
This project intentionally does not include LinkedIn password/session-cookie automation, DOM scraping, CAPTCHA bypass, automated clicks/submissions, or limit bypass. LinkedIn states that unauthorized third-party software/automation and scraping are not allowed; Easy Apply also has daily and speed limits designed to curb bots. Use the approval/manual lane unless LinkedIn provides an officially authorized integration for the use case.

## Your seeded profile
- Roles: Frontend Developer, React JS Developer, Web Developer, UI Developer, Software Developer, Senior Frontend Engineer, React Developer, Frontend Lead, Frontend Engineer, UI Engineer.
- Locations: Jaipur, Remote, Indore; willing to relocate.
- Minimum salary: 14 LPA; target 16+ LPA.
- Experience filter: 3–6 years.
- Immediate joiner / 0 days.
- Full-time; product-based preferred.
- Industries: software, IT, healthcare.
- React.js must-have; resume skills become nice-to-have and future rule candidates.
- High priority >= 90; review >= 78.
- Daily cap default: 8 applications.

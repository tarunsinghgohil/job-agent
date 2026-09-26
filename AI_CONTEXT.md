# AI CONTEXT — AI Job Application Agent

> Read this file first. It is the compact source of truth for AI agents working on this repository.

## Mission
Build a personal AI career agent for Tarun Singh Gohil that discovers relevant jobs, evaluates them against a structured career profile, recommends the best resume, prepares application materials, manages an approval queue, tracks applications, and learns from outcomes.

## Non-goals
- Do not build a covert LinkedIn bot.
- Do not store or request LinkedIn passwords, session cookies, OTPs, or CAPTCHA solutions.
- Do not claim a live integration exists unless an approved API/integration is actually configured and tested.
- Do not auto-submit to sources where automation is unauthorized or unsupported.

## User profile (seed configuration)
- Target roles: Frontend Developer, React JS Developer, Web Developer, UI Developer, Software Developer, similar frontend roles; also relevant Senior Frontend Engineer / Frontend Engineer / Frontend Lead opportunities.
- Locations: Jaipur, Remote, Indore; remote accepted; relocation allowed.
- Minimum salary: 14 LPA. Preferred target: 16+ LPA.
- Experience preference: 3–6 years.
- Availability: immediate joiner; currently not working; 0-day notice.
- Employment: full-time.
- Company preference: product-based preferred; any company allowed unless later restricted.
- Industries: software, IT, healthcare preferred.
- Must-have: React.js and role-appropriate core frontend skills from resume.
- Nice-to-have: other relevant resume skills.
- Must-not-have: none currently.
- Standard answers: React 4.5 years; TypeScript 4 years; current CTC 14 LPA; expected 16+ LPA; notice 0 days/immediate; reason for change: company is closing; relocation: yes; work authorization: yes.

## Resume facts to treat as evidence
- 6+ years professional frontend experience.
- Strong React/React 19, JavaScript, TypeScript, Redux Toolkit, REST APIs, reusable component architecture, responsive UI, performance optimization.
- Recent Lead Developer experience on an AI-powered, multi-tenant HIMS; healthcare enterprise workflows; Django REST integration.
- Enterprise ERP/retail experience including POS, inventory, reporting.
- AI-related frontend work including OCR and voice-enabled workflows.
- Testing/tooling: Vitest, Jest, React Testing Library, Cypress, Playwright.
- Backend/cloud exposure: Python/Django/DRF, Node/Express, PostgreSQL/MySQL/MongoDB/Redis, AWS, Docker, Vercel.
- Do not infer unlisted achievements, compensation, employers, certifications, or years of experience for any skill unless explicitly supported elsewhere in the repo.

## Core product flow
Discover -> Normalize -> Deduplicate -> Qualify -> Match -> Rank -> Select resume -> Tailor materials -> Approval or permitted submission -> Track -> Notify -> Learn.

## Architecture
- Frontend: Next.js + TypeScript.
- Backend: Python + FastAPI.
- Data: PostgreSQL + pgvector.
- Queue/cache: Redis; worker abstraction may use Celery or equivalent.
- AI: provider abstraction; OpenAI is the initial provider.
- Storage: local in development; S3-compatible in production.
- Deploy: Docker-first.

## Agent responsibilities
1. Career/Profile Agent: maintain structured career truth.
2. Job Discovery Agent: ingest jobs from allowed sources.
3. Qualification Agent: hard filters and policy checks.
4. Matching Agent: semantic + structured score, explain score.
5. Resume Agent: recommend and tailor from approved resume variants.
6. Application Agent: create application package and route by source policy.
7. Follow-up Agent: deadlines, reminders, stale applications.
8. Learning Agent: analyze application outcomes and improve ranking recommendations without silently changing hard user rules.

## Matching principles
Hard constraints first: minimum salary when known, role compatibility, location, work type, employment type, must-have skills if configured. Then weighted semantic/skill/domain match. Prefer explainable scores over opaque single-number LLM judgments.

## Source policy
Use official APIs, permitted feeds, public career pages, and user-approved workflows. Treat LinkedIn as a controlled/approval workflow unless an explicitly authorized integration becomes available. Never implement CAPTCHA bypass, session hijacking, stealth scraping, or hidden browser automation.

## Credentials
Secrets belong in environment variables or a secret manager, never in source files or committed markdown. The dashboard may provide fields for configuring providers, but values must be encrypted/secret-managed at rest.

## AI coding rules
- Read `AGENTS.md` and `docs/ai/*` before changing behavior.
- Prefer small, composable services with typed contracts.
- Keep provider-specific code behind adapters.
- Add tests for matching, qualification, parsers, and critical state transitions.
- Update the nearest relevant markdown spec when behavior changes.
- Do not duplicate the entire project context into every prompt; reference this file + the specific task file.

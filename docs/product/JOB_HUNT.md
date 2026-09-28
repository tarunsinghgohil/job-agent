# 3x Job Hunt

A repeatable, personalised job-search pipeline with its own screen at `/hunt`
(Shortlist, Setup, Run history). Everything it uses is typed into the Setup tab.

## Pipeline
`run_hunt` in `backend/app/services/hunt/pipeline.py`:

1. **Profile**: experience years, target roles, skills, related title words and
   excluded seniority levels, all set on the Setup tab. "Import from my profile"
   merges in roles and skills from the career profile and preferences.
2. **Query generation** (`hunt/queries.py`): custom queries first, then each target
   role across every location tier ("Senior React Developer Remote India",
   "… Jaipur", "… India"), plus skill-combination queries. De-duplicated and
   capped at `max_queries`.
3. **Discovery** (`services/discovery.py`, `queries=`): search-capable sources
   (`supports_search`) run each query once per distinct provider signature.
   Board sources such as Greenhouse, Lever and Ashby run once with role keywords.
   Remotive answers the whole batch with **one** request (`search_many`), because
   it blocks more than 2 requests per minute and asks for at most about 4 fetches a day.
4. **Normalize and dedupe**: this is the existing ingest path. On a re-sighting, a
   more direct apply link (ATS, then company, then aggregator) replaces a worse one.
5. **Assessment** (`hunt/assess.py`, pure):
   - work mode (remote, hybrid or on-site) and remote region (country, worldwide or
     foreign), so "Remote India" and "Remote US" are told apart;
   - seniority from the title, and experience fit against the candidate's years
     (5–8 for 5.5 years is strong, 1–2 is under);
   - skill overlap using canonical skills, whole-word matching, and MERN, MEAN
     and PERN expansion;
   - freshness: original posting date first, with a warning when a posting was
     updated long after it was posted; otherwise the source's update time, then
     when the hunt first saw it;
   - semantic similarity: local TF-IDF by default, which is free and offline, or
     opt-in OpenAI embeddings stored on `jobs.embedding`;
   - apply-link quality and any public application email (never guessed).
6. **Location tier**: the first tier in priority order that the job fits.
7. **Score** (0–100): relative weights over location, role, skills, experience,
   freshness, semantic similarity and apply link.
8. **Category**:
   - `apply_first` needs an apply-first tier, a score at or above the threshold,
     skill overlap at or above the minimum, a fitting experience level, a related
     title, and a confirmed region.
   - `review` covers weaker fits and review tiers.
   - `not_match` means at least one hard reason applies: excluded seniority,
     under-level experience, a different job family, a location outside every
     tier, remote only for another region, older than `max_age_days`, or one of
     the Preferences filters (excluded companies and keywords, salary floor).
9. **Alert**: one notification (`high_match_job`) lists apply-first jobs that have
   not been alerted on before.

## Defaults
The seed values come from the 3x Job Hunt brief: 5.5 years, React-centred roles,
and the tiers Remote India, Jaipur, Hybrid Jaipur, Other India. The tier bucket
is apply-first for all but Other India, which is review. Reset restores these.

## Schedule
The hunt is the `job_hunt` agent. It is created **disabled**, and switching on
"Run the hunt automatically" enables it, every 6 hours by default. The schedule
lives on the agent, so the Automations page and the Hunt setup always agree.

## Data
- `hunt_configs`: one row per user.
- `hunt_results`: one row per job, upserted on every assessment. Age is computed
  live from `freshness_at`.
- `jobs.source_updated_at`: the provider's last-modified time, kept apart from
  `posted_at`.

## API
See `architecture/API_CONTRACTS.md`, section Job Hunt.

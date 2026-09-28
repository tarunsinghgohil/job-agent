# Scheduler

## Recurring jobs
- Daily job discovery.
- Incremental refresh for recent sources.
- Re-score new/changed jobs.
- Application follow-up reminders.
- Weekly outcome analytics.
- 3x Job Hunt (`job_hunt` agent): off until enabled on the Job Hunt Setup tab; every 6 hours by default. Remotive is fetched once per run to respect its limits (2/min, ~4/day).

## Idempotency
Every scheduled task needs a deterministic run key or source cursor so retries do not create duplicate jobs/applications.

## User control
Dashboard should allow enable/disable, timezone, run frequency, quiet hours, and notification preferences.

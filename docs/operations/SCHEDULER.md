# Scheduler

## Recurring jobs
- Daily job discovery.
- Incremental refresh for recent sources.
- Re-score new/changed jobs.
- Application follow-up reminders.
- Weekly outcome analytics.

## Idempotency
Every scheduled task needs a deterministic run key or source cursor so retries do not create duplicate jobs/applications.

## User control
Dashboard should allow enable/disable, timezone, run frequency, quiet hours, and notification preferences.

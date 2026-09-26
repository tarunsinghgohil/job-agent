# Error Handling

## Principles
- Fail closed for external submission.
- Retry transient provider/network errors with backoff.
- Do not retry validation or policy failures blindly.
- Persist failed agent runs with a human-readable reason.
- Surface actionable errors in the dashboard.

## Submission rule
If policy, authorization, or integration capability is uncertain, do not submit. Move to `NEEDS_APPROVAL`.

# Observability

Track:
- Agent run ID.
- Job/source identifiers.
- Provider and model.
- Prompt/template version.
- Decision/scoring version.
- Duration.
- Token/cost estimate when available.
- Success/failure.

Never log:
- API keys.
- Passwords.
- OTPs.
- Raw session cookies.
- Sensitive application secrets.

Use structured logs so failed agent runs can be replayed with the same input snapshot where appropriate.

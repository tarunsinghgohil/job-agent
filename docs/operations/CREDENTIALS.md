# Credentials

## Required later
- OpenAI API key for AI operations.
- Job discovery provider API credentials as selected.
- Database/Redis credentials for production.

## Optional
- Notification provider credentials.
- Object-storage credentials.
- OAuth client credentials for integrations that support them.

## Never request/store
- LinkedIn password.
- LinkedIn session cookies.
- One-time passwords.
- CAPTCHA answers.
- Browser profile copies containing active authenticated sessions.

## Storage
Local: `.env` ignored by Git.
Production: encrypted secret manager or platform secrets.
Dashboard secret fields: write encrypted secrets only; never return raw secret values from read endpoints.

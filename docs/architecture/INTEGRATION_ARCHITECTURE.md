# Integration Architecture

## Adapter interface
Every external source should expose a normalized interface such as:
- `discover(query)`
- `fetch(job_ref)`
- `normalize(raw)`
- `supports_apply()`
- `prepare_application()`
- `submit()` only when permitted and supported

## Providers
Potential categories:
- Job search APIs
- Company career pages
- ATS platforms such as Greenhouse/Lever when their interfaces permit the needed operation
- Email
- Telegram
- Slack
- WhatsApp-compatible providers
- LLM providers

## Credential principle
Credentials are configuration, not code. Use environment variables for local development and encrypted secret storage for production.

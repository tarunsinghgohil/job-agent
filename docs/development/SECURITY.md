# Security Baseline

- Least-privilege credentials.
- Encrypt secrets at rest in production.
- HTTPS in production.
- CSRF/XSS/input validation appropriate to framework.
- File upload validation and malware scanning for production.
- Virus-scan or safely sandbox uploaded resumes if exposed to untrusted execution paths.
- Never expose raw secrets through API responses.
- Audit critical application actions.
- Separate user data from agent telemetry.

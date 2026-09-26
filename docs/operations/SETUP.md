# Setup

## Prerequisites
- Docker Desktop
- Git
- Node.js if running frontend outside Docker
- Python 3.11+ if running backend outside Docker

## Local flow
1. Copy `.env.example` to `.env`.
2. Add required provider values when available.
3. Start services with Docker Compose or project startup scripts.
4. Open the frontend URL documented by the current dev environment.
5. Configure the user profile and integration settings in the dashboard.

## Production
Use managed PostgreSQL, object storage, secret manager, HTTPS, backups, monitoring, and worker separation.

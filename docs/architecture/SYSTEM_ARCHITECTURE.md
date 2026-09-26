# System Architecture

## Layers
- UI: Next.js dashboard.
- API: FastAPI application layer.
- Domain services: qualification, matching, resume selection, application orchestration.
- Agent layer: bounded AI agents using tools/services.
- Integration adapters: job sources, notifications, storage, LLM provider.
- Persistence: PostgreSQL + pgvector.
- Queue/cache: Redis.
- Worker: scheduled and asynchronous jobs.

## Key rule
External integrations are adapters. Domain logic must not depend on one provider's SDK.

## Flow
UI/API -> domain service -> policy check -> provider adapter -> persistence -> event/log -> UI/notification.

# AI Implementation Rules

## Goal
Maximize useful engineering work per token while preventing context drift.

## Context loading strategy
Do not read the whole repo for normal tasks. Load:
1. `AI_CONTEXT.md`
2. One relevant spec file
3. The exact code files being changed
4. Tests for those files
5. One ADR only when architecture is ambiguous

## Source of truth priority
1. Explicit user requirement
2. `AI_CONTEXT.md`
3. Current product/architecture spec
4. Existing code behavior
5. Tests
6. General best practice

When sources conflict, stop and document the conflict rather than silently inventing a rule.

## Code style
- TypeScript strict mode.
- Python type hints for public functions.
- Small services and adapters.
- Dependency injection for external providers.
- No business logic in UI components when it can live in domain/services.
- Deterministic rule evaluation before LLM judgment.
- Structured LLM output validated against schemas.

## AI behavior
- LLMs propose; deterministic code enforces hard rules.
- Never let an LLM directly execute an irreversible external action without policy/approval checks.
- Record prompt version and model/provider in AI decisions.

## Documentation
Update docs only for changed contracts/behavior. Do not duplicate large explanations across files.

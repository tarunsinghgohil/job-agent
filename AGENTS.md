# AGENTS.md — Instructions for AI Coding Agents

## Start here
1. Read `AI_CONTEXT.md`.
2. Read `docs/README.md` and the task-specific document.
3. Inspect the relevant source files before editing.
4. Follow `docs/ai/IMPLEMENTATION_RULES.md`.

## Context minimization
Use this order instead of loading the whole repository:
- Global context: `AI_CONTEXT.md`
- Navigation: `docs/README.md`
- Architecture change: `docs/architecture/*`
- Product behavior: `docs/product/*`
- Job domain: `docs/domain/*`
- Operations/integrations: `docs/operations/*`
- Coding/testing: `docs/development/*`

Only read the exact files needed for the task.

## Change discipline
- One feature/fix at a time.
- Preserve public API contracts unless the task explicitly changes them.
- Prefer migrations over destructive schema edits.
- Never hard-code secrets, user data, or provider tokens.
- Never introduce unauthorized automation against job sites.
- For AI prompts, preserve structured JSON outputs where possible.
- Log agent decisions with enough metadata for debugging, but never log secrets.

## Definition of done
- Behavior implemented.
- Tests added/updated.
- Error handling included.
- Docs updated if contract or workflow changed.
- Local startup still documented and reproducible.
- No secret committed.

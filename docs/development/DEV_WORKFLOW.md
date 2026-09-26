# Development Workflow

1. Define the behavior in the nearest product/domain spec.
2. Add/update domain types and tests.
3. Implement service logic.
4. Connect API/UI.
5. Add integration adapter only after domain contract is stable.
6. Run tests and linters.
7. Update docs and changelog/backlog when contract changes.

Avoid large cross-layer rewrites unless required by an ADR.

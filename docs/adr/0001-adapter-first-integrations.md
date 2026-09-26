# ADR 0001 — Adapter-first integrations

## Decision
External job, notification, and AI providers are accessed through adapters.

## Why
Providers change, access varies, and core domain behavior should remain provider-neutral.

## Consequence
More interfaces and mapping code, but lower coupling and easier testing.

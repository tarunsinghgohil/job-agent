# Agent Architecture

## Orchestrator
Coordinates bounded agents and enforces policy checkpoints.

## Agents
### Career Agent
Reads approved profile/resume evidence.

### Discovery Agent
Finds and imports jobs through configured adapters.

### Qualification Agent
Applies hard filters deterministically.

### Matching Agent
Uses structured features + semantic analysis to score fit.

### Resume Agent
Selects a variant and creates a tailored application package.

### Application Agent
Creates the final package and invokes only permitted submission adapters.

### Follow-up Agent
Manages reminders and stale applications.

### Learning Agent
Summarizes outcomes and proposes improvements.

## Agent contract
Input -> validated structured context -> tool calls -> validated output -> persistence -> audit event.

Agents must be restartable and idempotent where possible.

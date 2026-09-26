# Job Scoring Model

## Principle
Hard constraints are deterministic. AI is used for semantic interpretation and explanation, not to override explicit hard constraints.

## Suggested score
100 total:
- Role alignment: 25
- Core skill match: 25
- Experience/seniority: 15
- Location/work mode: 10
- Salary: 10
- Industry/domain: 5
- Company preference: 5
- Nice-to-have skills: 5

## Hard filters
Current defaults:
- Exclude non-full-time roles.
- Prefer/require React-family relevance for default target set.
- Minimum salary filter applies only when salary information is known; unknown salary should be flagged, not silently treated as failure.
- Ignore roles clearly outside frontend/web/software target family.

## Decision bands
- 90–100: Strong Apply / highest priority.
- 80–89: Review / likely apply.
- 70–79: Review only if strategic.
- <70: Ignore by default.

## Explainability
Persist score components, matched evidence, missing evidence, hard-rule results, model/provider, and scoring version.

# Testing Strategy

## Unit
- Salary parsing.
- Location parsing.
- Role classification.
- Skill matching.
- Hard-rule evaluation.
- Score calculation.
- Resume selection.
- Deduplication.

## Integration
- Source adapter normalization.
- Database persistence.
- Notification adapters.
- LLM structured output validation.

## End-to-end
- Discover -> score -> queue.
- Job -> resume recommendation.
- Application -> answer bank -> approval.

## Golden datasets
Maintain representative job descriptions for React/frontend, healthcare, lead roles, irrelevant roles, unknown salary, and conflicting requirements. Use them to detect regressions.

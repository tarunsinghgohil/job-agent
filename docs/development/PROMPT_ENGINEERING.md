# Prompt Engineering

## Rules
- Prompts should reference specific structured context, not the entire repository.
- Use JSON/schema-constrained outputs for machine-consumed decisions.
- Keep role, task, evidence, constraints, and expected output separate.
- Version important prompts.
- Store model/provider + prompt version with decisions.

## Matching prompt input
Pass only normalized job data + approved user profile + relevant resume evidence + scoring rubric.

## Resume tailoring prompt
Pass only the selected base resume + job description + allowed changes. Explicitly prohibit invented claims.

## Application answer prompt
Retrieve from answer bank first. Ask for user input only when no approved answer exists or the question is materially ambiguous.

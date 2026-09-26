# Data Model

## Core entities
- `UserProfile`
- `JobPreference`
- `JobSource`
- `Job`
- `JobScore`
- `Resume`
- `ResumeVersion`
- `AnswerBankItem`
- `Application`
- `ApplicationAnswer`
- `NotificationChannel`
- `IntegrationCredential`
- `AgentRun`
- `AgentDecision`
- `FollowUp`
- `FeedbackOutcome`

## Important relationships
UserProfile -> many ResumeVersions, AnswerBankItems, Applications.
Job -> many JobScores/Applications (dedupe rules should normally produce one canonical Job per external posting).
Application -> one selected ResumeVersion + many ApplicationAnswers + optional AgentRun references.

## Persistence rules
- External IDs should be unique within a source.
- Store canonical URL and source URL separately when they differ.
- Keep immutable historical application snapshots where auditability matters.
- Never store raw secrets in ordinary domain tables.

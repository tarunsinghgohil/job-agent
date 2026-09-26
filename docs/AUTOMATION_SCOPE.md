# What this agent automates, and what it does not

Written for whoever operates this product. Read the second section before
turning on auto-apply.

## The pipeline

| Stage | Automated? | Notes |
| --- | --- | --- |
| Discover jobs from sources | **Yes** | Scheduled, multi-source, deduplicated. |
| Normalize and extract skills | **Yes** | Salary, experience, location, skills. |
| Score and explain the match | **Yes** | Deterministic; every score is explainable. |
| Recommend a resume | **Yes** | Deterministic pick, with an optional AI second opinion. |
| Tailor a resume / write a cover letter | **Yes** | Evidence-grounded; refuses to invent facts. |
| Resolve application answers | **Yes** | From your answer bank; AI fallback is marked "needs review". |
| Queue for approval | **Yes** | |
| **Submit the application** | **Partly — see below** | |
| Track status, follow-ups, notifications | **Yes** | |

## Submission is the one stage with a hard boundary

There is exactly one channel the agent will submit through on its own.

### Email — automated

If a posting publishes an address to apply to (`careers@`, `jobs@`, "send your
resume to …"), the agent can send the prepared application there, with the
resume attached. That address exists to receive applications, so using it is
ordinary automation.

The agent extracts such an address conservatively. A generic `support@` or a
personal address mentioned in passing is ignored, because mailing the wrong
inbox is worse than not mailing.

### LinkedIn, company portals, ATS forms — not automated

These are filled in by you. The agent prepares everything and then waits.

This is not a missing feature, it is the product rule from the project spec
(section 0, rules 6 and 7). Automating them would mean driving their forms
headlessly and working around bot protection, which risks your accounts being
banned and is explicitly out of scope. For these the agent gives you a prepared
package; you submit, then mark it submitted so tracking and follow-ups continue.

An authorized ATS integration could change this for a specific employer, but
only with real credentials from that employer's side.

## Turning on auto-apply

Auto-send is off by default and behind **three** separate gates. All of them
must be cleared:

1. **Preferences → "Let the agent send email applications"** switched on.
2. **Preferences → "Approval required before submission"** switched off.
   While approval is required, nothing is sent without you.
3. **Automations → "Auto apply (email lane)"** agent enabled. It is created
   disabled, unlike every other agent.

Then it still only touches applications on the `email` channel that already have
a published address, and it stops at your daily application cap.

Set the cap to `0` to pause sending without changing anything else.

## Before you enable it

- **Configure SMTP** (`SMTP_HOST`, `SMTP_USER`, `SMTP_FROM`, and the password
  under Integrations). Without it, sends fail loudly and the application is
  marked `failed` with the reason — it is never silently skipped.
- **Upload a resume** and set it as default, or applications go out with no
  attachment.
- **Send one manually first.** Queue an email application, click Send, and check
  the sent mail before letting the scheduler do it unattended.
- **Watch the first day.** Every send is in the audit log and the application's
  status history.

## What is recorded

Every attempt, successful or not, writes an audit entry and a job-timeline
event. A failed send leaves the application in `failed` with the reason, and can
be retried. Nothing is ever marked submitted unless it actually went out or you
said you submitted it yourself.

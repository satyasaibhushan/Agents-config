---
name: slack-operational-context
description: Read VMock automated Slack notifications for build and deployment failures, environment availability, and SSO or CSV-upload errors. Use when these operational signals help an investigation.
---

## Slack operational context

For routine operational context, use only these automated notification
channels. Other channels require an explicit task scope; do not expand the
search into discussion channels or DMs by default.

- `#code-builds` (`C033LNE918A`): build and deployment notifications.
  Read message attachments and relevant thread replies; plain message text
  can be empty even when an attachment contains a failure. Match the exact
  repository or service, revision, and environment before attributing a
  notification to a change.
- `#ops-manage-env` (`C03B0RDF3TN`): environment start/stop results,
  scheduled operations, and skipped stops with grace periods. Distinguish
  a request or acknowledgement from its result, and check later events
  before explaining an environment's availability.
- `#sso-error-mails` (`C04NA9J3NSY`): automated error emails, including
  CSV-upload errors. Read the attached email file when needed; a filename
  alone does not establish the cause, affected client, or resolution.

Fetch relevant notifications fresh through authenticated read tools, bounded
by the task's service, environment, and time window. Follow relevant threads
and attachments without broadening the channel scope. If content cannot be
read, report that gap rather than infer it. Slack is supporting evidence;
verify deployment, runtime, or ticket state at its authoritative source
before claiming success or recovery.

Keep stable channel routing and read rules in this skill. Keep task findings in the
task's chat with source links and timestamps. Do not retain message histories,
email bodies, credentials, or personal data in this repository. These rules
authorize reads only, not posting, reactions, commands, environment changes,
or scheduling automation.

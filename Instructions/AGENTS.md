# Code Structure

All code lives under `~/Code/` with two main directories:

- `~/Code/backend/` — all backend repositories
- `~/Code/frontend/` — all frontend repositories

# Personal Preferences

## TypeScript
- Never use `any` unless 100% necessary or specifically instructed.

## Code Style
- Always strive for concise, simple solutions.
- If a problem can be solved in a simpler way, propose it.

## General preferences
- If asked to do too much work at once, stop and state that clearly.
- If computer use is helpful for completing or verifying work, shell out to gpt-5.5 with Codex for it

# Workflow Catalog

A catalog of workflow specs lives at `~/Agents/Workflows/` (a git repo). Each `.md`
file is the spec of one recurring ticket class: its trigger, steps, checkpoints,
and definition of done.

- Before starting ticket-shaped work, scan `~/Agents/Workflows/INDEX.md` for a
  match; on a match, read the workflow file and follow it.
- Workflows list the repos they touch in `repos:` frontmatter, by canonical name.
  To resolve a name: check `~/Agents/Workflows/repos.local.json` first (machine-local
  name → path overrides, gitignored), else match against `~/Code/*/`; if neither
  resolves, tell the user instead of improvising.
- If a workflow and reality disagree — the code moved, a step is outdated, or the
  user had to supply context the file should have carried — update the file with
  the smallest delta that fixes it, keep its INDEX.md line in sync, and leave the
  changes uncommitted for review. Never commit or push in that repo.
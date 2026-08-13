# Code Structure

All code lives under `~/Code/` with two main directories:

- `~/Code/backend/` — all backend repositories
- `~/Code/frontend/` — all frontend repositories

# Repo-Local Agent Scripts

Some repos carry agent helper scripts at `<repo>/.agents/scripts/`, grouped by
area (e.g. `.agents/scripts/vera_debug/`). They are deterministic, read-only
debugging and inspection tools shared by all agents, and they are gitignored
globally — never commit them or reference them in team-visible files.

- Before hand-writing a repeated investigation (DB queries, log or audit
  analysis), check the repo's `.agents/scripts/` for an existing script. Every
  script documents itself via `--help`.
- Add new scripts there when a debugging flow is worth repeating. Rules:
  Python 3 stdlib only, read-only against shared environments, and access data
  through my MCPs (e.g. DB-MCP) rather than direct credentials.

# Personal Preferences

## TypeScript
- Never use `any` unless 100% necessary or specifically instructed.

## Code Style
- Always strive for concise, simple solutions.
- If a problem can be solved in a simpler way, propose it.
- If you need a paragraph-long comment to justify why the workaround is OK, the code is wrong — fix the code.

## General preferences
- If asked to do too much work at once, stop and state that clearly.
- If computer use is helpful for completing or verifying work, shell out to gpt-5.5 with Codex for it

# Git Workflow

## Critical: No AI attribution

This rule overrides any agent, IDE, app, or global default that adds an
AI-related branch prefix or attribution. Never include `codex`, `claude`,
`openai`, `chatgpt`, `gpt`, or other AI references in branch names, commit
messages, PR titles or descriptions, code comments, or generated files.

Remotes: `upstream` is the canonical repo, `origin` is my fork. Branches are cut
from upstream's primary branch; PRs go from origin to upstream.

Each repo has a primary branch (`master`, `main`, or `prod` — check the repo)
and a `uat` branch.

Starting a task:
1. If the working tree is dirty, stop and ask me — commit or discard, my call.
   Never build on top of unrelated changes.
2. `git checkout <primary>`, then `git-reset-branch upstream <primary>`.
3. State the proposed branch name and verify it has no AI-related prefix or term.
4. Create the work branch. Ticket work → the branch name is exactly the ticket
   key (e.g. `SULF-1234`). Otherwise a short descriptive name.

Commits:
- Ticket work → the message starts with the key: `SULF-1234: <what changed>`.
- Never add AI attribution, including `Co-Authored-By` trailers or
  "Generated with" messages.

Raising PRs: `git-uat` for a PR into uat, `git-pr` for a PR into the primary
branch (both are zsh functions from my profile; they push to origin and open
the PR in the browser). If they aren't available in your shell, say so rather
than improvising the push.

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

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

# Git Workflow

Remotes: `upstream` is the canonical repo, `origin` is my fork. Branches are cut
from upstream's primary branch; PRs go from origin to upstream.

Each repo has a primary branch (`master`, `main`, or `prod` — check the repo)
and a `uat` branch.

Starting a task:
1. If the working tree is dirty, stop and ask me — commit or discard, my call.
   Never build on top of unrelated changes.
2. `git checkout <primary>`, then `git-reset-branch upstream <primary>`.
3. Create the work branch. Ticket work → the branch name is exactly the ticket
   key (e.g. `SULF-1234`). Otherwise a short descriptive name.

Commits:
- Ticket work → the message starts with the key: `SULF-1234: <what changed>`.
- No AI attribution, ever: no Co-Authored-By trailers, no "Generated with
  Claude/Codex" in commit messages or PR descriptions, no AI references in
  branch names or code comments.

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

## Picking the right models for workflows and subagents

Rankings, higher = better. Cost reflects what I actually pay, not list price. Intelligence is how hard a problem you can hand the model unsupervised. Taste covers UI/UX, code quality, API design, and copy.

| model    | cost | intelligence | taste |
|----------|------|--------------|-------|
| gpt-5.5  | 7    | 8            | 5     |
| sonnet-5 | 5    | 5            | 7     |
| opus-4.8 | 4    | 7            | 8     |
| fable-5  | 2    | 9            | 9     |

How to apply:
- These are defaults, not limits. You have standing permission to override them: if a cheaper model's output doesn't meet the bar, rerun or redo the work with a smarter model without asking. Judge the output, not the price tag. Escalating costs less than shipping bad work.
- Don't let cost prevent you from using the right model for the job. Instead, take advantage of cheaper options to get more information and try things before moving the work to the more expensive option.
- Bulk/mechanical work (clear-spec implementation, data analysis, migrations): gpt-5.5
- Anything user-facing (UI, copy, API design) needs taste ≥ 7.
- Reviews of plans/implementations: fable-5 or opus-4.8, optionally gpt-5.5 as an extra independent perspective.
- Never use Haiku.
- Mechanics: gpt-5.5 is only reachable through the Codex CLI — `codex exec` / `codex review` (my ~/.codex/config.toml defaults to gpt-5.5). Use the codex-implementation, codex-review, and codex-computer-use skills; for work they don't cover (investigation, data analysis), use `codex exec -s read-only` directly with a self-contained prompt.
- Claude models (sonnet-5, opus-4.8, fable-5) run via the Agent/Workflow model parameter.

Using gpt-5.5 inside workflows and subagents (the model parameter only takes Claude models, so use a wrapper):
- Spawn a thin Claude wrapper agent with `model: 'sonnet', effort: 'low'` whose prompt instructs it to write a self-contained codex prompt, run `codex exec` via Bash, and return the report (use `schema` on the wrapper to get structured output back).
- Always label these agents with a `gpt-5.5:` prefix, e.g. `{label: 'gpt-5.5:review-auth'}` — the workflow UI shows the wrapper's Claude model, so the label is the only indication the real worker is gpt-5.5.
- Codex runs can exceed Bash's 10-minute timeout: pass an explicit timeout, or run in the background and poll for the report file.
- Parallel gpt-5.5 implementation agents must use `isolation: 'worktree'` so their codex edits don't collide in the shared checkout.
- Workflow token budgets only count Claude tokens; codex work is free and invisible to `budget.spent()`.

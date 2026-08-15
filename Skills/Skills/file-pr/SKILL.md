---
name: file-pr
description: File a concise pull request. Use when the user asks to file, open, raise, or create a PR. "uat PR" or "PR to uat" means the UAT flow.
---

# File PR

File the PR for the work already done on the current branch. This skill is
about filing well, not about writing code: if the change isn't finished, say
so and stop.

Two flavours. Default is a normal PR into the primary branch; use the UAT
flavour only when the user says uat.

## Before filing

- Confirm the branch name and every commit message contain no AI reference
  (`codex`, `claude`, `openai`, `chatgpt`, `gpt`, or similar) and no
  `Co-Authored-By` / "Generated with" trailers. If one does, stop and tell
  the user; never file it as-is.
- Work repos: `upstream` is the company repo, `origin` the fork. The PR goes
  from origin to upstream. Personal repos have origin only; the PR is
  origin-internal.
- Find the primary branch (`master`, `main`, or `prod`; check the repo).

## Normal PR

1. Run `git-pr <primary>` (a zsh shell function). It pulls upstream's primary
   into the branch and pushes to origin. If the function is missing from your
   shell, say so; do not improvise the push.
2. If the pull produced conflicts, stop and report them; never resolve
   conflicts silently as part of filing.
3. Create the PR into upstream's primary:
   `gh pr create --repo <upstream-owner>/<repo> --head <origin-owner>:<branch> --base <primary>`

## UAT PR

1. Run `git-uat` (zsh shell function). It creates `<branch>-uat`, merges
   `upstream/uat` into it, pushes it to origin, and returns to the original
   branch. Same rules: missing function or conflicts mean stop and report.
2. Create the PR from `<branch>-uat` into upstream's `uat`:
   `gh pr create --repo <upstream-owner>/<repo> --head <origin-owner>:<branch>-uat --base uat`

## Title and description

- Title: what changed, short imperative English. Ticket work starts with the
  ticket key (`SULF-1234: ...`).
- Description: lead with the problem in the user's own words, what was broken
  and for whom. Then what changed, briefly. Not an inventory of every file
  touched. A test plan line only when there is something real to run.
- Keep it concise. If the description needs headings to stay readable, it is
  probably too long.

## After filing

Reply with the PR URL and one line of status. Nothing else.

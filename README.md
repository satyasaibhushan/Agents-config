# Agent Config

This repository is the canonical, cross-machine configuration source for agent
tooling. It carries no credentials and no machine-local state: everything here
is safe to clone anywhere, including read-only onto a shared devbox.

```text
profiles.yaml   Named profiles — one per (machine, account) shape
Skills/         Custom/shared agent skills
MCPs/           Canonical MCP server definitions and sync scripts
Instructions/   Canonical agent instructions, split into fragments
scripts/        agents-config — the reconciling apply for all of the above
```

## Profiles

Every run works under a profile from `profiles.yaml` (`mac-admin`,
`devbox-admin`, `devbox-agent`, ...). A profile pins the platform, the code
root (`${CODE_ROOT}`), the instruction fragments to render, default-allow or
default-deny policies for MCPs and skills, preflight checks (e.g. the
restricted agent account must not be root or in a privileged group), and the
mode:

- **read-write** — reconcile verbs may promote live edits back into canonical.
- **read-only** — live configs may only be synced *from* canonical; the menus
  drop every verb that would write into the checkout. Also forced automatically
  whenever the checkout itself is not writable.

The first run needs an explicit `--profile <name>`; `apply` saves the choice in
`~/.config/agents-config/config.json`.

Install the launcher once for each account after cloning:

```bash
~/Agents/Config/scripts/install
```

This creates only a `~/.local/bin/agents-config` symlink back to the checkout.
It does not copy configuration, so a pull updates every linked account.

## Apply (reconciling)

`scripts/agents-config` (a launcher that finds Python ≥ 3.11 for
`scripts/apply.py`) is the one verb for pushing canonical config out and
pulling live edits back in. It runs fetch → plan → reconcile → preview → write:

```bash
agents-config apply                    # full interactive apply
agents-config plan                     # read-only drift report
agents-config plan --json              # machine-readable matrix
agents-config apply --only mcps        # or skills / instructions
```

- **Fetch/plan** normalizes every agent's live config into an item × provider
  matrix. Each cell is one of: `in sync`, `added` (live-only item), `modified`,
  `missing`, `unlinked` (skill symlink replaced by an edited folder),
  `untargeted` (present live but provider not targeted), `foreign` (symlink
  pointing elsewhere — reported only), or `migrate` (instructions content in
  sync but living at a legacy path).
- **Reconcile** groups drifted items by distinct version: an identical change
  made in three agents is one decision, not three. Verbs per version:
  **promote** (fold the live edit back into canonical), **keep** (import as-is
  or as a per-client/per-provider override), **overwrite** (regenerate from
  canonical), **skip** (leave both, re-ask next apply).
- **Preview** recomputes the whole item row before writing — including the
  ripple where a promote rewrites providers that were in sync with the old
  base. Zero writes happen before you confirm; every touched file is backed up
  under `~/.local/state/agents-config/backups/<timestamp>/`.
- **Secrets** never enter the repo: literal values from the selected MCP env
  file (normally `~/.config/agents-config/mcp.env`, or a group-read-only shared
  file reached through that path) are reverse-substituted back into `${VAR}`
  placeholders on import/promote, and all previews are masked. The same
  applies to `${HOME}` and `${CODE_ROOT}`, so canonical definitions stay
  portable across machines.

App-managed items (Codex's `node_repl`, `computer-use`, and
`openaiDeveloperDocs` MCPs) are on an ignore list — planning skips them and
writes round-trip them untouched. MCP servers that are
out of scope for the current platform, profile, or machine (missing
executable/path/secret) are reported with the reason and left exactly as found.

## Skills

`Skills/Skills/<skill-name>/SKILL.md` is the canonical layout. Agents, Claude
Code, and Cursor point at it with per-skill symlinks. Codex points at a
generated per-skill view that translates provider-specific metadata. A sparse
`Skills/skills.json` targets skills at specific agents; see `Skills/README.md`.

## MCPs

`MCPs/servers.json` is the canonical source for MCP server definitions —
schema-validated, portable (`${HOME}`/`${CODE_ROOT}`, no hardcoded paths), and
scoped per platform/profile. See `MCPs/README.md`.

## Instructions

Provider instruction files render as the concatenation of the active profile's
`Instructions/fragments/*` plus an optional per-provider extra; see
`Instructions/README.md`.

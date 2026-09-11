# Agent Config

This repository is the canonical, cross-machine configuration source for agent
tooling. It carries no credentials and no machine-local state: everything here
is safe to clone anywhere, including read-only onto a shared devbox.

```text
profiles.yaml   Named profiles — one per (machine, account) shape
Skills/         Custom/shared agent skills
MCPs/           Canonical MCP server definitions and sync scripts
Instructions/   Canonical agent instructions, split into fragments
Shell/          Shared bash and zsh configuration
Git/            Shared git config, global ignore, and gh aliases
scripts/        agents-config — the reconciling apply for all of the above
```

## Profiles

Every run works under a profile from `profiles.yaml` (`mac-admin`,
`devbox-admin`, `devbox-agent`, ...). A profile pins the platform, the code
root (`${CODE_ROOT}`), the instruction fragments to render, default-allow or
default-deny policies for MCPs and skills, an optional `skill_clients` subset
of discovery roots, preflight checks (e.g. the
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

This creates a `~/.local/bin/agents-config` symlink back to the checkout and
installs the shell startup hooks and git configuration. It requires Python 3. Configuration is sourced
from the checkout, so a pull updates every linked account's next shell.

## Shell configuration

`Shell/shared.sh` is the single shared file for interactive bash and zsh on
macOS and Linux. Add portable aliases, functions, and environment settings here.
Keep secrets, prompts, shell plugins, and machine-specific initialization local.
Use `case "$(uname -s)"` when a shared helper needs different platform behavior.

The shared file includes Git, DevSpace, Kubernetes, repository navigation, and
C++ helpers migrated from the Mac startup files. Repository shortcuts use
`CODE_ROOT`, defaulting to `/srv/Code` when present or `~/Code` otherwise.
Git PR helpers open the configured browser on macOS, use `xdg-open` on Linux
desktops, and print the URL in headless sessions. Commands such as `git`,
`devspace`, `kubectl`, and `g++` still need to be installed where used.

Run `scripts/install` once per account after cloning, including on devbox.
It adds a managed source block to `.bashrc`, `.zshrc` under `${ZDOTDIR:-$HOME}`,
and the first existing bash login file: `.bash_profile`, `.bash_login`, or
`.profile`. If none exists, it creates `.bash_profile`. Existing contents stay
in place; modified files are backed up under
`~/.local/state/agents-config/backups/shell-*/`. Repeating installation does not
duplicate hooks. If `.zshenv` sets `ZDOTDIR`, export it when running the installer.

Edits and pulls take effect in new interactive shells. To reload an existing
shell, source `Shell/shared.sh` from the checkout. Already running shells do
not reload automatically. Shell hooks are installed separately from
`agents-config plan/apply`; those commands still reconcile agent configuration.

## Git configuration

`Git/` holds the shared git setup. `scripts/install` wires it in by reference,
so a pull updates every linked account without reinstalling:

- `Git/gitconfig` is loaded through `include.path` in the account's global git
  config. Shared identity (`user.name`) and any aliases live here.
- `Git/ignore` becomes `core.excludesFile`. It carries the `.agents/*` tooling
  ignores and macOS noise, replacing the per-machine `~/.gitignore_global`.
- `Git/gh.yaml` lists GitHub CLI aliases, applied with `gh alias set --clobber`
  when `gh` is installed.

`user.email` differs per machine, so it comes from the active profile's
`git_email` in `profiles.yaml` and is written as a literal into the global git
config. The profile is the one saved by `agents-config apply`; pass
`scripts/install --profile <name>` to override. A profile without `git_email`
leaves the local value alone.

Everything else in the global git config stays untouched. A local `user.name`
equal to the shared one is removed so the include owns it; a differing one is
kept with a warning. The global config and gh config are backed up under
`~/.local/state/agents-config/backups/git-*/` before the first write. Reading
values back needs `git config --get` without `--global`: scoped reads skip
includes.

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
`Skills/skills.json` targets skills at specific agents, and each profile may
further limit which discovery roots it uses via `skill_clients`; see
`Skills/README.md`.

## MCPs

`MCPs/servers.json` is the canonical source for MCP server definitions —
schema-validated, portable (`${HOME}`/`${CODE_ROOT}`, no hardcoded paths), and
scoped per platform/profile. See `MCPs/README.md`.

## Instructions

Provider instruction files render as the concatenation of the active profile's
`Instructions/fragments/*` plus an optional per-provider extra; see
`Instructions/README.md`.

## Development permissions

`Permissions/development.json` owns the approved development tool and directory
profile. Apply it with `python3 scripts/development-access.py` after selecting a
devbox profile. It preserves unrelated settings, renders instructions, and links
missing skills through the existing reconciler.

The restricted account can edit the shared `/srv/Code` checkouts used by DevDock.
Existing files use an explicit user ACL; directory defaults preserve that access
for new code. Keep protected runtimes outside this tree. DevDock uses
`/srv/devdock-control`, owned by the daemon user with group read/execute access.
MCP definitions remain in `MCPs/servers.json`; service-side authorization applies.

## Shared devbox layout

Both devbox accounts use `/srv/Agents/Config` and `/srv/Agents/Workflows`.
Their `~/Agents` links preserve existing references. Skill links and the apply
launcher target the shared Config checkout; generated provider files remain
per-user. Workflows is a shared Git checkout, writable by `devbox-shared`.
Laptop and devbox are separate checkouts, not an automatic file-sync service.

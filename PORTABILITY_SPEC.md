# Agents Config: Cross-Machine Profiles and Portable MCPs

Status: accepted (rev 2 — named profiles replace layered overlays)  
Canonical remote: `origin` (`satyasaibhushan/Agents-config`)  
Target platforms: macOS and Linux  
Target users: human administrator and restricted agent

## Goal

Make `Agents/Config` the canonical, credential-free source for instructions,
skills, and MCP definitions across Macs and Linux hosts. Allow multiple users on
one host to share one canonical checkout while receiving different effective
configuration.

## Deployment model

- Keep one checkout per physical machine. GitHub is the synchronization layer;
  do not use a network-mounted working tree across machines.
- On a single-user Mac, use `~/Agents/Config`.
- On the Devbox, use one admin-owned checkout such as `/srv/agent-config`:
  - `saibhushan`: read/write and allowed to update canonical configuration.
  - `agent`: read-only and allowed only to apply canonical configuration into
    its own home directory.
- Store mutable state and backups outside the checkout under
  `~/.local/state/agents-config/`.
- Store each account's local selection under
  `~/.config/agents-config/config.json`. This file is not committed.
- Keep configuration differences in profiles. Use Git commits or tags to pin a
  rollout version; do not create long-lived branches per machine.

## Profiles

A profile is a named, committed configuration set — not a composition of
role × platform × provider overlays. There are exactly three to start:

- `mac-admin`
- `devbox-admin`
- `devbox-agent`

Each profile in the committed manifest (`profiles.yaml`) declares:

- `platform`: `darwin` or `linux`. Detection only validates — `apply` fails if
  the detected platform does not match the selected profile.
- `fragments`: an ordered list of instruction fragments to render (see
  Instructions below).
- `mcps`: the MCP policy for this profile (see MCP portability below).
- `skills`: the skill policy for this profile (see Skills below).
- `mode`: `read-write` or `read-only` default (see Canonical write
  permissions below).
- `preflight`: checks that must pass before apply (e.g. the restricted
  profile fails if run as root or the account is in `sudo`/`wheel`).

Usage:

```bash
agents-config apply --profile devbox-agent
agents-config plan --profile devbox-agent
```

The saved local profile (`~/.config/agents-config/config.json`) is used when
`--profile` is omitted. The first run must require an explicit profile; there
must be no unsafe implicit default. Add test-only `--platform` and `--home`
overrides so behavior can be validated without changing a real home.

New machines or roles get a new named profile. If profile bodies start
duplicating heavily, shared fragment lists are the fix — not a return to
overlay dimensions.

## Instructions

Refactor instruction sources so provider files do not duplicate the entire
base document. Suggested layout:

```text
Instructions/
  fragments/
    base.md
    devbox.md
    restricted-agent.md
  providers/          # per-provider divergent sources, as today
    claude-code.md
  profiles.yaml
  instructions.yaml   # provider -> live path mapping, as today
```

A rendered provider file is the ordered concatenation of the profile's
fragments (plus any per-provider divergent source, preserving today's
`instructions.yaml` divergence mechanism). Render into each provider's native
user-level file:

- Codex: `~/.codex/AGENTS.md`
- Claude Code: `~/.claude/CLAUDE.md`
- Cursor/generic consumer: retain its configured target

Migration must detect the existing `~/CLAUDE.md` target, back it up, and avoid
leaving two Claude instruction files that both load. The current live
`~/CLAUDE.md` has real content, so the backup → preview → confirm path is
mandatory, not theoretical. Do not delete or overwrite an existing file before
preview and confirmation.

### Promote semantics with fragments

Because a rendered file is a pure concatenation, every unchanged line maps
back to exactly one source fragment. Reconciling a drifted live file:

- A diff hunk that falls entirely within one fragment's span **promotes
  automatically into that fragment**.
- A hunk that spans a fragment boundary, or a pure insertion at a boundary,
  **prompts the user to pick the target fragment** from the profile's list.
- In `read-only` mode, promote is unavailable; only sync/skip are offered.

This keeps bidirectional sync on the Mac while making shared-checkout
promotion impossible for the restricted account.

The restricted-agent fragment must state:

- Work only under the configured shared code root (`~/Code` -> `/srv/code`).
- Do not access another user's home.
- Never attempt sudo, privilege escalation, or permission bypasses.
- Do not modify services, networking, firewall, users, mounts, or OS packages.
- Keep credentials in the agent's private home, never in `/srv` or a repo.
- Ask before destructive actions; preserve unrelated working-tree changes.

Instructions are behavioral guidance, not a security boundary. The profile
preflight (no root, no privileged groups) plus OS ownership and sudo policy
remain the actual enforcement layer.

## Canonical write permissions

Support two operating modes:

- `read-write`: may promote live changes into canonical sources.
- `read-only`: may sync canonical content into the current user's home but may
  not promote, import, rewrite manifests, or create backups inside the checkout.

Automatically use read-only behavior when the checkout is not writable. In
read-only mode, reconciliation should offer only safe actions such as sync or
skip. Backups go to the current user's private state directory.

Generated MCP configuration and secret-bearing backups must be mode `0600`;
their parent state/config directories must be mode `0700`.

## MCP portability

Keep `MCPs/servers.json` declarative and free of machine-specific absolute
paths. Extend its schema to support:

- Compatible platforms: `darwin`, `linux`, or both.
- Allowed profiles: for example `mac-admin`; `devbox-agent` is default-deny
  unless explicitly listed.
- Provider/client targeting (the existing `clients` key).
- Platform and provider overrides when unavoidable.
- Required executables, environment variables, and setup checks.
- A security classification such as `read-only`, `write`, or `sensitive`.

Prefer commands available on `PATH`, package runners, or variables such as
`${HOME}` and `${CODE_ROOT}`. Reject unscoped hard-coded paths such as
`/Users/<name>`, `/home/<name>`, and `/opt/homebrew/...` during validation.

Variable substitution alone does not make locally-built servers portable:
`db-mcp` (venv binary) and `devdock` (built `dist/index.js`) require the
project installed and built on the target host. The canonical fix is a
PATH-resolved wrapper command (or a package runner such as `uv run`/`npx`),
with the per-host install step documented in the server's `setup` field.
Installing those projects on each host is deliberately out of scope for this
repo; the `required executables resolve on PATH` validation is the gate.

Move secret input from repository-local `MCPs/.env.local` to the current user's
private file, for example:

```text
~/.config/agents-config/mcp.env
```

The shared checkout must never contain or back up resolved secrets. Each user
gets separate, least-privilege credentials. Provisioning them is a manual
admin task per service (create scoped API keys/tokens for the `agent`
account); this tool only validates their presence and file permissions — it
never provisions or copies credentials. Never copy the admin's tokens, SSH
agent, or OAuth state to `agent`.

Before applying an MCP, validate that:

- The server supports the selected platform, profile, and provider.
- Every required executable resolves on `PATH`.
- Referenced project paths exist.
- Required variables are resolved.
- Sensitive credentials have suitably restrictive file permissions.

`plan` may report missing variables; `apply` must not write unresolved secret
placeholders into live client configuration.

Remote HTTP MCPs can usually run on both platforms. Stdio MCPs require their
runtime and command on the target host. macOS/Desktop/browser-only MCPs must be
excluded from Linux profiles. MCPs granted to `devbox-agent` should use
read-only or narrowly scoped service credentials whenever possible.

Refactor current definitions accordingly, including the hard-coded paths in
`db-mcp`, `jira-attachments`, and other local executables. Mark truly Mac-only
servers explicitly instead of making Linux generation fail.

## Skills

Skills keep today's mechanism: canonical folders under `Skills/Skills/`,
symlinked into each agent's skill directory, with per-skill client targeting
in `skills.json`. Two additions:

- A profile's `skills` policy filters which skills are linked, mirroring the
  MCP policy: `devbox-agent` is default-deny unless a skill is explicitly
  listed.
- On the shared checkout, both accounts symlink into the same admin-owned
  folders; the restricted account reading admin-controlled skill files is
  intended.

## Launcher and Python compatibility

Provide one documented entrypoint such as `scripts/agents-config` or an
installed `agents-config` command. It should:

- Use Python 3.11 or newer when available.
- Fall back to `uv run --python 3.14` when `uv` is installed.
- Otherwise stop with a precise installation message.

Do not document bare `python3 scripts/apply.py` without the Python requirement;
the current macOS system Python 3.9 cannot import `tomllib`.

## Safety and compatibility

- Preserve the existing fetch -> plan -> reconcile -> preview -> confirm ->
  write workflow.
- Preserve app-managed Codex MCPs and managed/bundled skills.
- A read-only `plan` must never modify the checkout, home, or state directory.
- Keep the previous manifest format readable during migration or provide an
  explicit one-time schema migration with preview.
- Never expose secret values in plan output, diffs, logs, or errors.

## Acceptance criteria

1. The same commit runs on macOS and Linux.
2. `mac-admin`, `devbox-admin`, and `devbox-agent` produce distinct,
   deterministic plans from the same checkout.
3. Both Devbox accounts can apply from one checkout while only the admin can
   change canonical files.
4. The restricted account cannot promote canonical changes and fails its
   privilege preflight if misconfigured.
5. Instructions load once at the correct provider-native path.
6. No generated MCP entry contains an incompatible absolute host path.
7. No resolved secret or secret-bearing backup exists inside the Git checkout.
8. Secret-bearing live files and backups are `0600`; private directories are
   `0700`.
9. Unsupported MCPs are skipped with a clear reason; compatible MCP commands
   and required variables pass validation before writes.
10. Instruction promote maps in-fragment hunks to the right fragment and
    prompts on boundary-ambiguous hunks.
11. Tests use temporary homes and cover profile selection, platform
    validation, read-only canonical mode, permission modes, unresolved
    secrets, skill/MCP profile filtering, and legacy manifest migration.

## Rollout

1. Add the portable launcher and the `--home`/`--platform` seams (`apply.py`
   currently hard-codes `Path.home()`; the seams are prerequisites for
   testing it at all).
2. Add characterization tests for current behavior before refactoring.
3. Add profile resolution and preflights.
4. Refactor instruction rendering into fragments and implement the promote
   semantics above.
5. Move backups, local selection, and MCP environment input outside the repo.
6. Add MCP schema validation and platform/profile filtering.
7. Convert current MCP definitions and run read-only plans on both platforms.
8. Review the complete diff and security behavior before committing.
9. After merging, create the single `/srv/agent-config` checkout and apply
   each Devbox profile separately.

Steps 1–8 need only the Mac; the Devbox enters at step 9.

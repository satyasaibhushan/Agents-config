# HindSight on the Mac

Canonical endpoint: `https://hindsight.bhushan.fun/api/mcp`.
The `mac-admin` profile registers the three default clients in `servers.json`.
The dedicated installer extends that definition to existing private hub profiles
and OpenCode. No remote account is configured by this installer.

Run with Python 3.11 or newer after cloning or updating the repository:

```sh
python3 scripts/install-hindsight.py --instructions
```

Requires Node 22+, npm, and the locally provisioned ingestion key. On a new
machine the installer installs the hidden-entry helper and stops with the exact
missing-key step. Run `~/.local/bin/save-hindsight-token` directly in a terminal,
then repeat installation. Create the key at
[HindSight tokens](https://hindsight.bhushan.fun/tokens) with `feedback:submit`
only and a bounded expiry. Never enter it in chat or copy another machine's key.

The key stays in `~/.config/hindsight/mac-agents.token`, directory 0700/file 0600.
The installer checks metadata only. It never opens the key. Native configuration
contains the endpoint, helper path, or OpenCode's file reference, never a key.
The HTTP header helper checks owner/mode and exact server/endpoint; its output
belongs only to the client's private pipe. Never run the header helper as a
shell diagnostic. The stdio bridge uses the locked official SDK, restricts
requests to the endpoint, refuses redirects, exposes only `submit_feedback`,
and never retries submissions or stores authentication state.

Ordinary client launches load authentication automatically, including GUI
launches. No shell exports, daily wrappers, login hooks, or approval changes
are required. The installer enrolls four default configs plus existing
`.codex-privatehub-{zai,copilot,cursor}` and `.claude-privatehub` configs. It
preserves unrelated configuration and refuses differing HindSight entries.
OpenCode JSONC comments are preserved; a conflicting or existing MCP map needs
an explicit merge. The normal reconciler handles the three default profiles;
repeat this installer after updates to refresh runtime and hub registrations.

`--instructions` uses the existing instruction renderer and backups. It updates
missing files or the previous unchanged render only, and stops on local drift.
The Mac profile adds `Instructions/fragments/hindsight.md`; the installer
extends the renderer to existing hub profiles and OpenCode. Already running sessions need their
normal reload/new session to pick up instruction changes.

Touched configs and instructions are backed up under
`~/.local/state/agents-config/backups/*-hindsight/`. Runtime files live under
`~/.local/share/hindsight-mcp` with owner-only helpers in `~/.local/bin`.
Dependencies are pinned in `package-lock.json`; installation scripts are disabled.
No key goes in `mcp.env`, generated previews, the repository, or backups.

Discovery itself consumes HTTP requests from the ingestion key's shared rate
limit. A 429 can occur even without a submission. Stop the burst and wait for
`Retry-After` before a later discovery check. Do not raise the server limit or
add an automatic feedback retry. See the
[source feedback guidance](https://github.com/satyasaibhushan/HindSight/blob/main/docs/agent-feedback.md).

# MCP Config

`servers.json` is the canonical MCP source of truth for:

- Cursor: `~/.cursor/mcp.json`
- Claude Code: `~/.claude.json`
- Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Codex: `~/.codex/config.toml`

## Files

```text
servers.json                 Canonical MCP server definitions
.env.example                 Secret placeholders (real values: ~/.config/agents-config/mcp.env)
~/.local/state/agents-config/generated/  Private resolved previews (0600)
scripts/generate-mcps.py     Regenerate previews from servers.json (used by apply)
```

## Server schema

Each entry in `servers.json` supports, besides `clients`, `config`, and
per-client override blocks (`codex:`, `claude-desktop:`, ...):

```jsonc
{
  "clients": ["claude-code", "codex"],
  "platforms": ["darwin"],               // omit = every platform
  "profiles": ["mac-admin"],             // omit = the profile's default policy
  "requires": {                           // machine capabilities; any miss ⇒ out of scope
    "executables": ["node"],
    "env": ["SOME_API_KEY"],
    "paths": ["${CODE_ROOT}/Personal/tool/dist/index.js"]
  },
  "security": "what this server can read or touch",
  "setup": "how to provision a new machine for it",
  "config": { "command": "${HOME}/.local/bin/tool" }
}
```

The schema is validated on every run. Hardcoded machine paths (`/Users/...`,
`/home/...`, `/opt/homebrew/...`) are rejected — use `${HOME}` or
`${CODE_ROOT}` (the code root comes from the active profile). Out-of-scope
servers are skipped with a printed reason and their live entries left
untouched.

## Secret handling

Real values live in `~/.config/agents-config/mcp.env` (must be mode 0600) —
never in this repo, and outside the checkout so the repo can be shared
read-only. `plan` never changes its permissions; it warns, while `apply` and
standalone generation stop with the exact `chmod` command when it is unsafe.
Canonical config uses `${VAR}` placeholders; generation injects the
literal values into private user-state previews (0600) and into live
configs on apply. Apply refuses to write configs with unresolved placeholders.
On import/promote, literal secrets are reverse-substituted back into
placeholders, and all previews are masked.

## Apply

```bash
agents-config apply --only mcps    # interactive reconcile
agents-config plan --only mcps     # read-only drift report
```

To regenerate private preview files without applying:

```bash
python3 ~/Agents/Config/MCPs/scripts/generate-mcps.py --profile mac-admin
```

The active profile filters the preview by platform, permissions, and available
requirements exactly like `agents-config apply`. The command prints the output
directory. Use `--output-dir` only when a
different private location is needed; resolved previews must never be written
inside the Git checkout.

Applies back up every touched file under
`~/.local/state/agents-config/backups/<timestamp>/`.

For config files that contain non-MCP settings, such as `~/.claude.json` and
Claude Desktop's config, the apply updates only the `mcpServers` key (or the
`[mcp_servers.*]` tables in Codex's TOML) and preserves the rest of the file.
App-managed Codex servers (`node_repl`, `computer-use`, and
`openaiDeveloperDocs`) are ignored during planning and round-tripped untouched
on write.

The restricted `devbox-agent` profile explicitly allows only the read-oriented
DB, New Relic, and Jira MCP definitions. They remain out of scope until their
commands, paths, and environment variables exist. Give that account separate,
least-privilege service credentials rather than reusing an admin token.

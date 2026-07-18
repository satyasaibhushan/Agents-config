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
generated/cursor.mcp.json     Ignored preview for ~/.cursor/mcp.json
generated/claude-code.json    Ignored preview for top-level ~/.claude.json mcpServers
generated/claude-desktop.json Ignored preview for Claude Desktop config
generated/codex-mcp.toml      Ignored preview for Codex [mcp_servers.*] TOML
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

Real values live in `~/.config/agents-config/mcp.env` (mode 0600, enforced) —
never in this repo, and outside the checkout so the repo can be shared
read-only. Canonical config uses `${VAR}` placeholders; generation injects the
literal values into the gitignored `generated/` files (0600) and into live
configs on apply. Apply refuses to write configs with unresolved placeholders.
On import/promote, literal secrets are reverse-substituted back into
placeholders, and all previews are masked.

## Apply

```bash
agents-config apply --only mcps    # interactive reconcile
agents-config plan --only mcps     # read-only drift report
```

To regenerate the ignored preview files without applying:

```bash
python3 ~/Agents/Config/MCPs/scripts/generate-mcps.py
```

Applies back up every touched file under
`~/.local/state/agents-config/backups/<timestamp>/`.

For config files that contain non-MCP settings, such as `~/.claude.json` and
Claude Desktop's config, the apply updates only the `mcpServers` key (or the
`[mcp_servers.*]` tables in Codex's TOML) and preserves the rest of the file.
App-managed servers (e.g. Codex's `node_repl`) are ignored during planning and
round-tripped untouched on write.

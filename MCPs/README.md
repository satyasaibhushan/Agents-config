# MCP Config

`servers.json` is the canonical MCP source of truth. It was generated from the current local setup for:

- Cursor: `~/.cursor/mcp.json`
- Claude Code: `~/.claude.json`
- Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Codex: `~/.codex/config.toml`

## Files

```text
servers.json                 Canonical MCP server definitions
.env.example                 Secret placeholders
generated/cursor.mcp.json     Ignored preview for ~/.cursor/mcp.json
generated/claude-code.json    Ignored preview for top-level ~/.claude.json mcpServers
generated/claude-desktop.json Ignored preview for Claude Desktop config
generated/codex-mcp.toml      Ignored preview for Codex [mcp_servers.*] TOML
scripts/generate-mcps.py     Regenerate previews from servers.json
scripts/apply-mcps.sh        Backup and apply generated configs
```

## Secret Handling

Do not commit secrets. Canonical config uses placeholders like:

```text
${NEW_RELIC_API_KEY}
```

Set those environment variables before launching an agent, or replace them in a private local config after generation.

## Apply

Review generated files first:

```bash
python3 ~/Agents/Config/MCPs/scripts/generate-mcps.py
```

When ready:

```bash
~/Agents/Config/MCPs/scripts/apply-mcps.sh
```

The script writes backups under:

```text
~/Agents/Config/MCPs/backups/<timestamp>/
```

For config files that contain non-MCP settings, such as `~/.claude.json` and Claude Desktop's config, the apply script updates only the `mcpServers` key and preserves the rest of the file.

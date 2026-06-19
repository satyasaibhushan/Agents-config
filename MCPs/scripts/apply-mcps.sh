#!/usr/bin/env bash
set -euo pipefail

root="$HOME/Agents/Config/MCPs"
generated="$root/generated"
timestamp="$(date +%Y%m%d-%H%M%S)"
backup="$root/backups/$timestamp"

python3 "$root/scripts/generate-mcps.py"
mkdir -p "$backup"

backup_file() {
  local path="$1"
  if [ -e "$path" ] || [ -L "$path" ]; then
    mkdir -p "$backup/$(dirname "$path")"
    cp -a "$path" "$backup/$path"
  fi
}

backup_file "$HOME/.cursor/mcp.json"
backup_file "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
backup_file "$HOME/.claude.json"
backup_file "$HOME/.codex/config.toml"

mkdir -p "$HOME/.cursor"
cp "$generated/cursor.mcp.json" "$HOME/.cursor/mcp.json"

mkdir -p "$HOME/Library/Application Support/Claude"
python3 - "$HOME/Library/Application Support/Claude/claude_desktop_config.json" "$generated/claude-desktop.json" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
generated = Path(sys.argv[2])

data = {}
if target.exists():
    with target.open() as f:
        data = json.load(f)

with generated.open() as f:
    mcp = json.load(f)["mcpServers"]

data["mcpServers"] = mcp
target.write_text(json.dumps(data, indent=2) + "\n")
PY

python3 - "$HOME/.claude.json" "$generated/claude-code.json" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
generated = Path(sys.argv[2])

data = {}
if target.exists():
    with target.open() as f:
        data = json.load(f)

with generated.open() as f:
    mcp = json.load(f)["mcpServers"]

data["mcpServers"] = mcp
target.write_text(json.dumps(data, indent=2) + "\n")
PY

python3 - "$HOME/.codex/config.toml" "$generated/codex-mcp.toml" <<'PY'
import re
import sys
from pathlib import Path

target = Path(sys.argv[1])
generated = Path(sys.argv[2])

content = target.read_text() if target.exists() else ""
content = re.sub(r'\n\[mcp_servers(?:\.[^\]\n]+)?\][\s\S]*?(?=\n\[[^\]\n]+\]|\Z)', '', content)
content = content.rstrip() + "\n\n" + generated.read_text().rstrip() + "\n"
target.write_text(content)
PY

echo "Applied MCP config. Backups: $backup"

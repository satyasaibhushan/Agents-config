#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVERS_PATH = ROOT / "servers.json"
GENERATED_DIR = ROOT / "generated"
ENV_PATH = ROOT / ".env.local"

PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Placeholders that could not be resolved during this run. Collected so we can
# warn the operator without ever printing the resolved (secret) values.
MISSING_PLACEHOLDERS = set()


def load_servers():
    with SERVERS_PATH.open() as f:
        return json.load(f)["servers"]


def load_env():
    """Source secrets from .env.local, with the real shell environment as a
    fallback. Values here are injected into the gitignored generated/ files so
    each agent gets a literal key instead of an unexpanded ${VAR}."""
    env = {}
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def substitute(value, env):
    """Recursively replace ${VAR} placeholders using .env.local then os.environ.
    Unresolved placeholders are left intact and recorded in MISSING_PLACEHOLDERS."""
    if isinstance(value, str):
        def repl(match):
            name = match.group(1)
            resolved = env.get(name) or os.environ.get(name)
            if resolved:
                return resolved
            MISSING_PLACEHOLDERS.add(name)
            return match.group(0)

        return PLACEHOLDER_RE.sub(repl, value)
    if isinstance(value, list):
        return [substitute(item, env) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, env) for key, item in value.items()}
    return value


def json_config_for_client(servers, client, env):
    mcp_servers = {}
    for name, entry in servers.items():
        if client not in entry.get("clients", []):
            continue

        config = dict(entry.get("config", {}))
        config.update(entry.get(client, {}))  # optional per-client override block
        config = substitute(config, env)

        if client == "cursor" and config.get("type") == "http":
            config.pop("type", None)

        if client == "claude-desktop":
            config.pop("type", None)
            # Claude Desktop only supports stdio servers. When a command-based
            # override is supplied (e.g. an mcp-remote bridge), drop the remote
            # transport keys so the entry is a valid stdio config.
            if "command" in config:
                config.pop("url", None)
                config.pop("headers", None)

        mcp_servers[name] = config

    return {"mcpServers": mcp_servers}


def toml_quote(value):
    return json.dumps(value)


def toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return toml_quote(value)


def codex_config(servers, env):
    lines = [
        "# Generated from ~/Agents/Config/MCPs/servers.json",
        "# Paste or sync this section into ~/.codex/config.toml.",
        "",
    ]

    for name, entry in servers.items():
        if "codex" not in entry.get("clients", []):
            continue

        config = dict(entry.get("config", {}))
        config.update(entry.get("codex", {}))
        config = substitute(config, env)
        config = {
            key: value
            for key, value in config.items()
            if key in {"args", "command", "enabled", "env", "startup_timeout_sec"}
        }
        server_env = config.pop("env", None)

        table_name = name if name.replace("_", "").replace("-", "").isalnum() else json.dumps(name)
        lines.append(f"[mcp_servers.{table_name}]")
        for key in sorted(config):
            lines.append(f"{key} = {toml_value(config[key])}")
        lines.append("")

        if server_env:
            lines.append(f"[mcp_servers.{table_name}.env]")
            for key in sorted(server_env):
                lines.append(f"{key} = {toml_value(server_env[key])}")
            lines.append("")

    return "\n".join(lines)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def main():
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    servers = load_servers()
    env = load_env()

    if not ENV_PATH.exists():
        print(f"warning: {ENV_PATH} not found; placeholders will rely on the shell environment", file=sys.stderr)

    write_json(GENERATED_DIR / "cursor.mcp.json", json_config_for_client(servers, "cursor", env))
    write_json(GENERATED_DIR / "claude-code.json", json_config_for_client(servers, "claude-code", env))
    write_json(GENERATED_DIR / "claude-desktop.json", json_config_for_client(servers, "claude-desktop", env))
    (GENERATED_DIR / "codex-mcp.toml").write_text(codex_config(servers, env))

    if MISSING_PLACEHOLDERS:
        names = ", ".join(sorted(MISSING_PLACEHOLDERS))
        print(
            f"warning: unresolved placeholder(s) left as-is (not in .env.local or shell env): {names}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()

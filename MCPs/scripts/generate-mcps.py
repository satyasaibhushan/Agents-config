#!/usr/bin/env python3
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVERS_PATH = ROOT / "servers.json"
GENERATED_DIR = ROOT / "generated"


def load_servers():
    with SERVERS_PATH.open() as f:
        return json.load(f)["servers"]


def json_config_for_client(servers, client):
    mcp_servers = {}
    for name, entry in servers.items():
        if client not in entry.get("clients", []):
            continue

        config = dict(entry.get("config", {}))

        if client == "cursor" and config.get("type") == "http":
            config.pop("type", None)

        if client == "claude-desktop":
            config.pop("type", None)

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


def codex_config(servers):
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
        config = {
            key: value
            for key, value in config.items()
            if key in {"args", "command", "enabled", "env", "startup_timeout_sec"}
        }
        env = config.pop("env", None)

        table_name = name if name.replace("_", "").replace("-", "").isalnum() else json.dumps(name)
        lines.append(f"[mcp_servers.{table_name}]")
        for key in sorted(config):
            lines.append(f"{key} = {toml_value(config[key])}")
        lines.append("")

        if env:
            lines.append(f"[mcp_servers.{table_name}.env]")
            for key in sorted(env):
                lines.append(f"{key} = {toml_value(env[key])}")
            lines.append("")

    return "\n".join(lines)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def main():
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    servers = load_servers()

    write_json(GENERATED_DIR / "cursor.mcp.json", json_config_for_client(servers, "cursor"))
    write_json(GENERATED_DIR / "claude-code.json", json_config_for_client(servers, "claude-code"))
    write_json(GENERATED_DIR / "claude-desktop.json", json_config_for_client(servers, "claude-desktop"))
    (GENERATED_DIR / "codex-mcp.toml").write_text(codex_config(servers))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SERVERS_PATH = ROOT / "servers.json"
ENV_PATH = Path.home() / ".config" / "agents-config" / "mcp.env"
LEGACY_ENV_PATH = ROOT / ".env.local"

PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Placeholders that could not be resolved during this run. Collected so we can
# warn the operator without ever printing the resolved (secret) values.
MISSING_PLACEHOLDERS = set()


def load_servers():
    with SERVERS_PATH.open() as f:
        return json.load(f)["servers"]


def env_path():
    """Secrets live in ~/.config/agents-config/mcp.env — outside the checkout,
    so the repo can be shared read-only and can never leak a key. The old
    MCPs/.env.local is honored with a nag until it is moved."""
    if ENV_PATH.exists():
        return ENV_PATH
    if LEGACY_ENV_PATH.exists():
        print(f"warning: using legacy {LEGACY_ENV_PATH}; move it to {ENV_PATH}",
              file=sys.stderr)
        return LEGACY_ENV_PATH
    return None


def generated_dir(home=Path.home()):
    """Resolved previews are mutable, secret-bearing user state, never repo data."""
    return home / ".local" / "state" / "agents-config" / "generated"


def load_env(strict_permissions=False):
    """Source secrets from mcp.env, with the real shell environment as a
    fallback. Values are injected into private user-state previews and live
    provider configs so each agent gets a literal key instead of ${VAR}."""
    env = {}
    path = env_path()
    if path is not None:
        mode = path.stat().st_mode & 0o777
        # A per-user file is normally 0600.  Devboxes may instead point each
        # account at one group-owned 0640 file; group write/execute and every
        # permission for other users remain forbidden.
        if mode & 0o037:
            message = (
                f"{path} must be private or group-read-only "
                f"(run: chmod 600 {path}, or chmod 640 for a shared group file)"
            )
            if strict_permissions:
                sys.exit("error: " + message)
            print("warning: " + message, file=sys.stderr)
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    env["MCP_ENV_PATH"] = str(path or ENV_PATH)
    # Path variables for portable server definitions. Standalone generation
    # assumes the default layout; apply.py overrides both from the profile.
    env.setdefault("HOME", str(Path.home()))
    env.setdefault("CODE_ROOT", os.environ.get("CODE_ROOT",
                                               str(Path.home() / "Code")))
    return env


def substitute(value, env):
    """Recursively replace ${VAR} placeholders using mcp.env then os.environ.
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
    os.chmod(path, 0o600)  # generated files carry resolved secrets


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate secret-bearing MCP previews outside the checkout")
    parser.add_argument("--profile", required=True,
                        help="profile from the repository profiles.yaml")
    parser.add_argument("--platform", choices=["darwin", "linux"],
                        default="darwin" if sys.platform == "darwin" else "linux")
    parser.add_argument("--output-dir", type=Path,
                        help="override ~/.local/state/agents-config/generated")
    return parser.parse_args(argv)


def scoped_servers(servers, env, profile_name, platform, home):
    """Use apply.py's one schema/scope implementation for standalone previews."""
    apply_path = ROOT.parent / "scripts" / "apply.py"
    spec = importlib.util.spec_from_file_location("agents_config_apply", apply_path)
    applymod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(applymod)
    profiles = applymod.load_profiles()
    args = argparse.Namespace(
        profile=profile_name, home=home, platform=platform)
    profile = applymod.resolve_profile(args, profiles)
    applymod.run_preflight(profile)
    env.update(applymod.path_vars({}, home, profile))
    applymod.validate_servers(servers, profiles)
    selected, out = applymod.partition_servers(
        SimpleNamespace(substitute=substitute),
        servers, profile, platform, env)
    for name, reason in sorted(out.items(), key=lambda item: item[0].lower()):
        print(f"out of scope: {name} — {reason}", file=sys.stderr)
    return selected


def main(argv=None):
    args = parse_args(argv)
    output_dir = args.output_dir or generated_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    servers = load_servers()
    env = load_env(strict_permissions=True)
    servers = scoped_servers(
        servers, env, args.profile, args.platform, Path.home())

    if env_path() is None:
        print(f"warning: {ENV_PATH} not found; placeholders will rely on the shell environment", file=sys.stderr)

    write_json(output_dir / "cursor.mcp.json", json_config_for_client(servers, "cursor", env))
    write_json(output_dir / "claude-code.json", json_config_for_client(servers, "claude-code", env))
    write_json(output_dir / "claude-desktop.json", json_config_for_client(servers, "claude-desktop", env))
    toml_path = output_dir / "codex-mcp.toml"
    toml_path.write_text(codex_config(servers, env))
    os.chmod(toml_path, 0o600)

    if MISSING_PLACEHOLDERS:
        names = ", ".join(sorted(MISSING_PLACEHOLDERS))
        print(
            f"warning: unresolved placeholder(s) left as-is (not in mcp.env or shell env): {names}",
            file=sys.stderr,
        )
    print(output_dir)


if __name__ == "__main__":
    main()

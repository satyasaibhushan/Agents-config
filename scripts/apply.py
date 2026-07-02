#!/usr/bin/env python3
"""Reconciling apply for Agent-config (AC-1 + AC-2 per-skill targeting).

One verb: fetch -> plan -> reconcile -> preview -> write.

fetch      normalizes every provider's native config (MCPs + skills) into
           (item, provider, state) triples.
plan       prints the full item x provider matrix. Every cell is exactly one of:
           in sync / added / modified / missing / unlinked / untargeted / foreign.
reconcile  walks drifted items grouped by distinct version. Verbs:
             promote   this version becomes the canonical base for every provider
             keep      import into canonical (per-client override for modified)
             overwrite regenerate the provider from canonical
             skip      leave both sides, re-ask next apply
detect     secrets from MCPs/.env.local are never written into servers.json --
           literal values are reverse-substituted back to ${VAR} placeholders,
           and masked in all output.
preview    recomputes every affected item row (including promote ripple onto
           providers that were in sync with the old base) before anything is
           written. Zero writes before confirm; backups always.
targeting  skills mirror the MCP `clients` key via Skills/skills.json:
             {"version": 1, "skills": {"<name>": {"clients": ["claude-code"]}}}
           The manifest is sparse -- a skill absent from it targets every agent.
           Reconcile decisions (keep here / stop targeting / target this agent)
           rewrite the manifest on confirm.

Usage:
  apply.py                interactive reconcile + apply
  apply.py --plan         print the drift matrix and exit (read-only)
  apply.py --plan --json  machine-readable plan (for the control plane later)
  apply.py --only mcps    limit to MCP servers (or: --only skills)
"""

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import tomllib
from datetime import datetime
from pathlib import Path

CONFIG_ROOT = Path(__file__).resolve().parents[1]
MCPS_ROOT = CONFIG_ROOT / "MCPs"
SERVERS_PATH = MCPS_ROOT / "servers.json"
SKILLS_ROOT = CONFIG_ROOT / "Skills"
CANONICAL_SKILLS = SKILLS_ROOT / "Skills"
SKILLS_MANIFEST = SKILLS_ROOT / "skills.json"

MCP_CLIENTS = ["cursor", "claude-code", "claude-desktop", "codex"]
SKILL_AGENTS = {
    "agents": ".agents/skills",
    "claude-code": ".claude/skills",
    "codex": ".codex/skills",
    "cursor": ".cursor/skills",
}
# Agent-managed skills that must never be treated as drift (see Skills/README.md).
SKILL_IGNORE = {
    "codex": {"codex-primary-runtime"},
}
# Agent-managed MCP servers (installed by the app itself, not by us).
MCP_IGNORE = {
    "codex": {"node_repl"},
}

CODEX_KEYS = {"args", "command", "enabled", "env", "startup_timeout_sec"}

IN_SYNC = "in sync"
ADDED = "added"
MODIFIED = "modified"
MISSING = "missing"
UNLINKED = "unlinked"
UNTARGETED = "untargeted"  # in canonical, provider not targeted, but present live
FOREIGN = "foreign"        # symlink pointing somewhere non-canonical
DRIFT_STATES = {ADDED, MODIFIED, MISSING, UNLINKED, UNTARGETED}


def load_genmod():
    """Reuse generate-mcps.py's substitution + per-client transform logic so
    desired state here can never diverge from what generation produces."""
    spec = importlib.util.spec_from_file_location(
        "genmcps", MCPS_ROOT / "scripts" / "generate-mcps.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mcp_config_paths(home):
    return {
        "cursor": home / ".cursor/mcp.json",
        "claude-code": home / ".claude.json",
        "claude-desktop": home / "Library/Application Support/Claude/claude_desktop_config.json",
        "codex": home / ".codex/config.toml",
    }


# ---------------------------------------------------------------- secrets

def build_secret_map(env):
    """value -> ${VAR}, for masking output and reverse-substituting imports."""
    return {
        value: "${%s}" % name
        for name, value in env.items()
        if value and len(value) >= 6
    }


def reverse_substitute(value, secret_map):
    if isinstance(value, str):
        for secret, placeholder in secret_map.items():
            if secret in value:
                value = value.replace(secret, placeholder)
        return value
    if isinstance(value, list):
        return [reverse_substitute(item, secret_map) for item in value]
    if isinstance(value, dict):
        return {k: reverse_substitute(v, secret_map) for k, v in value.items()}
    return value


def render(value, secret_map, indent=None):
    return json.dumps(reverse_substitute(value, secret_map), indent=indent, sort_keys=True)


# ---------------------------------------------------------------- fetch: MCPs

def read_live_mcps(client, path):
    if not path.exists():
        return {}
    try:
        if client == "codex":
            return tomllib.loads(path.read_text()).get("mcp_servers", {}) or {}
        data = json.loads(path.read_text())
        return data.get("mcpServers", {}) or {}
    except Exception as exc:  # unreadable config is a hard stop, not silent drift
        sys.exit(f"error: cannot parse {path}: {exc}")


def desired_mcp(genmod, name, entry, client, env):
    """What generation would produce for this (server, client), or None."""
    if client not in entry.get("clients", []):
        return None
    if client == "codex":
        config = dict(entry.get("config", {}))
        config.update(entry.get("codex", {}))
        config = genmod.substitute(config, env)
        config = {k: v for k, v in config.items() if k in CODEX_KEYS}
        if not config.get("env"):
            config.pop("env", None)  # TOML generation omits empty env tables
        return config
    generated = genmod.json_config_for_client({name: entry}, client, env)
    return generated["mcpServers"].get(name)


def norm(value):
    return json.dumps(value, sort_keys=True)


def plan_mcps(genmod, servers, env, home):
    """-> {name: {client: cell}} where cell = {state, live, desired}."""
    paths = mcp_config_paths(home)
    live_all = {client: read_live_mcps(client, path) for client, path in paths.items()}

    items = {}
    names = set(servers)
    for live in live_all.values():
        names |= set(live)

    for name in sorted(names, key=str.lower):
        entry = servers.get(name)
        cells = {}
        for client in MCP_CLIENTS:
            if name in MCP_IGNORE.get(client, set()):
                continue  # app-managed; write-back still round-trips it untouched
            live = live_all[client].get(name)
            desired = desired_mcp(genmod, name, entry, client, env) if entry else None
            if live is None and desired is None:
                continue
            if desired is None and live is not None:
                state = ADDED if entry is None else UNTARGETED
            elif live is None:
                state = MISSING
            elif norm(live) == norm(desired):
                state = IN_SYNC
            else:
                state = MODIFIED
            cells[client] = {"state": state, "live": live, "desired": desired}
        if cells:
            items[name] = cells
    return items, live_all


# ---------------------------------------------------------------- fetch: skills

def load_skill_targets():
    """Skills/skills.json -> {name: [agents]}. Sparse: a skill absent from the
    manifest targets every agent (so no manifest means AC-1 behavior)."""
    if not SKILLS_MANIFEST.exists():
        return {}
    try:
        data = json.loads(SKILLS_MANIFEST.read_text())
    except Exception as exc:
        sys.exit(f"error: cannot parse {SKILLS_MANIFEST}: {exc}")
    targets = {}
    for name, entry in (data.get("skills") or {}).items():
        clients = entry.get("clients", [])
        unknown = [c for c in clients if c not in SKILL_AGENTS]
        if unknown:
            sys.exit(f"error: skills.json: {name}: unknown client(s): {', '.join(unknown)}")
        targets[name] = clients
    return targets


def skill_clients(name, targets):
    return targets.get(name, list(SKILL_AGENTS))


def write_skill_targets(targets):
    manifest = {
        "version": 1,
        "skills": {
            name: {"clients": clients}
            for name, clients in sorted(targets.items(), key=lambda kv: kv[0].lower())
        },
    }
    SKILLS_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")


def dir_digest(path):
    digest = hashlib.sha256()
    for file in sorted(p for p in Path(path).rglob("*") if p.is_file()):
        if file.name == ".DS_Store":
            continue
        digest.update(str(file.relative_to(path)).encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def plan_skills(home, targets):
    """-> {name: {agent: cell}} with skill states per agent directory.
    targets: Skills/skills.json content — absent skill = targets every agent."""
    canonical = {
        p.name: p for p in sorted(CANONICAL_SKILLS.iterdir())
        if p.is_dir() and not p.name.startswith(".")
    } if CANONICAL_SKILLS.is_dir() else {}

    items = {}
    for agent, rel in SKILL_AGENTS.items():
        agent_dir = home / rel
        ignore = SKILL_IGNORE.get(agent, set())
        seen = set()
        if agent_dir.is_dir():
            for target in sorted(agent_dir.iterdir()):
                name = target.name
                if name.startswith(".") or name in ignore:
                    continue
                seen.add(name)
                cell = classify_skill(target, canonical.get(name))
                if cell is None:
                    continue
                if (name in canonical and cell["state"] != FOREIGN
                        and agent not in skill_clients(name, targets)):
                    # in canonical, present live, but this agent isn't targeted
                    cell = {
                        "state": UNTARGETED,
                        "kind": "dir" if cell["state"] == UNLINKED else "link",
                        "identical": cell.get("identical", True),
                        "path": str(target),
                    }
                items.setdefault(name, {})[agent] = cell
        for name in canonical:
            if name not in seen and agent in skill_clients(name, targets):
                items.setdefault(name, {})[agent] = {"state": MISSING}

    # drop rows where every agent is in sync
    return {
        name: cells for name, cells in sorted(items.items(), key=lambda kv: kv[0].lower())
        if any(cell["state"] != IN_SYNC for cell in cells.values())
    }, canonical


def classify_skill(target, canonical_path):
    if target.is_symlink():
        dest = target.resolve() if target.exists() else Path(target.readlink())
        if canonical_path and dest == canonical_path.resolve():
            return {"state": IN_SYNC}
        return {"state": FOREIGN, "dest": str(dest)}
    if target.is_dir():
        if canonical_path:
            identical = dir_digest(target) == dir_digest(canonical_path)
            return {"state": UNLINKED, "identical": identical, "path": str(target)}
        return {"state": ADDED, "path": str(target), "digest": dir_digest(target)}
    return None  # stray file; not a skill


# ---------------------------------------------------------------- plan output

STATE_MARK = {
    IN_SYNC: "in sync",
    ADDED: "+ added",
    MODIFIED: "~ modified",
    MISSING: "x missing",
    UNLINKED: "! unlinked",
    UNTARGETED: "+ untargeted",
    FOREIGN: "> foreign",
}


def print_matrix(title, items, columns):
    drifted = {
        name: cells for name, cells in items.items()
        if any(c["state"] in DRIFT_STATES or c["state"] == FOREIGN for c in cells.values())
    }
    print(f"\n{title} — {len(drifted)} item(s) need attention")
    if not drifted:
        return drifted
    width = max(len(name) for name in drifted) + 2
    header = "  " + "ITEM".ljust(width) + "".join(c.ljust(16) for c in columns)
    print(header)
    for name, cells in drifted.items():
        row = "  " + name.ljust(width)
        for client in columns:
            cell = cells.get(client)
            row += (STATE_MARK[cell["state"]] if cell else "n/a").ljust(16)
        print(row)
    return drifted


# ---------------------------------------------------------------- reconcile

def ask(prompt, choices):
    """choices: ordered {key: label}."""
    menu = "  " + "\n  ".join(f"({key}) {label}" for key, label in choices.items())
    while True:
        try:
            answer = input(f"{menu}\n> ").strip().lower()
        except EOFError:
            sys.exit("\naborted: no answer on stdin")
        if answer in choices:
            return answer
        print(f"  pick one of: {', '.join(choices)}")


def version_groups(cells, state):
    """Group clients whose live config is byte-identical -> one decision each."""
    groups = {}
    for client, cell in cells.items():
        if cell["state"] == state:
            groups.setdefault(norm(cell["live"]), []).append(client)
    return groups


def reconcile_mcps(items, servers, secret_map):
    """Mutates a deep copy of servers; returns (new_servers, resolutions, skips).
    resolutions: {(name, client): 'sync'|'remove'}; 'sync' = regenerate from new
    canonical, 'remove' = delete from the provider. Skipped cells keep live."""
    new_servers = json.loads(json.dumps(servers))
    resolutions = {}
    skipped = []

    drifted = [
        (name, cells) for name, cells in items.items()
        if any(c["state"] in DRIFT_STATES for c in cells.values())
    ]
    for index, (name, cells) in enumerate(drifted, 1):
        entry = new_servers.get(name)
        print(f"\n[{index}/{len(drifted)}] {name} (mcp)")

        if entry is None:
            # Brand-new item: one decision per distinct version.
            for content, clients in version_groups(cells, ADDED).items():
                live = cells[clients[0]]["live"]
                print(f"  added in {', '.join(clients)} — not in canonical:")
                print("    " + render(live, secret_map))
                choice = ask("", {
                    "k": f"keep — import into servers.json, targets: {', '.join(clients)}",
                    "o": "overwrite — remove it from those provider(s)",
                    "s": "skip — leave both, ask next apply",
                })
                if choice == "k":
                    imported = reverse_substitute(live, secret_map)
                    if name in new_servers:  # a second, different version was kept
                        new_servers[name]["clients"] += clients
                        for client in clients:
                            new_servers[name][client] = imported
                    else:
                        new_servers[name] = {"clients": list(clients), "config": imported}
                    resolutions.update({(name, c): "sync" for c in clients})
                elif choice == "o":
                    resolutions.update({(name, c): "remove" for c in clients})
                else:
                    skipped.append((name, clients, ADDED))
            continue

        # Known item: modified versions first, then missing, then untargeted.
        for content, clients in version_groups(cells, MODIFIED).items():
            live = cells[clients[0]]["live"]
            desired = cells[clients[0]]["desired"]
            print(f"  modified in {', '.join(clients)}:")
            print("    canonical would generate: " + render(desired, secret_map))
            print("    live:                     " + render(live, secret_map))
            choice = ask("", {
                "p": "promote — this becomes the canonical base for every provider",
                "k": "keep — store as per-client override(s), base untouched",
                "o": "overwrite — regenerate from canonical",
                "s": "skip",
            })
            if choice == "p":
                entry["config"] = reverse_substitute(live, secret_map)
                for client in clients:
                    entry.pop(client, None)  # their change is canon now
                resolutions.update({(name, c): "sync" for c in clients})
            elif choice == "k":
                for client in clients:
                    entry[client] = reverse_substitute(cells[client]["live"], secret_map)
                resolutions.update({(name, c): "sync" for c in clients})
            elif choice == "o":
                resolutions.update({(name, c): "sync" for c in clients})
            else:
                skipped.append((name, clients, MODIFIED))

        for client, cell in cells.items():
            if cell["state"] == MISSING:
                print(f"  missing in {client} (canonical targets it)")
                choice = ask("", {
                    "o": "overwrite — re-add it from canonical",
                    "k": "keep — stop targeting this provider",
                    "s": "skip",
                })
                if choice == "o":
                    resolutions[(name, client)] = "sync"
                elif choice == "k":
                    entry["clients"] = [c for c in entry["clients"] if c != client]
                    entry.pop(client, None)
                    resolutions[(name, client)] = "remove"
                else:
                    skipped.append((name, [client], MISSING))
            elif cell["state"] == UNTARGETED:
                print(f"  present in {client}, but canonical does not target it:")
                print("    " + render(cell["live"], secret_map))
                choice = ask("", {
                    "k": "keep — target this provider in canonical",
                    "o": "overwrite — remove it from the provider",
                    "s": "skip",
                })
                if choice == "k":
                    entry["clients"].append(client)
                    imported = reverse_substitute(cell["live"], secret_map)
                    if norm(cell["live"]) != norm(entry.get("config")):
                        entry[client] = imported
                    resolutions[(name, client)] = "sync"
                elif choice == "o":
                    resolutions[(name, client)] = "remove"
                else:
                    skipped.append((name, [client], UNTARGETED))

    return new_servers, resolutions, skipped


def reconcile_skills(items, canonical, targets, home):
    """-> (ops, new_targets, skipped). ops: (action, name, agent_or_None, src, dest).
    new_targets is the (possibly rewritten) Skills/skills.json content."""
    ops = []
    skipped = []
    new_targets = {name: list(clients) for name, clients in targets.items()}

    def clients_of(name):
        return new_targets.get(name, list(SKILL_AGENTS))

    def set_clients(name, clients):
        ordered = [a for a in SKILL_AGENTS if a in clients]
        if ordered == list(SKILL_AGENTS):
            new_targets.pop(name, None)  # all agents = the sparse default
        else:
            new_targets[name] = ordered

    drifted = [
        (name, cells) for name, cells in items.items()
        if any(c["state"] in DRIFT_STATES for c in cells.values())
    ]
    for index, (name, cells) in enumerate(drifted, 1):
        header_shown = False

        def show_header():
            nonlocal header_shown
            if not header_shown:
                print(f"\n[{index}/{len(drifted)}] {name} (skill)")
                header_shown = True

        added = {a: c for a, c in cells.items() if c["state"] == ADDED}
        if added:
            show_header()
            # group identical copies -> one decision
            groups = {}
            for agent, cell in added.items():
                groups.setdefault(cell["digest"], []).append(agent)
            for digest, agents in groups.items():
                src = Path(added[agents[0]]["path"])
                print(f"  added in {', '.join(agents)}: {src}")
                choice = ask("", {
                    "k": "keep — import into canonical, target ALL agents",
                    "t": f"keep here — import, target only: {', '.join(agents)}",
                    "o": "overwrite — remove it from the agent(s) (backed up)",
                    "s": "skip",
                })
                if choice in ("k", "t"):
                    ops.append(("import", name, None, src, CANONICAL_SKILLS / name))
                    chosen = list(SKILL_AGENTS) if choice == "k" else agents
                    set_clients(name, chosen)
                    for agent in chosen:
                        ops.append(("link", name, agent, CANONICAL_SKILLS / name,
                                    home / SKILL_AGENTS[agent] / name))
                elif choice == "o":
                    for agent in agents:
                        ops.append(("remove", name, agent, None,
                                    Path(added[agent]["path"])))
                else:
                    skipped.append((name, agents, ADDED))

        missing = [a for a, c in cells.items() if c["state"] == MISSING]
        if missing and name in canonical:
            show_header()
            print(f"  missing in {', '.join(missing)} (canonical targets them)")
            choice = ask("", {
                "o": "overwrite — link from canonical",
                "k": "keep — stop targeting these agent(s) (Skills/skills.json)",
                "s": "skip",
            })
            if choice == "o":
                for agent in missing:
                    ops.append(("link", name, agent, CANONICAL_SKILLS / name,
                                home / SKILL_AGENTS[agent] / name))
            elif choice == "k":
                set_clients(name, [a for a in clients_of(name) if a not in missing])
            else:
                skipped.append((name, missing, MISSING))

        for agent, cell in cells.items():
            if cell["state"] == UNLINKED:
                show_header()
                target = home / SKILL_AGENTS[agent] / name
                if cell["identical"]:
                    print(f"  unlinked in {agent} (content identical to canonical)")
                    choice = ask("", {
                        "o": "overwrite — replace the copy with the canonical symlink",
                        "s": "skip",
                    })
                    if choice == "o":
                        ops.append(("link", name, agent, CANONICAL_SKILLS / name, target))
                    else:
                        skipped.append((name, [agent], UNLINKED))
                else:
                    print(f"  unlinked in {agent} and content DIFFERS from canonical")
                    choice = ask("", {
                        "k": "keep — pull the edited content into canonical, then relink",
                        "o": "overwrite — discard the local edits, relink (backed up)",
                        "s": "skip",
                    })
                    if choice == "k":
                        ops.append(("import", name, None, target, CANONICAL_SKILLS / name))
                        ops.append(("link", name, agent, CANONICAL_SKILLS / name, target))
                    elif choice == "o":
                        ops.append(("link", name, agent, CANONICAL_SKILLS / name, target))
                    else:
                        skipped.append((name, [agent], UNLINKED))
            elif cell["state"] == UNTARGETED:
                show_header()
                target = home / SKILL_AGENTS[agent] / name
                detail = "canonical symlink" if cell["kind"] == "link" else (
                    "real copy, identical" if cell["identical"]
                    else "real copy, content DIFFERS from canonical")
                print(f"  present in {agent} ({detail}), but canonical does not target it")
                keep_label = "keep — target this agent in Skills/skills.json"
                if cell["kind"] == "dir":
                    keep_label += (", relink the copy" if cell["identical"] else
                                   "; edits go into canonical (ALL agents), then relink")
                choice = ask("", {
                    "k": keep_label,
                    "o": "overwrite — remove it from the agent (backed up)",
                    "s": "skip",
                })
                if choice == "k":
                    set_clients(name, clients_of(name) + [agent])
                    if cell["kind"] == "dir":
                        if not cell["identical"]:
                            ops.append(("import", name, None, target,
                                        CANONICAL_SKILLS / name))
                        ops.append(("link", name, agent, CANONICAL_SKILLS / name, target))
                elif choice == "o":
                    ops.append(("remove", name, agent, None, target))
                else:
                    skipped.append((name, [agent], UNTARGETED))
            elif cell["state"] == FOREIGN:
                show_header()
                print(f"  {agent}: symlink points elsewhere ({cell['dest']}) — left alone")

    return ops, new_targets, skipped


# ---------------------------------------------------------------- preview + write

def final_mcp_state(genmod, new_servers, env, live_all, resolutions, plan_items):
    """Per client: start from live, apply resolutions, regenerate the rest.
    Skipped drift keeps its live value; everything else follows canonical —
    which is exactly where promote ripple shows up on previously in-sync cells."""
    final = {}
    for client in MCP_CLIENTS:
        state = dict(live_all[client])
        for name, entry in new_servers.items():
            desired = desired_mcp(genmod, name, entry, client, env)
            resolution = resolutions.get((name, client))
            if resolution == "remove":
                state.pop(name, None)
                continue
            if resolution == "sync":
                if desired is None:
                    state.pop(name, None)
                else:
                    state[name] = desired
                continue
            cell = plan_items.get(name, {}).get(client)
            if cell and cell["state"] in DRIFT_STATES:
                continue  # skipped: user said leave both sides alone
            if desired is not None:
                state[name] = desired
        # non-canonical items the user chose to remove (overwrite on 'added')
        for (name, target_client), action in resolutions.items():
            if target_client == client and action == "remove" and name not in new_servers:
                state.pop(name, None)
        final[client] = state
    return final


def codex_toml_section(final_codex, genmod):
    lines = [
        "# Managed by ~/Agents/Config/scripts/apply.py (canonical: MCPs/servers.json)",
        "",
    ]
    for name in sorted(final_codex, key=str.lower):
        config = {k: v for k, v in final_codex[name].items() if k in CODEX_KEYS}
        env = config.pop("env", None)
        table = name if name.replace("_", "").replace("-", "").isalnum() else json.dumps(name)
        lines.append(f"[mcp_servers.{table}]")
        for key in sorted(config):
            lines.append(f"{key} = {genmod.toml_value(config[key])}")
        lines.append("")
        if env:
            lines.append(f"[mcp_servers.{table}.env]")
            for key in sorted(env):
                lines.append(f"{key} = {genmod.toml_value(env[key])}")
            lines.append("")
    return "\n".join(lines)


def backup(path, root, stamp):
    if path.exists() or path.is_symlink():
        dest = root / "backups" / stamp / str(path).lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir() and not path.is_symlink():
            shutil.copytree(path, dest, symlinks=True)
        else:
            shutil.copy2(path, dest, follow_symlinks=False)


def write_mcp_configs(final, live_all, home, genmod, stamp):
    paths = mcp_config_paths(home)
    changed = []
    for client in MCP_CLIENTS:
        if norm(final[client]) == norm(live_all[client]):
            continue
        path = paths[client]
        backup(path, MCPS_ROOT, stamp)
        path.parent.mkdir(parents=True, exist_ok=True)
        if client == "cursor":
            path.write_text(json.dumps({"mcpServers": final[client]}, indent=2) + "\n")
        elif client in ("claude-code", "claude-desktop"):
            data = json.loads(path.read_text()) if path.exists() else {}
            data["mcpServers"] = final[client]
            path.write_text(json.dumps(data, indent=2) + "\n")
        else:  # codex: replace only the [mcp_servers.*] tables
            import re
            content = path.read_text() if path.exists() else ""
            content = re.sub(
                r"\n\[mcp_servers(?:\.[^\]\n]+)?\][\s\S]*?(?=\n\[[^\]\n]+\]|\Z)",
                "", content,
            )
            content = content.rstrip() + "\n\n" + codex_toml_section(final[client], genmod).rstrip() + "\n"
            path.write_text(content)
        changed.append(client)
    return changed


def apply_skill_ops(ops, stamp):
    applied = []
    for action, name, agent, src, dest in ops:
        if action == "import":
            if dest.exists():
                backup(dest, SKILLS_ROOT, stamp)
                shutil.rmtree(dest)
            shutil.copytree(src, dest, symlinks=True,
                            ignore=shutil.ignore_patterns(".DS_Store"))
        elif action == "link":
            if dest.is_symlink() and dest.resolve() == src.resolve():
                continue
            if dest.exists() or dest.is_symlink():
                backup(dest, SKILLS_ROOT, stamp)
                if dest.is_dir() and not dest.is_symlink():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(src)
        elif action == "remove":
            backup(dest, SKILLS_ROOT, stamp)
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        applied.append((action, name, agent))
    return applied


# ---------------------------------------------------------------- main

def emit_json_plan(mcp_items, skill_items, secret_map):
    def cells_out(items, mask_live):
        out = {}
        for name, cells in items.items():
            row = {}
            for client, cell in cells.items():
                slim = {"state": cell["state"]}
                if mask_live and cell.get("live") is not None:
                    slim["live"] = reverse_substitute(cell["live"], secret_map)
                row[client] = slim
            out[name] = row
        return out

    print(json.dumps({
        "mcps": cells_out(mcp_items, mask_live=True),
        "skills": cells_out(skill_items, mask_live=False),
    }, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Reconciling apply for Agent-config")
    parser.add_argument("--plan", action="store_true", help="show drift and exit")
    parser.add_argument("--json", action="store_true", help="with --plan: JSON output")
    parser.add_argument("--only", choices=["mcps", "skills"], help="limit scope")
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    args = parser.parse_args()

    genmod = load_genmod()
    servers = genmod.load_servers()
    env = genmod.load_env()
    secret_map = build_secret_map(env)
    home = args.home

    skill_targets = load_skill_targets()

    mcp_items, live_all = ({}, {c: {} for c in MCP_CLIENTS})
    skill_items, canonical_skills = ({}, {})
    if args.only != "skills":
        mcp_items, live_all = plan_mcps(genmod, servers, env, home)
    if args.only != "mcps":
        skill_items, canonical_skills = plan_skills(home, skill_targets)

    if args.plan and args.json:
        emit_json_plan(
            {n: c for n, c in mcp_items.items()
             if any(x["state"] != IN_SYNC for x in c.values())},
            skill_items, secret_map,
        )
        return

    mcp_drift = print_matrix("MCP DRIFT PLAN", mcp_items, MCP_CLIENTS) \
        if args.only != "skills" else {}
    skill_drift = print_matrix("SKILL DRIFT PLAN", skill_items, list(SKILL_AGENTS)) \
        if args.only != "mcps" else {}

    if not mcp_drift and not skill_drift:
        print("\nEverything in sync. Nothing to do.")
        return
    if args.plan:
        return

    # ---- reconcile
    new_servers = servers
    resolutions = {}
    mcp_skipped = []
    if mcp_drift:
        new_servers, resolutions, mcp_skipped = reconcile_mcps(
            mcp_drift, servers, secret_map)
    skill_ops, new_skill_targets, skill_skipped = ([], skill_targets, [])
    if skill_drift:
        skill_ops, new_skill_targets, skill_skipped = reconcile_skills(
            skill_drift, canonical_skills, skill_targets, home)

    # ---- effect preview (recomputed rows, including promote ripple)
    # out-of-scope MCPs (--only skills) must stay exactly live: never regenerate
    final = final_mcp_state(genmod, new_servers, env, live_all, resolutions, mcp_items) \
        if args.only != "skills" else live_all
    print("\nEFFECT PREVIEW")
    any_change = False
    for client in MCP_CLIENTS:
        before, after = live_all[client], final[client]
        for name in sorted(set(before) | set(after), key=str.lower):
            old, new = before.get(name), after.get(name)
            if norm(old) == norm(new):
                continue
            any_change = True
            action = "add" if old is None else "remove" if new is None else "rewrite"
            print(f"  {client}: {action} {name}")
            if new is not None:
                print(f"    -> {render(new, secret_map)}")
    if norm(new_servers) != norm(servers):
        any_change = True
        print("  servers.json: updated (review with git diff after apply)")
    for action, name, agent, src, dest in skill_ops:
        target = f" @ {agent}" if agent else ""
        print(f"  skill {action}: {name}{target}")
        any_change = True
    if new_skill_targets != skill_targets:
        any_change = True
        print("  Skills/skills.json: targeting updated")
        for name in sorted(set(skill_targets) | set(new_skill_targets), key=str.lower):
            old = skill_targets.get(name, list(SKILL_AGENTS))
            new = new_skill_targets.get(name, list(SKILL_AGENTS))
            if old != new:
                print(f"    {name}: {', '.join(old)} -> {', '.join(new) or '(no agents)'}")
    for name, clients, state in mcp_skipped + skill_skipped:
        print(f"  skipped: {name} ({state} in {', '.join(clients)}) — will re-ask next apply")
    if not any_change:
        print("  no writes needed.")
        return

    answer = input("\nconfirm? (y/N) ").strip().lower()
    if answer != "y":
        print("aborted. nothing written.")
        return

    # ---- write
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if norm(new_servers) != norm(servers):
        backup(SERVERS_PATH, MCPS_ROOT, stamp)
        SERVERS_PATH.write_text(
            json.dumps({"version": 1, "servers": new_servers}, indent=2) + "\n")
    changed_clients = write_mcp_configs(final, live_all, home, genmod, stamp)
    applied_skills = apply_skill_ops(skill_ops, stamp)
    if new_skill_targets != skill_targets:
        backup(SKILLS_MANIFEST, SKILLS_ROOT, stamp)
        write_skill_targets(new_skill_targets)

    print("\nSUMMARY")
    if norm(new_servers) != norm(servers):
        print(f"  canonical: servers.json updated — review: git -C {CONFIG_ROOT} diff")
    if new_skill_targets != skill_targets:
        print("  canonical: Skills/skills.json updated (per-skill targeting)")
    if changed_clients:
        print(f"  providers rewritten: {', '.join(changed_clients)}")
    for action, name, agent in applied_skills:
        print(f"  skill {action}: {name}" + (f" @ {agent}" if agent else ""))
    print(f"  backups: MCPs/backups/{stamp} and Skills/backups/{stamp} (as needed)")


if __name__ == "__main__":
    main()

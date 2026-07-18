#!/usr/bin/env python3
"""Reconciling apply for Agent-config (AC-1..AC-3).

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
detect     secrets from ~/.config/agents-config/mcp.env (legacy MCPs/.env.local)
           are never written into servers.json --
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
instructions (AC-3)
           Each provider file renders as the concatenation of the active
           profile's Instructions/fragments/* plus an optional per-provider
           `extra` fragment (Instructions/instructions.yaml, version 2):
             targets:
               claude-code:
                 path: ~/.claude/CLAUDE.md
                 legacy: ~/CLAUDE.md              # old path; apply migrates it
                 extra: providers/claude-code.md  # appended after fragments
           Same verbs as MCPs. Promote maps each live diff hunk back to the
           fragment it falls in and edits that source (rippling to every
           provider that renders it); insertions on a fragment boundary prompt
           for which side, and hunks rewriting across a boundary block promote.
           `keep` diverges the provider onto a whole-file providers/<name>.md
           `source`, opting it out of fragment rendering. v1 manifests
           (default_source) still read fine. `legacy` migration writes the new
           path and backs up + removes the old one so rules never load twice.

Usage (via scripts/agents-config, which picks a Python >= 3.11):
  agents-config apply              interactive reconcile + apply
  agents-config plan               print the drift matrix and exit (read-only)
  agents-config plan --json        machine-readable plan
  agents-config apply --only mcps  limit scope (or: skills / instructions)

--home and --platform are test seams: they retarget every home-relative path
and the platform check without touching the real home. The bare --plan flag is
kept for back-compat with `apply.py --plan`.
"""

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tomllib
from datetime import datetime
from pathlib import Path

CONFIG_ROOT = Path(__file__).resolve().parents[1]
PROFILES_PATH = CONFIG_ROOT / "profiles.yaml"
MCPS_ROOT = CONFIG_ROOT / "MCPs"
SERVERS_PATH = MCPS_ROOT / "servers.json"
SKILLS_ROOT = CONFIG_ROOT / "Skills"
CANONICAL_SKILLS = SKILLS_ROOT / "Skills"
SKILLS_MANIFEST = SKILLS_ROOT / "skills.json"
INSTRUCTIONS_ROOT = CONFIG_ROOT / "Instructions"
INSTRUCTIONS_MANIFEST = INSTRUCTIONS_ROOT / "instructions.yaml"

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
MIGRATE = "migrate"        # content in sync, but a legacy path still loads
DRIFT_STATES = {ADDED, MODIFIED, MISSING, UNLINKED, UNTARGETED, MIGRATE}


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
    """value -> ${VAR}, for masking output and reverse-substituting imports.
    Longest values first so ${CODE_ROOT} wins over its ${HOME} prefix."""
    return {
        value: "${%s}" % name
        for name, value in sorted(env.items(), key=lambda kv: -len(kv[1]))
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


# ---------------------------------------------------------------- MCP scope

SERVER_KEYS = {"clients", "config", "platforms", "profiles", "requires",
               "security", "setup"}
REQUIRES_KEYS = {"executables", "env", "paths"}
HARDCODED_PATHS = ("/Users/", "/home/", "/opt/homebrew")


def path_vars(env, home, profile):
    """Overlay ${HOME}/${CODE_ROOT} onto the secrets env. They ride the same
    substitution pipeline forward (rendering) and the same reverse map back
    (promote writes ${HOME}, never a literal /Users/... path)."""
    env = dict(env)
    env["HOME"] = str(home)
    code_root = profile.get("code_root", "~/Code")
    env["CODE_ROOT"] = str(home / code_root[2:]) \
        if code_root.startswith("~/") else code_root
    return env


def validate_servers(servers, profiles):
    """Hard stop on schema violations: a bad servers.json must never
    half-apply on some machine and silently no-op on another."""
    errors = []
    allowed = SERVER_KEYS | set(MCP_CLIENTS)
    for name, entry in servers.items():
        errors += [f"{name}: unknown key {key!r}" for key in entry
                   if key not in allowed]
        errors += [f"{name}: unknown client {c!r}"
                   for c in entry.get("clients", []) if c not in MCP_CLIENTS]
        errors += [f"{name}: unknown platform {p!r}"
                   for p in entry.get("platforms", [])
                   if p not in ("darwin", "linux")]
        errors += [f"{name}: unknown profile {p!r}"
                   for p in entry.get("profiles", []) if p not in profiles]
        errors += [f"{name}: requires: unknown key {key!r}"
                   for key in entry.get("requires", {})
                   if key not in REQUIRES_KEYS]
        blob = json.dumps([entry.get("config"),
                           *(entry.get(c) for c in MCP_CLIENTS)])
        errors += [f"{name}: hardcoded path ({prefix}...) — use "
                   "${HOME} or ${CODE_ROOT}"
                   for prefix in HARDCODED_PATHS if prefix in blob]
    if errors:
        sys.exit("error: MCPs/servers.json failed validation:\n  "
                 + "\n  ".join(errors))


def partition_servers(genmod, servers, profile, platform, env):
    """-> (in_scope, out_of_scope {name: reason}). Out-of-scope servers are
    invisible to plan and apply: their live entries are left exactly as found,
    never flagged as strays, never regenerated."""
    in_scope, out = {}, {}
    for name, entry in servers.items():
        platforms = entry.get("platforms")
        allowed_profiles = entry.get("profiles")
        if platforms and platform not in platforms:
            out[name] = f"not for {platform} (platforms: {', '.join(platforms)})"
        elif allowed_profiles is not None and profile["name"] not in allowed_profiles:
            out[name] = f"not enabled for profile {profile['name']}"
        elif allowed_profiles is None and profile.get("mcps") == "default-deny":
            out[name] = f"profile {profile['name']} denies MCPs by default"
        else:
            requires = entry.get("requires", {})
            missing = [f"executable {exe!r}"
                       for exe in requires.get("executables", [])
                       if not shutil.which(exe)]
            missing += [f"env var {var}" for var in requires.get("env", [])
                        if not (env.get(var) or os.environ.get(var))]
            missing += [f"path {p}" for p in requires.get("paths", [])
                        if not Path(genmod.substitute(p, env)).exists()]
            if missing:
                out[name] = "missing " + ", ".join(missing)
            else:
                in_scope[name] = entry
    return in_scope, out


def plan_mcps(genmod, servers, env, home, ignore=frozenset()):
    """-> {name: {client: cell}} where cell = {state, live, desired}."""
    paths = mcp_config_paths(home)
    live_all = {client: read_live_mcps(client, path) for client, path in paths.items()}

    items = {}
    names = set(servers)
    for live in live_all.values():
        names |= set(live)
    names -= set(ignore)

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


# ---------------------------------------------------------------- fetch: instructions

def load_yaml_subset(text, origin="yaml"):
    """Minimal YAML: nested mappings of scalar strings and inline [a, b] lists,
    plus comments. That is all our manifests need, and it keeps the repo
    dependency-free."""
    root = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        key, sep, value = line.strip().partition(":")
        if not sep:
            sys.exit(f"error: {origin}: cannot parse line: {raw!r}")
        value = value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value == "":
            parent[key] = {}
            stack.append((indent, parent[key]))
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            parent[key] = [item.strip().strip("'\"")
                           for item in inner.split(",")] if inner else []
        else:
            parent[key] = value.strip("'\"")
    return root


# ---------------------------------------------------------------- profiles

POLICY_VALUES = ("default-allow", "default-deny")


def config_dir(home):
    return home / ".config" / "agents-config"


def state_dir(home):
    return home / ".local" / "state" / "agents-config"


def load_local_config(home):
    path = config_dir(home) / "config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        sys.exit(f"error: cannot parse {path}: {exc}")


def private_mkdir(path):
    """mkdir -p with 0700 on every directory we create (never loosens existing)."""
    missing = []
    probe = path
    while not probe.exists():
        missing.append(probe)
        probe = probe.parent
    path.mkdir(parents=True, exist_ok=True)
    for created in missing:
        os.chmod(created, 0o700)


def save_local_config(home, updates):
    path = config_dir(home) / "config.json"
    data = load_local_config(home)
    data.update(updates)
    private_mkdir(path.parent)
    path.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(path, 0o600)


def load_profiles():
    if not PROFILES_PATH.exists():
        sys.exit(f"error: {PROFILES_PATH} not found")
    data = load_yaml_subset(PROFILES_PATH.read_text(), origin="profiles.yaml")
    return data.get("profiles") or {}


def resolve_profile(args, profiles):
    name = args.profile or load_local_config(args.home).get("profile")
    available = ", ".join(sorted(profiles)) or "none defined"
    if not name:
        sys.exit("error: no profile selected. Pass --profile <name> "
                 f"(available: {available}); apply saves the choice "
                 "in ~/.config/agents-config/config.json for later runs.")
    if name not in profiles:
        sys.exit(f"error: unknown profile {name!r} (available: {available})")
    profile = dict(profiles[name])
    profile["name"] = name
    if profile.get("platform") not in ("darwin", "linux"):
        sys.exit(f"error: profiles.yaml: {name}: platform must be darwin or linux")
    if profile["platform"] != args.platform:
        sys.exit(f"error: profile {name!r} is for {profile['platform']}, "
                 f"but this host is {args.platform}")
    if profile.get("mode", "read-write") not in ("read-write", "read-only"):
        sys.exit(f"error: profiles.yaml: {name}: mode must be read-write or read-only")
    for policy in ("mcps", "skills"):
        if profile.get(policy, "default-allow") not in POLICY_VALUES:
            sys.exit(f"error: profiles.yaml: {name}: {policy} must be one of: "
                     + ", ".join(POLICY_VALUES))
    if not isinstance(profile.get("fragments", []), list):
        sys.exit(f"error: profiles.yaml: {name}: fragments must be a [list]")
    return profile


def run_preflight(profile):
    for check in profile.get("preflight", []):
        if check == "not-root":
            if os.geteuid() == 0:
                sys.exit(f"error: preflight {check}: refusing to run as root")
        elif check == "no-privileged-groups":
            import grp
            names = set()
            for gid in os.getgroups():
                try:
                    names.add(grp.getgrgid(gid).gr_name)
                except KeyError:
                    pass
            privileged = names & {"root", "sudo", "wheel", "admin"}
            if privileged:
                sys.exit(f"error: preflight {check}: account belongs to "
                         f"privileged group(s): {', '.join(sorted(privileged))}")
        else:
            sys.exit(f"error: profiles.yaml: unknown preflight check {check!r}")


def effective_mode(profile):
    """Profile mode, downgraded to read-only when the checkout is not ours to
    write. Read-only may sync canonical -> home but never promote/import."""
    mode = profile.get("mode", "read-write")
    if mode == "read-write" and not os.access(CONFIG_ROOT, os.W_OK):
        print("note: checkout is not writable; running in read-only mode",
              file=sys.stderr)
        mode = "read-only"
    return mode


def load_instruction_targets():
    """-> (targets, default_source). v2 manifests return default_source=None;
    entries may carry source/extra/legacy. v1 manifests (default_source set)
    keep the old whole-file rendering for every entry."""
    if not INSTRUCTIONS_MANIFEST.exists():
        return {}, None
    data = load_yaml_subset(INSTRUCTIONS_MANIFEST.read_text(),
                            origin="instructions.yaml")
    v1 = "default_source" in data or data.get("version") == "1"
    default_source = data.get("default_source", "AGENTS.md") if v1 else None
    targets = {}
    for provider, entry in (data.get("targets") or {}).items():
        if not isinstance(entry, dict) or "path" not in entry:
            sys.exit(f"error: instructions.yaml: {provider}: needs a path")
        target = {"path": entry["path"]}
        if v1:
            target["source"] = entry.get("source", default_source)
        else:
            for key in ("source", "extra", "legacy"):
                if key in entry:
                    target[key] = entry[key]
        targets[provider] = target
    return targets, default_source


def write_instruction_targets(targets):
    lines = [
        "# Which instructions file belongs to which provider.",
        "# Rendering: active profile fragments + optional per-provider `extra`;",
        "# an explicit `source` opts the provider out of fragment rendering.",
        "# `legacy` is an old live path that apply migrates to `path`.",
        "# NOTE: hand-written comments below this header are lost when apply",
        "# rewrites this file.",
        "version: 2",
        "targets:",
    ]
    for provider in sorted(targets, key=str.lower):
        entry = targets[provider]
        lines.append(f"  {provider}:")
        lines.append(f"    path: {entry['path']}")
        for key in ("legacy", "extra", "source"):
            if entry.get(key):
                lines.append(f"    {key}: {entry[key]}")
    INSTRUCTIONS_MANIFEST.write_text("\n".join(lines) + "\n")


def instruction_path(path_str, home):
    return home / path_str[2:] if path_str.startswith("~/") else Path(path_str)


def instruction_sources(entry, profile, default_source):
    """-> ordered source relpaths (under Instructions/) whose concatenation
    renders this provider. A diverged provider has exactly one."""
    if entry.get("source"):
        return [entry["source"]]
    if default_source:  # v1 manifest
        return [default_source]
    sources = [f"fragments/{name}" for name in profile.get("fragments", [])]
    if entry.get("extra"):
        sources.append(entry["extra"])
    if not sources:
        sys.exit(f"error: profile {profile.get('name')!r} renders no "
                 "instruction fragments")
    return sources


def render_instruction(relpaths, overrides=None):
    """-> (text, spans). Fragments are joined by exactly one blank separator
    line, so rendering is a pure concatenation: every rendered line maps back
    to one source file, and spans (start, end, relpath) record the mapping."""
    parts = []
    for relpath in relpaths:
        if overrides is not None and relpath in overrides:
            content = overrides[relpath]
        else:
            path = INSTRUCTIONS_ROOT / relpath
            if not path.exists():
                sys.exit(f"error: instructions source Instructions/{relpath} "
                         "does not exist")
            content = path.read_text()
        parts.append(content.rstrip("\n"))
    spans = []
    line = 0
    for relpath, part in zip(relpaths, parts):
        count = part.count("\n") + 1
        spans.append((line, line + count, relpath))
        line += count + 1  # the separator blank line
    return "\n\n".join(parts) + "\n", spans


def plan_instructions(targets, home, profile, default_source):
    """-> {provider: cell}. live = what reconcile diffs against (the legacy
    file's content when only it exists); target_live = content at the real
    target path. MIGRATE = content is right but the legacy file still loads."""
    items = {}
    for provider, entry in targets.items():
        relpaths = instruction_sources(entry, profile, default_source)
        desired, spans = render_instruction(relpaths)
        path = instruction_path(entry["path"], home)
        target_live = path.read_text() if path.exists() else None
        legacy = instruction_path(entry["legacy"], home) if entry.get("legacy") else None
        legacy_live = legacy.read_text() if legacy and legacy.exists() else None

        live = target_live if target_live is not None else legacy_live
        if live is None:
            state = MISSING
        elif live != desired:
            state = MODIFIED
        elif legacy_live is not None:
            state = MIGRATE
        else:
            state = IN_SYNC
        items[provider] = {
            "state": state, "live": live, "desired": desired, "path": path,
            "target_live": target_live,
            "legacy": legacy if legacy_live is not None else None,
            "spans": spans, "sources": relpaths,
            "source": relpaths[0] if len(relpaths) == 1 else "fragments",
        }
    return items


def print_instructions_plan(items):
    drifted = {p: c for p, c in items.items() if c["state"] != IN_SYNC}
    print(f"\nINSTRUCTIONS DRIFT PLAN — {len(drifted)} file(s) need attention")
    if not drifted:
        return drifted
    width = max(len(p) for p in drifted) + 2
    pwidth = max(len(str(c["path"])) for c in drifted.values()) + 2
    for provider, cell in drifted.items():
        print("  " + provider.ljust(width) + str(cell["path"]).ljust(pwidth)
              + STATE_MARK[cell["state"]])
    return drifted


def map_hunks_to_sources(old_lines, live_lines, spans):
    """-> (edits, boundary_inserts, blocked).
    edits: {relpath: [(lo, hi, replacement_lines)]} in source-local coords —
      hunks that fall entirely within one fragment promote automatically.
    boundary_inserts: [(prev_relpath, next_relpath, lines)] pure insertions
      between fragments — the caller asks which side they belong to.
    blocked: hunks rewriting lines across a fragment boundary — promote is
      unavailable for the whole edit when any exist."""
    edits, boundary, blocked = {}, [], []
    matcher = difflib.SequenceMatcher(a=old_lines, b=live_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        repl = live_lines[j1:j2]
        if i1 == i2:  # pure insertion at old-render position i1
            inside = next(((s, e, rel) for s, e, rel in spans if s < i1 < e), None)
            if inside:
                edits.setdefault(inside[2], []).append(
                    (i1 - inside[0], i1 - inside[0], repl))
            else:
                prev = next((rel for s, e, rel in reversed(spans) if e <= i1), None)
                nxt = next((rel for s, e, rel in spans if s >= i1), None)
                boundary.append((prev, nxt, repl))
            continue
        span = next(((s, e, rel) for s, e, rel in spans if s <= i1 and i2 <= e), None)
        if span:
            edits.setdefault(span[2], []).append((i1 - span[0], i2 - span[0], repl))
        else:
            blocked.append((i1, i2, repl))
    return edits, boundary, blocked


def apply_source_edits(relpath, source_edits, overrides):
    """Apply source-local line edits on top of any pending override content."""
    base = overrides.get(relpath)
    if base is None:
        base = (INSTRUCTIONS_ROOT / relpath).read_text()
    lines = base.rstrip("\n").split("\n")
    for lo, hi, repl in sorted(source_edits, reverse=True):
        lines[lo:hi] = repl
    overrides[relpath] = "\n".join(lines) + "\n"


def reconcile_instructions(items, targets, secret_map, read_only=False):
    """-> (new_targets, source_updates, resolutions, skipped).
    source_updates: {relpath under Instructions/: new content}. A provider
    resolved \'sync\' gets rewritten at its target path; a live legacy file is
    backed up and removed in the same apply (see final_instructions)."""
    new_targets = {p: dict(e) for p, e in targets.items()}
    source_updates = {}
    resolutions = {}
    skipped = []

    drifted = {p: c for p, c in items.items() if c["state"] != IN_SYNC}
    groups = {}  # identical live edits over the same sources -> one decision
    for provider, cell in drifted.items():
        if cell["state"] == MODIFIED:
            groups.setdefault((tuple(cell["sources"]), cell["live"]), []).append(provider)
    total = len(groups) + sum(
        1 for c in drifted.values() if c["state"] in (MISSING, MIGRATE))
    index = 0

    for (sources, live), providers in groups.items():
        index += 1
        cell = items[providers[0]]
        label = ", ".join(f"Instructions/{s}" for s in sources)
        print(f"\n[{index}/{total}] instructions — modified in {', '.join(providers)} "
              f"(rendered from: {label})")
        old_lines = cell["desired"].splitlines()
        live_lines = live.splitlines()
        diff = list(difflib.unified_diff(
            old_lines, live_lines,
            fromfile="canonical render", tofile="live", lineterm=""))
        for line in diff[:80]:
            print("    " + reverse_substitute(line, secret_map))
        if len(diff) > 80:
            print(f"    ... ({len(diff) - 80} more diff lines)")

        edits, boundary, blocked = map_hunks_to_sources(
            old_lines, live_lines, cell["spans"])
        choices = {
            "p": "promote — fold the live edits back into the source file(s) "
                 "(ripples to every provider rendering them)",
            "k": "keep — diverge: store the whole live file as a per-provider source",
            "o": "overwrite — regenerate from canonical",
            "s": "skip",
        }
        if blocked:
            choices.pop("p")
            print("    (promote unavailable: an edit rewrites lines across a "
                  "fragment boundary — split the edit or diverge)")
        choice = ask("", filter_choices(choices, read_only))
        if choice == "p":
            for prev, nxt, repl in boundary:
                print("    inserted lines sit on the boundary between two fragments:")
                for line in repl[:10]:
                    print("      + " + reverse_substitute(line, secret_map))
                options = {}
                if prev:
                    options["a"] = f"append to Instructions/{prev}"
                if nxt:
                    options["b"] = f"prepend to Instructions/{nxt}"
                options["s"] = "skip this inserted block"
                picked = ask("", options)
                if picked == "a":
                    edits.setdefault(prev, []).append((sys.maxsize, sys.maxsize, repl))
                elif picked == "b":
                    edits.setdefault(nxt, []).append((0, 0, repl))
            for relpath, source_edits in edits.items():
                apply_source_edits(relpath, source_edits, source_updates)
            resolutions.update({p: "sync" for p in providers})
        elif choice == "k":
            for provider in providers:
                relpath = f"providers/{provider}.md"
                source_updates[relpath] = live
                new_targets[provider]["source"] = relpath
                new_targets[provider].pop("extra", None)
                resolutions[provider] = "sync"
        elif choice == "o":
            resolutions.update({p: "sync" for p in providers})
        else:
            skipped.append(("instructions", providers, MODIFIED))

    for provider, cell in drifted.items():
        if cell["state"] == MISSING:
            index += 1
            print(f"\n[{index}/{total}] instructions — missing in {provider} "
                  f"({cell['path']})")
            choice = ask("", filter_choices({
                "o": "overwrite — write it from canonical",
                "k": "keep — stop targeting this provider (instructions.yaml)",
                "s": "skip",
            }, read_only))
            if choice == "o":
                resolutions[provider] = "sync"
            elif choice == "k":
                new_targets.pop(provider, None)
            else:
                skipped.append(("instructions", [provider], MISSING))
        elif cell["state"] == MIGRATE:
            index += 1
            print(f"\n[{index}/{total}] instructions — {provider}: content in sync "
                  f"but {cell['legacy']} still loads (target: {cell['path']})")
            choice = ask("", {
                "o": f"migrate — write {cell['path']}, back up and remove "
                     f"{cell['legacy']}",
                "s": "skip",
            })
            if choice == "o":
                resolutions[provider] = "sync"
            else:
                skipped.append(("instructions", [provider], MIGRATE))

    return new_targets, source_updates, resolutions, skipped


def final_instructions(items, new_targets, source_updates, resolutions, home,
                       profile, default_source):
    """-> (writes, removals). writes: (provider, path, content); removals:
    (provider, legacy_path) for migrated legacy files. Promote ripple happens
    here: desired is re-rendered with source_updates layered on top."""
    writes, removals = [], []
    for provider, entry in new_targets.items():
        relpaths = instruction_sources(entry, profile, default_source)
        if not all((INSTRUCTIONS_ROOT / r).exists() or r in source_updates
                   for r in relpaths):
            continue
        desired, _ = render_instruction(relpaths, overrides=source_updates)
        cell = items.get(provider)
        if cell and cell["state"] != IN_SYNC and provider not in resolutions:
            continue  # skipped: leave both sides alone
        target_live = cell["target_live"] if cell else None
        path = cell["path"] if cell else instruction_path(entry["path"], home)
        if target_live != desired:
            writes.append((provider, path, desired))
        if cell and cell.get("legacy") and resolutions.get(provider) == "sync":
            removals.append((provider, cell["legacy"]))
    return writes, removals


# ---------------------------------------------------------------- plan output

STATE_MARK = {
    IN_SYNC: "in sync",
    ADDED: "+ added",
    MODIFIED: "~ modified",
    MISSING: "x missing",
    UNLINKED: "! unlinked",
    UNTARGETED: "+ untargeted",
    FOREIGN: "> foreign",
    MIGRATE: "> migrate",
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

def filter_choices(choices, read_only):
    """Read-only mode may sync or skip, never promote/keep/import: every verb
    that would rewrite canonical files (p/k/t) is removed from the menu."""
    if not read_only:
        return choices
    return {key: label for key, label in choices.items() if key in ("o", "s")}


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


def reconcile_mcps(items, servers, secret_map, read_only=False):
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
                choice = ask("", filter_choices({
                    "k": f"keep — import into servers.json, targets: {', '.join(clients)}",
                    "o": "overwrite — remove it from those provider(s)",
                    "s": "skip — leave both, ask next apply",
                }, read_only))
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
            choice = ask("", filter_choices({
                "p": "promote — this becomes the canonical base for every provider",
                "k": "keep — store as per-client override(s), base untouched",
                "o": "overwrite — regenerate from canonical",
                "s": "skip",
            }, read_only))
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
                choice = ask("", filter_choices({
                    "o": "overwrite — re-add it from canonical",
                    "k": "keep — stop targeting this provider",
                    "s": "skip",
                }, read_only))
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
                choice = ask("", filter_choices({
                    "k": "keep — target this provider in canonical",
                    "o": "overwrite — remove it from the provider",
                    "s": "skip",
                }, read_only))
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


def reconcile_skills(items, canonical, targets, home, read_only=False):
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
                choice = ask("", filter_choices({
                    "k": "keep — import into canonical, target ALL agents",
                    "t": f"keep here — import, target only: {', '.join(agents)}",
                    "o": "overwrite — remove it from the agent(s) (backed up)",
                    "s": "skip",
                }, read_only))
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
            choice = ask("", filter_choices({
                "o": "overwrite — link from canonical",
                "k": "keep — stop targeting these agent(s) (Skills/skills.json)",
                "s": "skip",
            }, read_only))
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
                    choice = ask("", filter_choices({
                        "o": "overwrite — replace the copy with the canonical symlink",
                        "s": "skip",
                    }, read_only))
                    if choice == "o":
                        ops.append(("link", name, agent, CANONICAL_SKILLS / name, target))
                    else:
                        skipped.append((name, [agent], UNLINKED))
                else:
                    print(f"  unlinked in {agent} and content DIFFERS from canonical")
                    choice = ask("", filter_choices({
                        "k": "keep — pull the edited content into canonical, then relink",
                        "o": "overwrite — discard the local edits, relink (backed up)",
                        "s": "skip",
                    }, read_only))
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
                choice = ask("", filter_choices({
                    "k": keep_label,
                    "o": "overwrite — remove it from the agent (backed up)",
                    "s": "skip",
                }, read_only))
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


def backup(path, home, stamp):
    """Copy path into ~/.local/state/agents-config/backups/<stamp>/ (0700 dirs:
    backed-up provider configs carry resolved secrets)."""
    if path.exists() or path.is_symlink():
        dest = state_dir(home) / "backups" / stamp / str(path).lstrip("/")
        private_mkdir(dest.parent)
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
        backup(path, home, stamp)
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


def apply_skill_ops(ops, home, stamp):
    applied = []
    for action, name, agent, src, dest in ops:
        if action == "import":
            if dest.exists():
                backup(dest, home, stamp)
                shutil.rmtree(dest)
            shutil.copytree(src, dest, symlinks=True,
                            ignore=shutil.ignore_patterns(".DS_Store"))
        elif action == "link":
            if dest.is_symlink() and dest.resolve() == src.resolve():
                continue
            if dest.exists() or dest.is_symlink():
                backup(dest, home, stamp)
                if dest.is_dir() and not dest.is_symlink():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(src)
        elif action == "remove":
            backup(dest, home, stamp)
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        applied.append((action, name, agent))
    return applied


# ---------------------------------------------------------------- main

def emit_json_plan(mcp_items, skill_items, instr_items, secret_map, profile_name):
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
        "profile": profile_name,
        "mcps": cells_out(mcp_items, mask_live=True),
        "skills": cells_out(skill_items, mask_live=False),
        "instructions": {
            provider: {"state": cell["state"], "path": str(cell["path"]),
                       "source": cell["source"]}
            for provider, cell in instr_items.items()
        },
    }, indent=2))


def detect_platform():
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Reconciling apply for Agent-config")
    parser.add_argument("command", nargs="?", choices=["plan", "apply"],
                        help="plan: show drift and exit (read-only); apply: reconcile")
    parser.add_argument("--plan", action="store_true", help="alias for the plan command")
    parser.add_argument("--json", action="store_true", help="with plan: JSON output")
    parser.add_argument("--only", choices=["mcps", "skills", "instructions"],
                        help="limit scope")
    parser.add_argument("--profile", help="profile from profiles.yaml "
                        "(saved on apply; required on first run)")
    # test seams: retarget the home directory and platform without a real home
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    parser.add_argument("--platform", choices=["darwin", "linux"],
                        default=detect_platform(), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.plan = args.plan or args.command == "plan"
    return args


def main():
    args = parse_args()
    in_scope = lambda section: args.only in (None, section)

    profiles = load_profiles()
    profile = resolve_profile(args, profiles)
    run_preflight(profile)
    read_only = effective_mode(profile) == "read-only"
    if not args.plan:
        save_local_config(args.home, {"profile": profile["name"]})

    genmod = load_genmod()
    servers = genmod.load_servers()
    home = args.home
    env = path_vars(genmod.load_env(), home, profile)
    secret_map = build_secret_map(env)
    validate_servers(servers, profiles)
    servers_in_scope, out_of_scope = partition_servers(
        genmod, servers, profile, args.platform, env)

    skill_targets = load_skill_targets()
    instr_targets, default_source = load_instruction_targets()

    mcp_items, live_all = ({}, {c: {} for c in MCP_CLIENTS})
    skill_items, canonical_skills = ({}, {})
    instr_items = {}
    if in_scope("mcps"):
        mcp_items, live_all = plan_mcps(genmod, servers_in_scope, env, home,
                                        ignore=out_of_scope)
        if genmod.MISSING_PLACEHOLDERS:
            names = ", ".join(sorted(genmod.MISSING_PLACEHOLDERS))
            message = (f"unresolved placeholder(s): {names} — add them to "
                       "~/.config/agents-config/mcp.env")
            if args.plan:
                print("warning: " + message, file=sys.stderr)
            else:
                sys.exit("error: " + message)
    if in_scope("skills"):
        skill_items, canonical_skills = plan_skills(home, skill_targets)
    if in_scope("instructions"):
        instr_items = plan_instructions(instr_targets, home, profile, default_source)

    if args.plan and args.json:
        emit_json_plan(
            {n: c for n, c in mcp_items.items()
             if any(x["state"] != IN_SYNC for x in c.values())},
            skill_items, instr_items, secret_map, profile["name"],
        )
        return

    print(f"profile: {profile['name']} ({args.platform}, "
          f"{'read-only' if read_only else 'read-write'})")
    mcp_drift = print_matrix("MCP DRIFT PLAN", mcp_items, MCP_CLIENTS) \
        if in_scope("mcps") else {}
    if in_scope("mcps") and out_of_scope:
        for name in sorted(out_of_scope, key=str.lower):
            print(f"  out of scope: {name} — {out_of_scope[name]}")
    skill_drift = print_matrix("SKILL DRIFT PLAN", skill_items, list(SKILL_AGENTS)) \
        if in_scope("skills") else {}
    instr_drift = print_instructions_plan(instr_items) \
        if in_scope("instructions") else {}

    if not mcp_drift and not skill_drift and not instr_drift:
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
            mcp_drift, servers, secret_map, read_only)
    skill_ops, new_skill_targets, skill_skipped = ([], skill_targets, [])
    if skill_drift:
        skill_ops, new_skill_targets, skill_skipped = reconcile_skills(
            skill_drift, canonical_skills, skill_targets, home, read_only)
    new_instr_targets, source_updates, instr_resolutions, instr_skipped = \
        (instr_targets, {}, {}, [])
    if instr_drift:
        new_instr_targets, source_updates, instr_resolutions, instr_skipped = \
            reconcile_instructions(instr_items, instr_targets, secret_map, read_only)

    # ---- effect preview (recomputed rows, including promote ripple)
    # out-of-scope MCPs must stay exactly live: never regenerate
    final = final_mcp_state(
        genmod,
        {n: e for n, e in new_servers.items() if n not in out_of_scope},
        env, live_all, resolutions, mcp_items) \
        if in_scope("mcps") else live_all
    instr_ops, instr_removals = final_instructions(
        instr_items, new_instr_targets, source_updates, instr_resolutions, home,
        profile, default_source) \
        if in_scope("instructions") else ([], [])
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
    for relpath in sorted(source_updates):
        any_change = True
        print(f"  Instructions/{relpath}: updated (review with git diff after apply)")
    for provider, path, content in instr_ops:
        any_change = True
        print(f"  instructions rewrite: {provider} ({path})")
    for provider, legacy in instr_removals:
        any_change = True
        print(f"  instructions migrate: {provider} — back up and remove {legacy}")
    if new_instr_targets != instr_targets:
        any_change = True
        print("  Instructions/instructions.yaml: targeting updated")
        for provider in sorted(set(instr_targets) | set(new_instr_targets), key=str.lower):
            old, new = instr_targets.get(provider), new_instr_targets.get(provider)
            if old != new:
                print(f"    {provider}: {old or '(untargeted)'} -> {new or '(untargeted)'}")
    for name, clients, state in mcp_skipped + skill_skipped + instr_skipped:
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
    if read_only:
        assert norm(new_servers) == norm(servers)
        assert not source_updates and new_skill_targets == skill_targets
        assert new_instr_targets == instr_targets
    if norm(new_servers) != norm(servers):
        backup(SERVERS_PATH, home, stamp)
        SERVERS_PATH.write_text(
            json.dumps({"version": 1, "servers": new_servers}, indent=2) + "\n")
    changed_clients = write_mcp_configs(final, live_all, home, genmod, stamp)
    applied_skills = apply_skill_ops(skill_ops, home, stamp)
    if new_skill_targets != skill_targets:
        backup(SKILLS_MANIFEST, home, stamp)
        write_skill_targets(new_skill_targets)
    for relpath, content in source_updates.items():
        path = INSTRUCTIONS_ROOT / relpath
        backup(path, home, stamp)
        path.write_text(content)
    for provider, path, content in instr_ops:
        backup(path, home, stamp)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for provider, legacy in instr_removals:
        backup(legacy, home, stamp)
        legacy.unlink()
    if new_instr_targets != instr_targets:
        backup(INSTRUCTIONS_MANIFEST, home, stamp)
        write_instruction_targets(new_instr_targets)

    print("\nSUMMARY")
    if norm(new_servers) != norm(servers):
        print(f"  canonical: servers.json updated — review: git -C {CONFIG_ROOT} diff")
    if new_skill_targets != skill_targets:
        print("  canonical: Skills/skills.json updated (per-skill targeting)")
    if source_updates:
        print(f"  canonical: Instructions/ updated ({', '.join(sorted(source_updates))})"
              f" — review: git -C {CONFIG_ROOT} diff")
    if new_instr_targets != instr_targets:
        print("  canonical: Instructions/instructions.yaml updated")
    for provider, path, content in instr_ops:
        print(f"  instructions rewrite: {provider} ({path})")
    for provider, legacy in instr_removals:
        print(f"  instructions migrated: {provider} — removed {legacy}")
    if changed_clients:
        print(f"  providers rewritten: {', '.join(changed_clients)}")
    for action, name, agent in applied_skills:
        print(f"  skill {action}: {name}" + (f" @ {agent}" if agent else ""))
    print(f"  backups: {state_dir(home) / 'backups' / stamp} (as needed)")


if __name__ == "__main__":
    main()

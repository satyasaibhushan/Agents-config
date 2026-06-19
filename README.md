# Agent Config

This repository is the canonical local configuration source for agent tooling.

```text
Skills/  Custom/shared agent skills
MCPs/    Canonical MCP server definitions and sync scripts
```

Nothing in this repository should contain credentials. Use environment variables or local ignored files for secrets.

## Skills

`Skills/` mirrors the shared skills repository layout:

```text
Skills/Skills/<skill-name>/SKILL.md
```

The existing per-agent skill folders can point at this canonical location with per-skill symlinks.

## MCPs

`MCPs/servers.json` is the canonical source for MCP server definitions.

`MCPs/generated/` contains local generated preview files for each agent. It is ignored by git because it is reproducible from `MCPs/servers.json`.

To regenerate previews:

```bash
python3 ~/Agents/Config/MCPs/scripts/generate-mcps.py
```

After verification, apply to local agent config files:

```bash
~/Agents/Config/MCPs/scripts/apply-mcps.sh
```

The apply script creates backups before writing.

# Agent Config

This repository is the canonical local configuration source for agent tooling.

```text
Skills/    Custom/shared agent skills
MCPs/      Canonical MCP server definitions and sync scripts
scripts/   apply.py — the reconciling apply for MCPs and skills
```

Nothing in this repository should contain credentials. Use environment variables or local ignored files for secrets.

## Apply (reconciling)

`scripts/apply.py` is the one verb for pushing canonical config out and pulling live edits back in. It runs fetch → plan → reconcile → preview → write:

```bash
python3 ~/Agents/Config/scripts/apply.py            # full interactive apply
python3 ~/Agents/Config/scripts/apply.py --plan     # read-only drift report
python3 ~/Agents/Config/scripts/apply.py --plan --json   # machine-readable matrix
python3 ~/Agents/Config/scripts/apply.py --only mcps     # or --only skills
```

- **Fetch/plan** normalizes every agent's live config into an item × provider matrix. Each cell is one of: `in sync`, `added` (live-only item), `modified`, `missing`, `unlinked` (skill symlink replaced by an edited folder), `untargeted` (present live but provider not in the canonical `clients` list), or `foreign` (symlink pointing elsewhere — reported only).
- **Reconcile** groups drifted items by distinct version: an identical change made in three agents is one decision, not three. Verbs per version: **promote** (live version becomes the canonical base for every provider), **keep** (import as-is, or as a per-client override via the existing `codex:` / `claude-desktop:` keys), **overwrite** (regenerate from canonical), **skip** (leave both, re-ask next apply).
- **Preview** recomputes the whole item row before writing — including the ripple where a promote rewrites providers that were in sync with the old base. Zero writes happen before you confirm; every touched file is backed up under `MCPs/backups/<timestamp>/` or `Skills/backups/<timestamp>/`.
- **Secrets** never enter the repo: on import/promote, literal values from `MCPs/.env.local` are reverse-substituted back into `${VAR}` placeholders, and all previews are masked.

App-managed items (e.g. Codex's own `node_repl` MCP) are on an ignore list — planning skips them and writes round-trip them untouched.

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

To apply, use the reconciling apply above. `MCPs/scripts/apply-mcps.sh` remains as the legacy one-way push (canonical always wins, no drift detection); `scripts/apply.py` supersedes it and reuses `generate-mcps.py` internally, so both always produce identical per-client output.

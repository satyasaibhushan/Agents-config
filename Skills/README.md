# Shared Custom Agent Skills

This repository is the canonical copy of custom/shared local agent skills.

Each skill is stored as:

```text
Skills/<skill-name>/SKILL.md
```

## Replicate On A Machine

Clone or copy this repository to:

```text
~/Agents/Config
```

Then link skills into each agent's skill directory with the reconciling apply:

```bash
python3 ~/Agents/Config/scripts/apply.py --only skills          # interactive
python3 ~/Agents/Config/scripts/apply.py --plan --only skills   # read-only drift report
```

Beyond linking, it detects drift: skills that exist live but not in canon can be imported (**keep**) or removed (**overwrite**); a symlink someone replaced with an edited real folder can have its edits imported into canon and relinked, or be reverted. See the root README for the full model. The legacy one-way `Skills/scripts/apply-skills.sh` still works for plain linking, but it ignores targeting.

Both intentionally create symlinks for individual skills only. Do not replace an entire agent-managed skills directory with one symlink.

## Per-Skill Client Targeting

`Skills/skills.json` mirrors the MCP `clients` key:

```json
{
  "version": 1,
  "skills": {
    "laravel-specialist": { "clients": ["claude-code", "cursor"] }
  }
}
```

The manifest is **sparse**: a skill absent from it targets every agent (`agents`, `claude-code`, `codex`, `cursor`), so with no manifest everything links everywhere. During apply:

- a skill present in an agent it does not target shows as `untargeted` — keep (target the agent) or overwrite (remove the link, backed up)
- a targeted skill missing from an agent — overwrite (link it) or keep (stop targeting that agent)
- a brand-new skill found in some agent — keep (import, target all) or keep **here** (import, target only where it was found)

Reconcile decisions rewrite the manifest on confirm; an entry that returns to all agents is dropped, keeping the file sparse. Edit it by hand freely — the next apply reconciles reality against it.

The apply script backs up replaced symlinks under:

```text
~/Agents/Config/Skills/backups/<timestamp>/
```

## Add Or Update A Skill

Create or edit:

```text
Skills/<skill-name>/SKILL.md
```

After pulling updates on another machine, rerun the replication commands above. Existing canonical symlinks are left alone, and existing non-canonical skill folders are skipped.

To import a skill from GitHub into the canonical folder:

```bash
python3 ~/Agents/Config/Skills/scripts/generate-skill-from-github.py \
  https://github.com/<owner>/<repo>/tree/<ref>/<path/to/skill>
```

Then apply the symlinks:

```bash
~/Agents/Config/Skills/scripts/apply-skills.sh
```

Notes:

- Cursor's managed manifests are not copied.
- Cursor's managed/bundled `~/.cursor/skills-cursor` skills are not stored here.
- Codex `.system` skills are not stored here.
- Codex plugin cache skills are not copied.
- Tool-specific managed folders should not be replaced wholesale; prefer per-skill symlinks.

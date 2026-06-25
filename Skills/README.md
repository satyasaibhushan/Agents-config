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

Then create per-skill symlinks into each agent's skill directory:

```bash
~/Agents/Config/Skills/scripts/apply-skills.sh
```

This intentionally creates symlinks for individual skills only. Do not replace an entire agent-managed skills directory with one symlink.

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

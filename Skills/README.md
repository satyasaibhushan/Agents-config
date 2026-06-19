# Shared Custom Agent Skills

This repository is the canonical copy of custom/shared local agent skills.

Each skill is stored as:

```text
Skills/<skill-name>/SKILL.md
```

## Replicate On A Machine

Clone or copy this repository to:

```text
~/Agents/Skills
```

Then create per-skill symlinks into each agent's skill directory:

```bash
canonical="$HOME/Agents/Skills/Skills"

mkdir -p \
  "$HOME/.agents/skills" \
  "$HOME/.claude/skills" \
  "$HOME/.codex/skills" \
  "$HOME/.cursor/skills"

for dest in \
  "$HOME/.agents/skills" \
  "$HOME/.claude/skills" \
  "$HOME/.codex/skills" \
  "$HOME/.cursor/skills"
do
  for skill_dir in "$canonical"/*; do
    [ -d "$skill_dir" ] || continue
    name="${skill_dir##*/}"
    target="$dest/$name"

    if [ -L "$target" ] && [ "$(readlink "$target")" = "$skill_dir" ]; then
      continue
    fi

    if [ -e "$target" ] || [ -L "$target" ]; then
      echo "Skip existing non-canonical skill: $target"
      continue
    fi

    ln -s "$skill_dir" "$target"
  done
done
```

This intentionally creates symlinks for individual skills only. Do not replace an entire agent-managed skills directory with one symlink.

## Add Or Update A Skill

Create or edit:

```text
Skills/<skill-name>/SKILL.md
```

After pulling updates on another machine, rerun the replication commands above. Existing canonical symlinks are left alone, and existing non-canonical skill folders are skipped.

Notes:

- Cursor's managed manifests are not copied.
- Cursor's managed/bundled `~/.cursor/skills-cursor` skills are not stored here.
- Codex `.system` skills are not stored here.
- Codex plugin cache skills are not copied.
- Tool-specific managed folders should not be replaced wholesale; prefer per-skill symlinks.

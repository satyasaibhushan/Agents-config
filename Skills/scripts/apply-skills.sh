#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
canonical="$root/Skills"
timestamp="$(date +%Y%m%d-%H%M%S)"
backup="$root/backups/$timestamp"

mkdir -p \
  "$HOME/.agents/skills" \
  "$HOME/.claude/skills" \
  "$HOME/.codex/skills" \
  "$HOME/.cursor/skills"

backup_path() {
  local path="$1"
  if [ -e "$path" ] || [ -L "$path" ]; then
    mkdir -p "$backup/$(dirname "$path")"
    cp -a "$path" "$backup/$path"
  fi
}

apply_one() {
  local dest="$1"
  local skill_dir="$2"
  local name="${skill_dir##*/}"
  local target="$dest/$name"

  if [ -L "$target" ] && [ "$(readlink "$target")" = "$skill_dir" ]; then
    return
  fi

  if [ -L "$target" ]; then
    local current
    current="$(readlink "$target")"
    case "$current" in
      "$HOME/Agents/Skills/Skills/$name"|"$HOME/Agents/Skills/Skills/$name/")
        ;;
      *)
        echo "Skip existing non-canonical skill symlink: $target -> $current"
        return
        ;;
    esac

    backup_path "$target"
    rm "$target"
    ln -s "$skill_dir" "$target"
    echo "Repointed skill symlink: $target -> $skill_dir"
    return
  fi

  if [ -e "$target" ]; then
    echo "Skip existing non-symlink skill: $target"
    return
  fi

  ln -s "$skill_dir" "$target"
  echo "Linked skill: $target -> $skill_dir"
}

for dest in \
  "$HOME/.agents/skills" \
  "$HOME/.claude/skills" \
  "$HOME/.codex/skills" \
  "$HOME/.cursor/skills"
do
  for skill_dir in "$canonical"/*; do
    [ -d "$skill_dir" ] || continue
    apply_one "$dest" "$skill_dir"
  done
done

if [ -d "$backup" ]; then
  echo "Applied skills. Backups: $backup"
else
  echo "Applied skills. No backups needed."
fi

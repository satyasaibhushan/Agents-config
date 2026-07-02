# Shared Agent Instructions

Canonical instructions files, distributed to every agent by the reconciling apply.

```text
AGENTS.md           The shared default source every provider renders from
instructions.yaml   Which live file belongs to which provider
<provider>.md       Created only when a provider diverges (keep during apply)
```

## Mapping

`instructions.yaml` maps provider → live file:

```yaml
version: 1
default_source: AGENTS.md
targets:
  claude-code:
    path: ~/CLAUDE.md
  codex:
    path: ~/.codex/AGENTS.md
  cursor:
    path: ~/AGENTS.md        # generic AGENTS.md convention; anything under ~ reads it
```

`source` is optional per target and relative to this folder — all providers share
`default_source` until one diverges. Point a provider at its own file
(`source: codex.md`) to give it different instructions; the apply's **keep** verb
does exactly this for you when it finds a provider-local edit worth preserving.

## Apply

```bash
python3 ~/Agents/Config/scripts/apply.py --only instructions          # interactive
python3 ~/Agents/Config/scripts/apply.py --plan --only instructions   # read-only
```

States per provider: `in sync` / `modified` (live differs from its source, shown as a
unified diff) / `missing`. Identical edits across providers on the same source are one
decision. Verbs mirror MCPs:

- **promote** — the live edit becomes the source file's content, rippling to every
  provider on that source
- **keep** — diverge: the edit is stored as `Instructions/<provider>.md` and the
  provider's `source` is pointed at it
- **overwrite** — regenerate the live file from its source
- **skip** — leave both, re-ask next apply

A missing live file offers overwrite (write it) or keep (stop targeting the provider —
removes it from `instructions.yaml`). Zero writes before confirm; replaced live files
are backed up under `Instructions/backups/<timestamp>/`.

To onboard a new provider, add a `targets:` entry by hand — the next apply will show
it as `missing` and offer to write it.

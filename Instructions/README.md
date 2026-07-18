# Shared Agent Instructions

Canonical instructions, distributed to every agent by the reconciling apply.

```text
fragments/          Ordered building blocks (base.md, devbox.md, restricted-agent.md)
providers/          Per-provider extras and full divergences
instructions.yaml   Which live file belongs to which provider
```

## Rendering

Each provider's live file is the concatenation of the **active profile's
fragments** (in `profiles.yaml` order) plus the provider's optional `extra`
fragment. So `mac-admin` renders `base.md` alone, while `devbox-agent` renders
`base.md` + `devbox.md` + `restricted-agent.md` — same canonical content, one
render per machine shape.

`instructions.yaml` (version 2) maps provider → live file:

```yaml
version: 2
targets:
  claude-code:
    path: ~/.claude/CLAUDE.md
    legacy: ~/CLAUDE.md              # old live path; apply migrates it
    extra: providers/claude-code.md  # appended after the profile fragments
  codex:
    path: ~/.codex/AGENTS.md
  cursor:
    path: ~/AGENTS.md                # generic AGENTS.md convention
```

- `extra` — a provider-only fragment appended after the shared ones.
- `source` — full divergence: the provider renders exactly that one file and
  ignores fragments (the apply's **keep** verb sets this for you).
- `legacy` — an old live path. When it still exists, plan shows `migrate` and
  apply writes `path`, then backs up and removes the legacy file so the rules
  never load twice.

## Apply

```bash
agents-config apply --only instructions    # interactive
agents-config plan --only instructions     # read-only
```

States per provider: `in sync` / `modified` (live differs from the render,
shown as a unified diff) / `missing` / `migrate`. Identical edits across
providers rendering the same sources are one decision. Verbs:

- **promote** — each live diff hunk is mapped back to the fragment it falls in
  and folded into that source file, rippling to every provider that renders it.
  Insertions exactly on a fragment boundary ask which side they belong to;
  a hunk that rewrites lines *across* a boundary blocks promote (split the
  edit, or diverge).
- **keep** — diverge: the whole live file is stored as
  `providers/<provider>.md` and the provider's `source` is pointed at it.
- **overwrite** — regenerate the live file from canonical.
- **skip** — leave both, re-ask next apply.

Zero writes before confirm; replaced live files are backed up under
`~/.local/state/agents-config/backups/<timestamp>/`.

To onboard a new provider, add a `targets:` entry by hand — the next apply
shows it as `missing` and offers to write it.

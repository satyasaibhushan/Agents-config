## Picking the right models for workflows and subagents

Rankings, higher = better. Cost reflects what I actually pay, not list price. Intelligence is how hard a problem you can hand the model unsupervised. Taste covers UI/UX, code quality, API design, and copy.

| model    | cost | intelligence | taste |
|----------|------|--------------|-------|
| sonnet-5 | 5    | 5            | 7     |
| opus-4.8 | 4    | 7            | 8     |
| fable-5  | 2    | 9            | 9     |

Codex uses the model configured in `~/.codex/config.toml`. Do not carry
ratings from a previous model forward when that default changes.

How to apply:
- These are defaults, not limits. You have standing permission to override them: if a cheaper model's output doesn't meet the bar, rerun or redo the work with a smarter model without asking. Judge the output, not the price tag. Escalating costs less than shipping bad work.
- Don't let cost prevent you from using the right model for the job. Instead, take advantage of cheaper options to get more information and try things before moving the work to the more expensive option.
- Bulk/mechanical work (clear-spec implementation, data analysis, migrations): Codex
- Anything user-facing (UI, copy, API design) needs taste ≥ 7.
- Reviews of plans/implementations: fable-5 or opus-4.8, optionally Codex as an extra independent perspective.
- Never use Haiku.
- Mechanics: use `codex exec` / `codex review` with the configured Codex model. Pin a model explicitly only when the task calls for that specific model. Use the codex-implementation, codex-review, and codex-computer-use skills; for work they don't cover (investigation, data analysis), use `codex exec -s read-only` directly with a self-contained prompt.
- Claude models (sonnet-5, opus-4.8, fable-5) run via the Agent/Workflow model parameter.

Using Codex inside workflows and subagents (the model parameter only takes Claude models, so use a wrapper):
- Spawn a thin Claude wrapper agent with `model: 'sonnet', effort: 'low'` whose prompt instructs it to write a self-contained codex prompt, run `codex exec` via Bash, and return the report (use `schema` on the wrapper to get structured output back).
- Always label these agents with a `Codex:` prefix, e.g. `{label: 'Codex:review-auth'}` — the workflow UI shows the wrapper's Claude model, so the label is the only indication the real worker is Codex. Do not claim a specific model unless verified for that run.
- Codex runs can exceed Bash's 10-minute timeout: pass an explicit timeout, or run in the background and poll for the report file.
- Parallel Codex implementation agents must use `isolation: 'worktree'` so their codex edits don't collide in the shared checkout.
- Workflow token budgets only count Claude tokens; codex work is free and invisible to `budget.spent()`.

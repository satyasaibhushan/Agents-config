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
- Always label these agents with a `Codex:` prefix, e.g. `{label: 'Codex:review-auth'}`: the workflow UI shows the wrapper's Claude model, so the label is the only indication the real worker is Codex. Do not claim a specific model unless verified for that run.
- Codex runs can exceed Bash's 10-minute timeout: pass an explicit timeout, or run in the background and wait for its completion notice (see Waiting on long work).
- Parallel agents that edit files (Claude or Codex) must use `isolation: 'worktree'` or run serially, so their edits don't collide in the shared checkout. If they did share a tree, re-run the combined checks and diff `git status` against each agent's claimed files.
- Workflow token budgets only count Claude tokens; codex work is free and invisible to `budget.spent()`.

## Waiting on long work

Sleep loops are the biggest avoidable wait we have: about 16 hours over 30
days, and 25 of them ran into Bash's 10-minute ceiling.

- If you started it with `run_in_background`, the harness tells you when it
  exits. Keep working or end the turn. In T3, call `t3_background_wait` with
  the task ID. Don't loop `sleep` over its output file and don't `pgrep` it.
- Run tests in the foreground with an explicit `timeout`. Background them only
  when they can run past the ceiling.
- The harness can't watch a pod, an HTTP endpoint or a log line for you. Write
  one loop with a deadline under the ceiling, and make it exit on the failure
  marker too, so a crash shows up right away. If the tool has its own wait,
  like `devdock_wait`, use that instead of polling `kubectl`.
- If the deadline passes, report what you were waiting for and what you saw.
  Don't run the same wait again with a longer sleep.

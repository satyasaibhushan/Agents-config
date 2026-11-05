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
- Codex runs can exceed Bash's 10-minute timeout (600s). In a wrapper subagent, run `codex exec` in the foreground with an explicit Bash `timeout`. Background it only from the main agent, which is still running when the completion notice arrives (see Waiting on long work).
- Parallel agents that edit files (Claude or Codex) must use `isolation: 'worktree'` or run serially, so their edits don't collide in the shared checkout. If they did share a tree, re-run the combined checks and diff `git status` against each agent's claimed files.
- Workflow token budgets only count Claude tokens; codex work is free and invisible to `budget.spent()`.

## Waiting on long work

Don't wait in `sleep` loops. They block the turn and often hit Bash's
10-minute limit (600s) with nothing to show for it. A lone `sleep` followed by
another check is the same loop.

- If you started it with `run_in_background`, Claude Code tells you when it
  exits. Do work that doesn't need its result. If nothing else can move, end
  the turn and pick up on the notice; in T3, call `t3_background_wait` with
  the task ID first. A subagent whose caller needs the result in this run
  should run it in the foreground instead. Never wait for a background task
  from Bash: no `sleep` loop over its output file, no `pgrep`, `ps` or
  `kill -0` loop, no loop for a marker in its output. Read the output file
  once, after the notice.
- Run a test in the foreground with an explicit `timeout` only when it
  reliably finishes well under 600s, like one file or one class. Full suites,
  and any suite that has run long under load, go through `run_in_background`.
  A foreground run that passes 600s just gets killed.
- For a pod, an HTTP endpoint or a log line, use the tool's own wait first:
  `kubectl wait` or `kubectl rollout status`, `devdock_wait` where it exists,
  or the Monitor tool for logs. Give it a timeout under 600s (for example
  `--timeout=540s`). For PR checks in T3, use `watch_pull_request`. Only if
  nothing fits, write one loop with a deadline well under 600s, checks at
  least 20s apart, and an exit on failure (CrashLoopBackOff, Error, Failed)
  so a crash shows up at once.
- If the deadline passes, show the last status (pod phase, HTTP code, last
  log lines) and whether it was still moving. If it was, one more wait is
  fine; say what changed. If nothing changed, stop and report.

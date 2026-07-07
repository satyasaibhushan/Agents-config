---
name: codex-computer-use
description: Ask Codex CLI (gpt-5.5) to run local app verification that needs computer use: browser automation, simulators, screenshots, app launching, or independent runtime inspection. This is how gpt-5.5 is invoked for computer-use work. Use when the user asks Claude to test a flow, verify UI behavior, inspect a running app, capture screenshots, or report confirmation and feedback about implemented behavior that benefits from computer use functionality.
---

# Codex Computer Use

Use Codex as a separate local verification agent when the task needs real UI interaction, screenshots, simulator/browser/device state, or an independent runtime check beyond Claude's current context.

Do not use this for ordinary code reading, typechecking, linting, or tests Claude can run directly. Launching apps, simulators, or browsers to verify the requested work is fine without asking; ask first only if the run could disrupt the user's environment (closing their apps, changing system settings, acting on real accounts or data).

## Workflow

1. Create a temporary artifact directory.
2. Give Codex a self-contained prompt with the repo path, exact flow, constraints, and the evidence to capture.
3. Run `codex exec` non-interactively.
4. Read Codex's report, inspect or reference screenshot paths, and summarize the outcome.

Use this command shape:

```bash
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/codex-computer-use.XXXXXX")"
REPORT="$ARTIFACT_DIR/report.md"
PROMPT="$ARTIFACT_DIR/prompt.md"

# Write a self-contained prompt to $PROMPT, then run:
codex exec \
  -C "$PWD" \
  --full-auto \
  - < "$PROMPT" > "$REPORT"
```

## Prompt Requirements

The prompt must be self-contained. Tell Codex:

- The app or URL to verify, and how to launch or reach it.
- The exact flow to walk through, step by step.
- What evidence to capture: screenshots saved into the artifact directory, console or network output, and observed state.
- What passing and failing behavior look like.
- Not to disrupt the user's environment: no closing their apps, changing system settings, or acting on real accounts or data.
- To write a concise final report with the steps taken, screenshot paths, observed behavior, and a pass/fail verdict.

If `codex` is not installed or the command fails, report the error and offer to verify the behavior directly instead.

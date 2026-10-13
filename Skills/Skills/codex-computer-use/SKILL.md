---
name: codex-computer-use
description: Ask Codex CLI with its configured model to run local app verification that needs computer use: browser automation, simulators, screenshots, app launching, or independent runtime inspection. This is how Codex is invoked for computer-use work. Use when the user asks Claude to test a flow, verify UI behavior, inspect a running app, capture screenshots, or report confirmation and feedback about implemented behavior that benefits from computer use functionality.
---

# Codex Computer Use

Use Codex as a separate local verification agent when the task needs real UI interaction, screenshots, simulator/browser/device state, or an independent runtime check beyond Claude's current context.

Do not use this for ordinary code reading, typechecking, linting, or tests Claude can run directly. Launching apps, simulators, or browsers to verify the requested work is fine without asking; ask first only if the run could disrupt the user's environment (closing their apps, changing system settings, acting on real accounts or data).

Use the configured Codex model by default. Pin a model explicitly only when
the task calls for that specific model. Do not report a model name unless
verified for the run.

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
  -s workspace-write \
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

## App approval

Computer use runs through Codex's own bridge, outside the shell sandbox, so `-s workspace-write` is enough. Tell Codex to drive apps with its computer-use tool; shell desktop control (AppleScript, `screencapture`, `open -a`) is sandbox-blocked.

The bridge approves apps per Codex session, and `codex exec` cannot show that prompt, so the first run against a new app fails with "Computer Use was not approved to control <app>". Take the session id from the exec header, have the user add the app's bundle id to `~/.codex/computer-use/sessions/<session-id>.toml`:

```toml
[apps]
allowed = ["app.zen-browser.zen"]
```

then resume, with options before `resume`:

```bash
codex exec -C "$PWD" -s workspace-write resume <session-id> - < "$ARTIFACT_DIR/continue.md" > "$REPORT"
```

If `codex` is not installed or the command fails, report the error and offer to verify the behavior directly instead.

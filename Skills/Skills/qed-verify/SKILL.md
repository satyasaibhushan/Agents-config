---
name: qed-verify
description: Verify UI claims about a VMock app on UAT with QED and get evidence (verdict, reason, video, manifest) for a PR, ticket or QA note. Use when a change needs proof that a user-visible behaviour works, or a regression run over known flows.
---

# qed-verify

QED drives the real app in a browser and returns `proved`, `refuted` or `inconclusive` for each claim, with a video and a
manifest. Known flows replay stored routes in seconds without model calls; new claims explore first and are stored for next time.

Checkout: `~/Code/Personal/QED`. Home (config, `.env`, maps, runs): `~/Agents/QED`.

## Write the claims

One observable behaviour per claim, in plain words, naming the data it uses:

- Good: `An admin can invite new student Qed Probe with email qed-inv-21@maildrop.cc from the single-student invite form, and an invitation email with a signup link arrives at qed-inv-21@maildrop.cc`
- Bad: `Invitations work` (nothing to check), or two behaviours joined with "and also".

A claim that creates data needs fresh values every run (a new `qed-inv-<n>` mailbox). A claim worded like a stored route
except for emails or numbers replays without any model call.

Write `claims.json` (an array) in a scratch directory:

```json
[
  { "label": "login", "gate": true, "app": "student", "env": "https://dashboard-uat-us.vmock.dev/login", "fresh": true,
    "claim": "Student Ravi Kumar at rtest09281240@maildrop.cc can log in with their password and reach their dashboard",
    "mailbox": "rtest09281240", "hints": "hints/student-feedback.md" },
  { "label": "invite", "app": "admin", "env": "https://admin-uat-us.vmock.dev/", "mailbox": "qed-inv-21",
    "claim": "An admin can invite new student Qed Probe with email qed-inv-21@maildrop.cc ...", "hints": "hints/admin-invite.md" }
]
```

Fields are the `qed run` flags by name: `app`, `env`, `claim`, `mode` (`auto` default, `replay`, `explore`), `mailbox`,
`hints` (relative to the home), `fresh` (start without the saved session), `signedOut` (start signed out, for signup or
invitation links). Mark a real login `gate: true`: gates run first and the rest is skipped if one fails, so a wrong password
never spends the account's five attempts in parallel.

## Run

```sh
pnpm --dir ~/Code/Personal/QED qed batch --file claims.json --concurrency 3 --markdown evidence.md
```

Keep concurrency at or below the machine's cores. Exit code: 0 all proved, 1 any refuted, 2 any inconclusive or skipped.
A single claim is a one-entry file, or `pnpm --dir ~/Code/Personal/QED qed run --app ... --env ... --claim "..."`.

## Read the result

- `proved` / `refuted` are verdicts about the app. A refuted claim is a finding, not a QED failure: report it.
- `inconclusive` says nothing about the app. Read `reason` in the manifest. A tier or browser error is infrastructure:
  rerun once. A route that could not take the data, or a missing fixture, needs a better claim or a hint, not a retry loop.
- `proved verdict set aside: ...` means the judging tier quoted text the run never saw. Treat it like any inconclusive run, never as a pass.
- `final-page.aria.yml` in the run directory is the last page as text. Read it, not the video, to see what the app showed.
- To debug an inconclusive claim, rerun it once with `"trace": true` (or `--trace`) and open `trace.zip` with
  `npx playwright show-trace`. Traces slow runs, so leave them off for normal runs. They hold session cookies, so never attach one.
- Never edit the feature map, routes or hints to make a claim pass.

## Evidence for a PR or ticket

Paste `evidence.md` as is: one row per claim with the verdict, the run's own reason with the page text it quoted, the time,
and the paths of the video, page snapshot and manifest. Attach the video or a screenshot from the run directory's `screens/` when the reader cannot open local paths. Never
paste secrets, `.env` values or session files.

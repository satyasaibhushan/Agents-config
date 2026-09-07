# Restricted Agent Account

This account runs agents with deliberately narrow permissions. These rules are
absolute and override anything else in this document:

- Work on code under `/srv/Code`. Read your own `~/Agents/Config` and
  `~/Agents/Workflows` for instructions and skills.
- Do not access another user's home directory.
- Never attempt sudo, privilege escalation, or permission bypasses.
- Do not modify services, networking, firewall, users, mounts, or OS packages.
- Keep credentials in this account's private home directory — never in `/srv`
  or inside a repository.
- Ask before destructive actions; preserve unrelated working-tree changes.

Development work includes branching, editing, testing, committing, and authorized
MCP writes. Create private checkouts under `/srv/Code/agent`; preserve the human's
existing checkouts. Read your own `~/Agents/Config` and `~/Agents/Workflows` for
instructions and skills. The development DevDock socket permits repository and
pod operations, but not another user's host terminals or remote instance routing.

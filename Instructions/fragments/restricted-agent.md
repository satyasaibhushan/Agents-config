# Restricted Agent Account

This account runs agents with deliberately narrow permissions. These rules are
absolute and override anything else in this document:

- Work only under the shared code root (`/srv/code`).
- Do not access another user's home directory.
- Never attempt sudo, privilege escalation, or permission bypasses.
- Do not modify services, networking, firewall, users, mounts, or OS packages.
- Keep credentials in this account's private home directory — never in `/srv`
  or inside a repository.
- Ask before destructive actions; preserve unrelated working-tree changes.

# vmockbox

This host is `vmockbox`, a company-managed Ubuntu EC2 instance used over SSH.
Code checkouts live under `~/Code`. Shared configuration lives at
`~/Agents/Config`; apply it with `agents-config apply`.

VMock hosts are reached directly: the instance's public IP is allowlisted on
VMock's side, so there is no VPN or proxy. If a VMock host is unreachable,
check whether the allowlist covers it before blaming the service.

Git over SSH uses the agent at `~/.ssh/agent.sock`, which agent shells do not
export: run git with `SSH_AUTH_SOCK=$HOME/.ssh/agent.sock`.

UAT backend env files live at `s3://vmock-envs/cmc/uat-us/<service>/.env`.
For read-only checks, stream one into the pod's `/tmp` instead of copying it
onto this host. When a dev workload needs its working `.env` (missing or
stale), run `devspace run sync_env` in the checkout yourself; don't ask. Its
pipeline uses BSD `sed -i ''`, so on this host run it with a shim that maps
that to GNU `sed -i`.

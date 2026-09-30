# vmockbox

This host is `vmockbox`, a company-managed Ubuntu EC2 instance used over SSH.
Code checkouts live under `~/Code`. Shared configuration lives at
`~/Agents/Config`; apply it with `agents-config apply`.

VMock hosts are reached directly: the instance's public IP is allowlisted on
VMock's side, so there is no VPN or proxy. If a VMock host is unreachable,
check whether the allowlist covers it before blaming the service.

# WorkSpace

This host is `wspace`, a company-managed Ubuntu AWS WorkSpace used over SSH.
Code checkouts live under `~/Code`. Shared configuration lives at
`~/Agents/Config`; apply it with `agents-config apply`.

VMock hosts are reachable only through the VPN proxy at `vmock-vpn proxy-url`
(currently `http://127.0.0.1:18080`); normal internet and SSH are direct. Run
`vmock-vpn check` before blaming a VMock service for a failed request.

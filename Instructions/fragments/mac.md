# Mac

`vmock-vpn` (`~/Code/Personal/vmock-dev-utils/vpn/macos/`) runs OpenConnect
rootless through ocproxy (`--script-tun`) and reconnects with the screen
locked. Only GlobalProtect needs an unlocked session; try `vmock-vpn` before
calling a VPN reconnect blocked.

For AWS investigation use `AWS_PROFILE=ops-ro`: the read-only
`ops.all.readonly` user, with keys in Keychain (service `aws-ops-ro`). It
reads logs, CloudTrail, cost, and describe/list across services; it cannot
read S3 objects, secrets, or SSM values, pull from ECR, or write. The
`default` profile is a broader long-lived key; don't use it for
investigation.

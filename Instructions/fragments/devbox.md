# Devbox

This host is a shared Linux devbox. Code checkouts live under `/srv/Code`
(the code root on this host), not `~/Code` — read the base code-structure
section with that substitution in mind.

Shared configuration lives at `/srv/Agents/Config`; workflows live at
`/srv/Agents/Workflows`. Read `/srv/Agents/Workflows/INDEX.md` before ticket work.
Both accounts use these same checkouts. `~/Agents/Config` and `~/Agents/Workflows`
are compatibility links to them. Apply configuration with
`/srv/Agents/Config/scripts/agents-config apply`.

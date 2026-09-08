---
name: devdock-development
description: Use DevDock to run changed services in development, configure their routing, and prepare the environment for verification.
---

# DevDock development

Use the configured DevDock MCP. A repository is the checkout on the execution host; a workload is an API, worker, cron, or UI. A deployed pod and an active development session are separate states. The development session enables code synchronization and the development runtime.

## Tools and lifecycle

Inspect the available tool schemas for exact arguments.

| Tool | Purpose |
| --- | --- |
| list / status | Discover repositories, workloads, and their current state |
| checkout | Inspect checkout path, branch, revision, and local changes |
| start | Start development for an existing deployment |
| build_start | Deploy a workload and start development |
| run | Execute a command in the pod and obtain its exit result |
| logs / wait | Read output and wait for readiness or a known condition |
| operation_status | Check completion of a durable operation |

An `exec` acknowledgment only proves command submission. Check completion and exit status before claiming success.

1. Inspect state and checkout before changing anything. Reuse healthy running development sessions.
2. If the pod exists but development is stopped, start development only.
3. If a changed repository's pod is absent or purged, deploy it and start development.
4. Unchanged dependencies without development pods use the environment's UAT-US fallback. If UI is needed, deploy and start the relevant UI too.
5. Do not routinely purge or restart healthy workloads. If DevDock fails, report the operation ID and useful error to the user. Do not bypass it with direct infrastructure changes.

## Routing and verification

Run every changed repository in development. Set the relevant environment values to `saibhushan` so API calls reach that user's development pods; preserve unrelated values. Inspect actual network requests and pod logs. A personal frontend URL can still call UAT, so confirm the changed service handled the request.

| Surface | Development | UAT-US |
| --- | --- | --- |
| Dashboard | https://dashboard-saibhushan.vmock.dev | https://dashboard-uat-us.vmock.dev |
| Admin / coach | https://admin-saibhushan.vmock.dev | https://admin-uat-us.vmock.dev |
| Candidate API | https://api-saibhushan-candidate.vmock.dev/<service>/ | https://api-uat-us-candidate.vmock.dev/<service>/ |
| CMC API | https://api-saibhushan-cmc.vmock.dev/<service>/ | https://api-uat-us-cmc.vmock.dev/<service>/ |
| Capabilities API | https://api-saibhushan-capabilities.vmock.dev/<service>/ | https://api-uat-us-capabilities.vmock.dev/<service>/ |

Confirm the app's route and environment configuration before using these URLs. Local checkout paths are supplied by DevDock; do not invent localhost routes.

For deeper setup and routing details, read the [DevSpace guidelines](https://github.com/vmockinc/guidelines/tree/master/devspace).

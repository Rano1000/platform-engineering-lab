# Golden-path application reference

## Runtime contract

| Item | Value |
| --- | --- |
| Local image | `golden-path-api:0.1.0-<12-character-git-sha>` |
| GitOps image | `ghcr.io/rano1000/golden-path-api@sha256:<complete-digest>` |
| Namespace | `platform-apps` |
| Helm release | `golden-path` |
| Replicas | 2 |
| Container port | 8080 |
| Runtime identity | UID/GID 10001 |
| Public hostname | `golden-path-api.localhost` |

The local build refuses uncommitted image inputs and refuses to replace an existing revision tag. The tag uses the first 12 Git revision characters and the OCI revision label uses all 40. Local deployment retains `imagePullPolicy: Never`; reviewed GitOps state uses the public registry digest and `IfNotPresent`. Mutable registry tags are never promoted.

## Endpoints

- `/` returns application identity and build revision.
- `/health/live` indicates process liveness.
- `/health/ready` reflects lifecycle readiness.
- `/metrics` emits Prometheus metrics and is not attached to the public HTTPRoute.

## Commands

Read-only commands are `make app-status`, `make app-validate`, and `make app-ownership-status`. Build, load, deploy, uninstall, network-test, and recovery-test targets change local Docker or the exact lab cluster and must be used deliberately. Helm deployment and uninstall refuse to run after the repository-owned Argo Application exists.

`make app-network-test` requires the confirmation `app-network-policy-test`. It creates one uniquely named egress NetworkPolicy and runs two uniquely named Pods sequentially in `observability`, so no more than two temporary resources exist at once. The approved Pod proves the internal metrics response and denial outside the approved application port, to the Kubernetes API, and to public TCP 443. The unapproved Pod independently proves denial to metrics, the Kubernetes API, and public TCP 443. Three workstation-side assertions confirm that public metrics, liveness, and readiness paths remain blocked.

Each operation has a three-second socket timeout inside a 30-second Pod deadline. Evidence is written beneath `.artifacts/app-network/<run-id>/` and includes structured results, exact names and UIDs, pre-test specifications, logs, termination state, descriptions, events, node placement, runtime image IDs, and both relevant NetworkPolicies. Diagnostics must be complete, sanitized, and path-safe before each resource is removed with UID-aware observable cleanup. An incomplete diagnostic set preserves the affected resource for separate review. The temporary policy is validation-owned state; the application chart renders only `platform-apps` resources.

`make app-recovery-test` displays the exact application Pod, requires its name as confirmation, deletes only that Pod, and verifies that the Deployment restores two replicas.

Runtime validation derives image identity from the active owner. A Helm-owned local release must use an immutable revision tag, `imagePullPolicy: Never`, and the same complete content image ID on both workers and running Pods. An Argo-owned release must use the approved GHCR repository at a complete digest, with matching protected Application annotations and runtime `imageID`. Validation never assumes that the current repository revision has already been built or deployed.

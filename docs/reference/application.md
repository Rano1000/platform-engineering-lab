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

`make app-network-test` creates one uniquely named egress NetworkPolicy and two uniquely named Pods in `observability`. It proves labelled metrics traffic is allowed and unlabelled traffic is denied, then removes all three resources through a cleanup trap. This policy is validation-owned temporary state; it is not part of the application chart or Argo CD workload ownership. The chart renders resources only in `platform-apps`.

`make app-recovery-test` displays the exact application Pod, requires its name as confirmation, deletes only that Pod, and verifies that the Deployment restores two replicas.

Runtime validation derives image identity from the active owner. A Helm-owned local release must use an immutable revision tag, `imagePullPolicy: Never`, and the same complete content image ID on both workers and running Pods. An Argo-owned release must use the approved GHCR repository at a complete digest, with matching protected Application annotations and runtime `imageID`. Validation never assumes that the current repository revision has already been built or deployed.

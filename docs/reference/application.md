# Golden-path application reference

## Runtime contract

| Item | Value |
| --- | --- |
| Image | `golden-path-api:0.1.0-<12-character-git-sha>` |
| Namespace | `platform-apps` |
| Helm release | `golden-path` |
| Replicas | 2 |
| Container port | 8080 |
| Runtime identity | UID/GID 10001 |
| Public hostname | `golden-path-api.localhost` |

The build refuses uncommitted application/chart sources and refuses to replace an existing revision tag. The tag uses the first 12 Git revision characters and the OCI revision label uses all 40. `imagePullPolicy: Never` prevents registry fallback after the image is loaded into kind.

## Endpoints

- `/` returns application identity and build revision.
- `/health/live` indicates process liveness.
- `/health/ready` reflects lifecycle readiness.
- `/metrics` emits Prometheus metrics and is not attached to the public HTTPRoute.

## Commands

Read-only commands are `make app-status` and `make app-validate`. Build, load, deploy, uninstall, network-test, and recovery-test targets change local Docker or the exact lab cluster and must be used deliberately.

`make app-network-test` creates uniquely named Pods in `observability`, proves labelled metrics traffic is allowed and unlabelled traffic is denied, and removes both Pods through a cleanup trap.

`make app-recovery-test` displays the exact application Pod, requires its name as confirmation, deletes only that Pod, and verifies that the Deployment restores two replicas.

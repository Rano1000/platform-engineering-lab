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

`make app-network-test` requires the confirmation `app-network-policy-test`. A two-worker enforcement preflight must pass first. The application test creates exact run-specific ingress and egress policies and a reachable listener on the opposite worker, then runs approved and unapproved clients sequentially. At most five temporary resources coexist. A denial is accepted only as a timeout against the proven listener; refusal is a failure. Public HTTP probes always emit one structured result, including DNS, connect, read, TLS, malformed-response, and process failures.

`make kindnet-policy-recover` is separately authorized. Before confirmation it requires the exact DaemonSet selector `app=kindnet`, both `app=kindnet` and `k8s-app=kindnet` Pod-template labels, one directly owned Ready Pod on each expected node, and the pinned specification and runtime image identities. Its generated confirmation is `<context>/kindnet/<daemonset-uid>/<comma-separated-original-pod-uids>`. It replaces one verified kindnet Pod at a time in control-plane, worker, worker2 order and runs the two-worker enforcement test afterward. It does not restart Docker, nodes, or workloads and has no automatic retry.

All application and cluster recovery confirmations use the shared POSIX helper in `scripts/lib/cluster-common.sh`. Input must match the freshly generated identity byte-for-byte; empty input, EOF, leading or trailing whitespace, partial values, and extra characters stop before mutation.

`make kindnet-policy-validate` is the validation-only follow-up after recovery. It accepts the freshly discovered replacement Pod UIDs, validates the exact DaemonSet selector, template labels, ownership, pinned image and runtime identities, and then requests a confirmation beginning with `kindnet-policy-validation/`. It never deletes kindnet Pods. It creates only uniquely named policy-test resources, tests DNS plus allow and deny behavior independently on both workers, captures complete sanitized evidence, and removes only those temporary resources with exact UID-aware cleanup. Its nested evidence directories are validated beneath the selected kindnet run directory rather than an unrelated artifact root.

Pod evidence uses canonical suffixes from `scripts/lib/diagnostic-common.sh`: `.created.json`, `.pod.log`, `.pod.json`, `.describe.txt`, `.events.json`, and `.cleanup.json`. Capture and sanitization do not independently construct these names. Each DNS probe records the complete mapping before the final evidence manifest is created.

Each operation has a three-second socket timeout inside a 30-second Pod deadline. Evidence is written beneath `.artifacts/app-network/<run-id>/` and includes structured results, exact names and UIDs, pre-test specifications, logs, termination state, descriptions, events, node placement, runtime image IDs, and both relevant NetworkPolicies. Diagnostics must be complete, sanitized, and path-safe before each resource is removed with UID-aware observable cleanup. An incomplete diagnostic set preserves the affected resource for separate review. The temporary policy is validation-owned state; the application chart renders only `platform-apps` resources.

`make app-recovery-test` displays the exact application Pod, requires its name as confirmation, deletes only that Pod, and verifies that the Deployment restores two replicas.

Runtime validation derives image identity from the active owner. A Helm-owned local release must use an immutable revision tag, `imagePullPolicy: Never`, and the same complete content image ID on both workers and running Pods. An Argo-owned release must use the approved GHCR repository at a complete digest, with matching protected Application annotations and runtime `imageID`. Validation never assumes that the current repository revision has already been built or deployed.

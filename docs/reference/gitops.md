# GitOps reference

## Pinned installation

| Item | Value |
| --- | --- |
| Release | `argocd` |
| Namespace | `gitops` |
| Chart | `oci://ghcr.io/argoproj/argo-helm/argo-cd` 10.4.0 |
| Chart digest | `sha256:8ff18ee7a22670305555167ea31f24a88e2f912cf0a872f852e1880886d4c308` |
| Argo CD | v3.5.2, digest-pinned |
| Redis | 8.6.4-alpine, digest-pinned |
| Application | `golden-path-api` |
| Root Application | `platform-environment` |
| Projects | `platform-bootstrap`, `platform-apps` |

Both dedicated projects set `clusterResourceWhitelist: []`. `platform-bootstrap` permits only namespaced `argoproj.io/Application` resources in `gitops`; `platform-apps` permits only the seven reviewed workload kinds in `platform-apps`. Validation rejects wildcard repositories, destinations, namespaces, API groups, and kinds, as well as any removed or additional namespaced kind.

The controller cache uses `resource.respectRBAC: normal`. Its ClusterRole is a closed list: approved workload kinds retain their existing management verbs; Pods, namespaces, ReplicaSets, and EndpointSlices receive only `get`, `list`, and `watch`; Events additionally require `create` and `patch`. Unrelated APIs—including admission webhooks and Secrets—receive no access. `strict` mode is not used because it requires creating `SelfSubjectAccessReview` objects.

Canonical bootstrap-object SHA-256 checksums are `c8aeeac80903c974d4777b3924fb90a031fc9d71d7c29db917313332f0d4a481` for `platform-bootstrap`, `b09cdc47dab5fd2586597e21d4850163df937ead281905936efa9ef714cf487e` for `platform-apps`, and `6d70580cd848fd52a08476c8ecb98ea28e1f877a4bb18fd681ff7f82cad2a989` for `platform-environment`. Phase 4 validation recalculates all three from canonical JSON.

Steady-state requests total approximately 275m CPU and 704Mi memory. Combined limits are approximately 1.35 CPU and 1.4Gi memory. Redis and repository caches use disposable `emptyDir`; no PVC is created.

## Commands

- `make gitops-install`: guarded controller installation; cluster-scoped CRDs and RBAC are created.
- `make gitops-default-project-harden`: guarded, idempotent replacement of only the built-in `default` AppProject with the repository-owned deny-all specification.
- `make gitops-bootstrap`: one-time manual application of both projects and the root Application.
- `make gitops-status`: read-only component and reconciliation status.
- `make gitops-root-status` and `make gitops-root-diff`: read-only environment-definition status and diff.
- `make gitops-root-sync`: confirm stage 1 and update only the child Application specification.
- `make gitops-app-status` and `make gitops-app-diff`: read-only workload status and diff.
- `make gitops-app-sync`: separately confirm stage 2 and update workload resources.
- `make gitops-network-test`: run worker-pinned, single-assertion API egress diagnostics. Each result and its sanitized Kubernetes evidence are retained under `.artifacts/gitops-network`; UID-aware cleanup evidence records command output, final identity, and deletion-race classification.
- `make gitops-validate`: read-only runtime security and health validation.
- `make gitops-uninstall`: guarded removal that refuses while the Application exists.
- `make app-ownership-status`: report Helm or Argo ownership without mutation.

The cleanup guard records each resource UID immediately after creation, checks it again before deletion, and refuses a reused name. The pinned `kubectl` interface has no delete flag for an API UID precondition, so a final exact-name GET is mandatory: only confirmed absence can complete cleanup, and a surviving or replacement UID fails closed without an automatic retry.

Controller installation executes Helm once with `--atomic`, `--wait`, and a fixed 15-minute timeout. A first installation can spend several minutes pulling digest-pinned images. Cached pulls are normally faster but are never assumed. On failure, sanitized scheduling, image-pull, waiting-state, hook, readiness, Helm, CRD, and RBAC evidence is retained under `.artifacts/gitops-install` before the installer stops.

After Helm succeeds, installation adopts `platform/addons/argocd/default-project.yaml` with dedicated field manager `platform-engineering-lab-default-project`. The built-in project remains present but has no source repositories, destinations, cluster-resource allowlist, or namespaced-resource allowlist. Validation checks its protected metadata and complete specification against deterministic checksum `sha256:102d3a96976670f66b262eb2c45a0ad2ff30529c79844a3dd9e85f02f1b71625`. Any unrelated ownership or permissive value fails closed. Root and workload Applications use `platform-bootstrap` and `platform-apps`; neither may use `default`.

The separate hardening target supports an already installed controller. Before forcing the known `argocd-server` conflict, it requires the exact built-in permissive specification, no Application using `default`, and unchanged UID, resource version, protected checksum, and managed-field ownership across three snapshots. A forced server-side dry-run must change only the four ownership labels, purpose annotation, description, and four deny-all lists. The live apply executes once and is checked immediately and again after five seconds.

The confirmation is `<context>/gitops/default/<uid>/<current-checksum>/<desired-checksum>`. If the exact desired state is already owned by the dedicated manager, validation succeeds without dry-run, confirmation, or forced transfer. `--force-conflicts` is not available through any shared apply helper.

The `argocd` CLI must be exactly v3.5.2 for diff and sync. Install the repository-local copy with `make gitops-cli-install`. The installer downloads the official release binary and official `cli_checksums.txt`, verifies the pinned checksum-manifest digest and platform-specific binary SHA-256, checks the reported version, and atomically installs it under `.tools/argocd/v3.5.2/<os>-<architecture>/argocd`. This ignored cache does not alter the system `PATH` or require root access. Redirects are limited to GitHub release hosts; unsafe paths, symlinks, unsupported platforms, incomplete downloads, and mismatched content fail closed. Guarded commands prefer this verified copy. A system CLI is accepted only when it reports v3.5.2.

Argo CD v3.5.2 core mode obtains its controller namespace from the selected kubeconfig context; it has no global namespace flag. Every guarded core operation therefore creates a private `0600` temporary kubeconfig containing only `kind-platform-engineering-lab`, binds that temporary context to `gitops`, validates the complete context record, and invokes the CLI with both `--kube-context kind-platform-engineering-lab` and `--app-namespace gitops`. The original kubeconfig is never modified. A private credential-free Argo client configuration selects only that verified core context, while a minimal sanitized environment prevents shell variables or user configuration from redirecting the namespace, server, context, or diff implementation. Core mode uses Kubernetes authentication, so no Argo administrator or public server is required.

Guarded diffs set Argo CD's supported `--diff-exit-code` to `20`, keeping expected differences distinct from operational errors. Exit `20` is successful only after semantic validation. The root diff must be one complete creation of `Application/gitops/golden-path-api` matching the approved immutable manifest. The child diff may contain only creations or modifications from its exact rendered resource set; deletion, an unknown resource, empty output, malformed output, or any operational error fails closed. Sanitized stderr and the original error status remain visible for diagnosis.

Every sync requires the exact context, Application identity, repository, chart revision, image source revision, digest, and a clean local `main` synchronized with `origin/main`. The root alone tracks `main` for change detection. Root diff and sync fetch and resolve it to the complete immutable `environmentRevision`; they never pass `main` to the Argo operation.

The child renders its chart from immutable `chartRevision` and its image from the separate immutable digest. OCI revision must equal `imageSourceRevision`. These revisions may differ. Helm guards become active only after the live Deployment has the child's Argo tracking annotation.

Root synchronization checks `origin/main` before confirmation and again immediately before synchronization. A changed remote, abbreviated or mutable revision, local divergence, non-ancestor revision, evidence mismatch, or child-specification checksum mismatch stops the operation. Advancing `main` after a reviewed older revision is synchronized simply makes the root OutOfSync again; it never triggers automatic synchronization.

## Network boundary

Only the repository server receives external TCP 443 egress. Standard NetworkPolicy cannot select GitHub by DNS name, so that Pod alone may reach public HTTPS addresses while private, service, and Pod address ranges are excluded. Argo has no direct application-Pod flow.

Stable policies deliberately contain no Kubernetes Service ClusterIP allowance. Immediately before installation, the guard requires one Ready API EndpointSlice endpoint and verifies its address and TCP port against the control-plane InternalIP, kind Docker attachment, and kube-apiserver. A template then creates separate exact `/32` policies for the Redis secret-init hook, application controller, and API server. Their full stable label sets are selectors. Repository server, Redis, and unlabelled Pods remain denied from the API.

The canonical endpoint record includes cluster and context, Service and EndpointSlice identities, endpoint address and port, control-plane and kube-apiserver identities, and kind Docker network attachment. Its SHA-256 is recorded on every generated policy. Snapshots A, B, and C must match, and live policies are checked before and after Helm. No missing, multiple, non-Ready, malformed, broad, or changed endpoint is accepted.

This behavior is specific to the observed kind/kindnet post-DNAT enforcement path. It must be regenerated after cluster recreation. Traefik's older ClusterIP rule and control-plane placement remain unchanged pending a separate review.

The probe uses only Python standard-library networking from the already deployed immutable Golden Path image. API success means TCP and TLS completed; an HTTP 401 or 403 is an expected connectivity result and does not require an application credential. Timeout, refusal, DNS, TLS, HTTP authorization, socket, and process failures are reported separately. One Pod performs one assertion, with a two-second inner timeout and twenty-second outer deadline.

Diagnostics include the structured result, Pod JSON and termination state, description, events, applied policies, EndpointSlice identity, and worker node. Environment variables, credential mounts, Secret fields, tokens, and private-key patterns are sanitized or rejected before entering the ignored artifact directory.

Diagnostic helpers execute in POSIX subshells and use namespaced state. A path guard requires the unique run root and every Pod destination to remain beneath `.artifacts/gitops-network`, rejecting traversal, symlinks, special files, and file-as-directory collisions before writing.

## Removal and ownership reversal

Neither Application includes a resource finalizer and pruning is disabled:

1. Remove `platform-environment` only after confirmation. The child and workload remain.
2. Remove `golden-path-api` only after reviewing health. Workload resources remain orphaned.
3. Confirm the historical `platform-apps/golden-path` Helm release record still exists.
4. Confirm `make app-ownership-status` no longer reports live Argo ownership.
5. Use a separately approved guarded Helm upgrade to resume Helm management.

Controller removal preserves Argo CRDs by default and therefore may preserve the hardened built-in project. Do not restore wildcard permissions as part of rollback. Removing the project or its CRD requires separate destructive approval after proving that no Application or AppProject consumer remains.

Never use cascading deletion and never edit or delete the Helm release Secret manually.

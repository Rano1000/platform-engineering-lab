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

Steady-state requests total approximately 275m CPU and 704Mi memory. Combined limits are approximately 1.35 CPU and 1.4Gi memory. Redis and repository caches use disposable `emptyDir`; no PVC is created.

## Commands

- `make gitops-install`: guarded controller installation; cluster-scoped CRDs and RBAC are created.
- `make gitops-bootstrap`: one-time manual application of both projects and the root Application.
- `make gitops-status`: read-only component and reconciliation status.
- `make gitops-root-status` and `make gitops-root-diff`: read-only environment-definition status and diff.
- `make gitops-root-sync`: confirm stage 1 and update only the child Application specification.
- `make gitops-app-status` and `make gitops-app-diff`: read-only workload status and diff.
- `make gitops-app-sync`: separately confirm stage 2 and update workload resources.
- `make gitops-network-test`: run worker-pinned, single-assertion API egress diagnostics. Each result and its sanitized Kubernetes evidence are retained under `.artifacts/gitops-network`; cleanup follows successful capture.
- `make gitops-validate`: read-only runtime security and health validation.
- `make gitops-uninstall`: guarded removal that refuses while the Application exists.
- `make app-ownership-status`: report Helm or Argo ownership without mutation.

The `argocd` CLI must be exactly v3.5.2 for diff and sync. It uses core mode and Kubernetes authentication; no Argo administrator or public server is required.

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

Never use cascading deletion and never edit or delete the Helm release Secret manually.

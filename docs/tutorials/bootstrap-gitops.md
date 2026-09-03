# Bootstrap GitOps

The root Application is bootstrapped once. It observes merged child Application definitions but never synchronizes them automatically.

1. Run `make validate` and `make phase4-check`.
2. Inspect existing application ownership with `make app-ownership-status`.
3. Review Argo chart values, cluster-scoped CRDs, RBAC, NetworkPolicies, and resource controls.
4. Obtain separate runtime approval, then run `make gitops-install`. The guard discovers and verifies the API endpoint, prints its identity checksum, applies exact generated policies, and asks for the exact cluster name. The single atomic Helm operation has a fixed 15-minute deadline because initial digest-pinned image pulls can take several minutes. After Helm succeeds, the installer performs the separately confirmed, identity-bound transfer of the built-in `default` AppProject to the checksummed repository-owned deny-all state before reporting completion.

If Docker restarts an existing kind cluster, first run the read-only validators and rediscover the API endpoint. Do not rerun installation to repair endpoint drift. After reviewing the exact old and new identities, obtain separate approval for `make gitops-api-policy-reconcile`; it changes only the identity annotation and `/32` destination on the three existing Argo API policies and never runs Helm or synchronizes an Application.
5. The installation transaction runs worker-pinned, single-assertion network checks, compares endpoint snapshots A and B, and only then starts Helm. Each operation writes structured and sanitized evidence beneath `.artifacts/gitops-network` before temporary cleanup. Snapshot C and live-policy checks run after Helm. A failed check stops without widening a rule or retrying automatically.
6. Run `make gitops-validate`.
7. Run `make gitops-bootstrap` once. It applies the dedicated `platform-bootstrap` and `platform-apps` projects and `platform-environment`; it does not apply a child or workload. Root and child Applications must use these dedicated projects and cannot use the deny-all `default` project.
8. Install the pinned repository-local CLI with `make gitops-cli-install`. The ignored binary cache requires neither root access nor a system `PATH` change.
9. After a promotion merges, run `make gitops-root-status` and `make gitops-root-diff`. The diff reports the complete `environmentRevision` and deterministic child-specification SHA-256.
10. Confirm stage 1 with `make gitops-root-sync`. Its confirmation contains context, root name, environment revision, chart revision, image source revision, image digest, and specification checksum. It updates only `gitops/golden-path-api` from the immutable environment revision.
11. Confirm the child is OutOfSync with `make gitops-app-status` and inspect `make gitops-app-diff`.
12. Review the current-Helm versus proposed-Argo workload diff. It must not unexpectedly rename, recreate, or delete application resources.
13. Obtain a second approval and run `make gitops-app-sync`.
14. Validate workload health, routing, security, and ownership.

The historical Helm release record remains untouched. Helm mutation guards activate only after the live Deployment carries the child Application's Argo tracking identity.

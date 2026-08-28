# Bootstrap GitOps

The root Application is bootstrapped once. It observes merged child Application definitions but never synchronizes them automatically.

1. Run `make validate` and `make phase4-check`.
2. Inspect existing application ownership with `make app-ownership-status`.
3. Review Argo chart values, cluster-scoped CRDs, RBAC, NetworkPolicies, and resource controls.
4. Obtain separate runtime approval, then run `make gitops-install`. The guard discovers and verifies the API endpoint, prints its identity checksum, applies exact generated policies, and asks for the exact cluster name.
5. The installation transaction runs worker-pinned positive and negative network checks, compares endpoint snapshots A and B, and only then starts Helm. Snapshot C and live-policy checks run after Helm. A failed check stops without widening a rule or retrying automatically.
6. Run `make gitops-validate`.
7. Run `make gitops-bootstrap` once. It applies both restricted projects and `platform-environment`; it does not apply a child or workload.
8. After a promotion merges, run `make gitops-root-status` and `make gitops-root-diff`. The diff reports the complete `environmentRevision` and deterministic child-specification SHA-256.
9. Confirm stage 1 with `make gitops-root-sync`. Its confirmation contains context, root name, environment revision, chart revision, image source revision, image digest, and specification checksum. It updates only `gitops/golden-path-api` from the immutable environment revision.
10. Confirm the child is OutOfSync with `make gitops-app-status` and inspect `make gitops-app-diff`.
11. Review the current-Helm versus proposed-Argo workload diff. It must not unexpectedly rename, recreate, or delete application resources.
12. Obtain a second approval and run `make gitops-app-sync`.
13. Validate workload health, routing, security, and ownership.

The historical Helm release record remains untouched. Helm mutation guards activate only after the live Deployment carries the child Application's Argo tracking identity.

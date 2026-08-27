# Bootstrap GitOps

The root Application is bootstrapped once. It observes merged child Application definitions but never synchronizes them automatically.

1. Run `make validate` and `make phase4-check`.
2. Inspect existing application ownership with `make app-ownership-status`.
3. Review Argo chart values, cluster-scoped CRDs, RBAC, NetworkPolicies, and resource controls.
4. Obtain separate runtime approval, then run `make gitops-install` and confirm the exact cluster name.
5. Run `make gitops-validate`.
6. Run `make gitops-bootstrap` once. It applies both restricted projects and `platform-environment`; it does not apply a child or workload.
7. After a promotion merges, run `make gitops-root-status` and `make gitops-root-diff`. The diff reports the complete `environmentRevision` and deterministic child-specification SHA-256.
8. Confirm stage 1 with `make gitops-root-sync`. Its confirmation contains context, root name, environment revision, chart revision, image source revision, image digest, and specification checksum. It updates only `gitops/golden-path-api` from the immutable environment revision.
9. Confirm the child is OutOfSync with `make gitops-app-status` and inspect `make gitops-app-diff`.
10. Review the current-Helm versus proposed-Argo workload diff. It must not unexpectedly rename, recreate, or delete application resources.
11. Obtain a second approval and run `make gitops-app-sync`.
12. Validate workload health, routing, security, and ownership.

The historical Helm release record remains untouched. Helm mutation guards activate only after the live Deployment carries the child Application's Argo tracking identity.

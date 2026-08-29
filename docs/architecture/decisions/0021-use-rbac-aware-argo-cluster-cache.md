# ADR-0021: Use Argo CD's RBAC-aware cluster cache

- Status: Accepted
- Date: 2026-08-29

## Context

The application controller has exact write permissions for approved workload kinds and read-only permissions for their supporting resources. With Argo CD's default cache behavior, API discovery still attempts to list every served kind. The restricted controller therefore stopped comparison at the first unrelated cluster-scoped denial.

Granting broad read visibility would exceed the workload boundary. Maintaining resource exclusions for every unrelated API would be brittle as CRDs change.

## Decision

Set `resource.respectRBAC: normal` in `argocd-cm`. Argo CD 3.5 documents this mode as stopping watches after a list call is forbidden or unauthorized. Keep the existing exact controller rules as a closed contract and add no permission for admission webhooks or other unrelated APIs.

Do not use `strict`: it requires permission to create `SelfSubjectAccessReview` resources. Do not use wildcards, secrets access, impersonation, or cluster-admin. The approved workload write verbs remain unchanged; supporting Pods, namespaces, ReplicaSets, and EndpointSlices retain only `get`, `list`, and `watch`. Event creation and patching remain the only supporting write exception required for Argo operation reporting.

## Consequences

The API server may receive an initial denied list request for an unrelated kind before the controller excludes it. This is expected and materially narrower than granting visibility. The controller must be reconciled through the pinned Helm configuration before the existing root Application can complete comparison.

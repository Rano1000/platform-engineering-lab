# ADR-0020: Adopt the built-in Argo default project with a scoped ownership transfer

- Status: Accepted
- Date: 2026-08-28

## Context

Argo CD creates `gitops/AppProject default` with wildcard repository, destination, and cluster-resource permissions. The Argo server owns those fields, so ordinary Server-Side Apply correctly rejects the repository's deny-all manifest as a field-ownership conflict.

Leaving the project permissive would provide an unintended path around the dedicated bootstrap and workload projects. A general forced apply would be too broad.

## Decision

Use a resource-specific, fail-closed Server-Side Apply ownership transfer. Forced conflict resolution exists only in the default-project transaction and uses field manager `platform-engineering-lab-default-project`.

The transaction accepts only the untouched built-in permissive specification owned solely by `argocd-server`, or the already-hardened repository state. It rejects Applications using the default project, unexpected managers, changed identity or resource version, expanded dry-run mutations, and concurrent changes. The operator confirms an identity containing the context, resource, UID, current checksum, and desired checksum. One live apply is followed by immediate and bounded-stabilization verification.

## Consequences

The built-in project remains present but grants no source, destination, or resource permissions. Root and workload Applications must use their dedicated projects. The operation is idempotent once the dedicated manager owns the reviewed fields.

This deliberately narrow use of `--force-conflicts` must not be moved into a shared apply helper or reused for another resource.

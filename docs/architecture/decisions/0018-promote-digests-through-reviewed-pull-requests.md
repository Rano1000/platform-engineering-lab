# ADR-0018: Promote immutable digests through reviewed pull requests

- Status: Accepted
- Date: 2026-08-27

## Context

Image production must not directly change deployment state, and a desired-state update must not recursively publish another image.

## Decision

After cryptographic verification and digest rescanning, automation uses only `GITHUB_TOKEN` to open an idempotent image-promotion branch. Evidence records separate chart and image-source revisions plus the image, SBOM, vulnerability-report, scanner, and attestation identities.

A chart-only main change validates against the currently approved digest and opens an idempotent chart-promotion branch. It changes only `chartRevision` in the child Application and evidence. Desired-state-only and unrelated changes create no promotion. Both promotion paths refuse unrelated branches, force pushes, a different open promotion, mutable tags, mismatched evidence, missing attestations, and stale revisions.

The root Application detects merged desired state from `main`, but root and workload synchronization remain two separate manual operations. Pruning and cascading deletion remain disabled.

## Consequences

Promotion remains reviewable and rollback follows Git history. GitHub suppresses normal workflow recursion for pull requests created with `GITHUB_TOKEN`; a repository writer must manually start or approve required validation. The repository setting allowing Actions to create pull requests must also be enabled before the first promotion.

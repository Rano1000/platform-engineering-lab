# ADR-0016: Publish verified application images to public GHCR

- Status: Accepted
- Date: 2026-08-27

## Context

GitOps nodes must pull an immutable image rather than depend on a workstation-local kind image. A private package would require a long-lived Kubernetes pull credential.

## Decision

Publish the exact checksummed CI archive to `ghcr.io/rano1000/golden-path-api` through a separate manual workflow. The workflow accepts only a successful forced validation run, requires explicit repository-variable approval and typed immutable confirmation, and never rebuilds. The package must be public and linked to this repository before a separate promotion can continue. Desired state uses only the registry-generated digest.

## Consequences

The image is publicly readable and needs no cluster pull secret. The publication job alone receives `packages: write`; no job receives package deletion permission. First publication and the manual visibility change require separate approval outside this repository implementation.

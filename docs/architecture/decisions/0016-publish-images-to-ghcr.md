# ADR-0016: Publish verified application images to public GHCR

- Status: Accepted
- Date: 2026-08-27

## Context

GitOps nodes must pull an immutable image rather than depend on a workstation-local kind image. A private package would require a long-lived Kubernetes pull credential.

## Decision

Publish the exact checksummed CI archive to `ghcr.io/rano1000/golden-path-api`. Publication runs only for reviewed `main` changes affecting image bytes and only after explicit repository-variable approval. The package must be public and linked to this repository before promotion continues. Desired state uses only the registry-generated digest.

## Consequences

The image is publicly readable and needs no cluster pull secret. The publication job alone receives `packages: write`; no job receives package deletion permission. First publication and the manual visibility change require separate approval outside this repository implementation.

# ADR-0001: Use kind for local Kubernetes

- Status: Accepted
- Date: 2026-08-13

## Context

The project needs a disposable Kubernetes target that behaves consistently on developer workstations and CI runners. It must expose Kubernetes concepts directly and avoid a permanent cloud dependency.

## Decision

Use kind as the supported local Kubernetes implementation. Cluster configuration and lifecycle automation will be introduced in Phase 1, not Phase 0.

## Consequences

Developers need Docker and kind. Clusters are inexpensive to recreate and suitable for automated integration tests. Container networking and storage differ from managed cloud services, so cloud-specific behavior requires separate validation.

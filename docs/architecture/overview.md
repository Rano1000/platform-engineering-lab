# Architecture overview

## Purpose

Platform Engineering Lab is a reference environment for evaluating platform contracts and operating practices. It favors transparent components and version-controlled state over opaque automation.

Phase 1 defines a reproducible local Kubernetes baseline. Phase 2 defines a reference workload and Gateway API delivery path. Repository configuration exists, but cluster state must be validated independently and is not implied by this documentation.

## Planned system context

```mermaid
flowchart TB
    Developer[Developer] --> Repository[Git repository]
    Repository --> CI[Validation pipeline]
    Repository -. desired state .-> Argo[Argo CD]
    Argo -. reconciliation .-> Kubernetes[kind Kubernetes]
    Kubernetes --> Gateway[Traefik Gateway API configuration]
    Gateway --> Workloads[Golden-path API configuration]
    Kubernetes -. governed by .-> Policy[Policy controls]
    Kubernetes -. observed by .-> Telemetry[Metrics and dashboards]
```

## Architectural boundaries

- **Repository foundation:** governance, decisions, documentation, diagnostics, and validation. Implemented.
- **Kubernetes baseline:** defines a guarded three-node local cluster, namespaces, and baseline controls. Repository implementation is available; runtime state is environment-dependent.
- **GitOps bootstrap:** installs the minimum GitOps entry point. Planned for Phase 4.
- **Platform services:** Traefik Gateway API configuration is available in Phase 2; policy and monitoring services remain planned.
- **Workloads:** the independently packaged golden-path API is available in Phase 2; runtime deployment remains environment-dependent.
- **Infrastructure:** optional provisioning outside Kubernetes. Planned for a cloud extension.

Git will be the source of desired configuration. CI will validate proposed state; Argo CD will eventually reconcile accepted state. Direct cluster access remains a diagnostic and recovery mechanism rather than the normal delivery path.

## Quality attributes

- **Reproducibility:** versions and inputs are explicit.
- **Security:** least privilege, immutable dependencies, and secret-free Git history.
- **Operability:** health, ownership, failures, and recovery paths are visible.
- **Portability:** local concepts transfer to managed Kubernetes without forcing identical infrastructure.
- **Approachability:** one supported path is documented before optional alternatives.

## Decisions

- [ADR-0001: Use kind for local Kubernetes](decisions/0001-use-kind-for-local-kubernetes.md)
- [ADR-0002: Use Helm for application packaging](decisions/0002-use-helm-for-application-packaging.md)
- [ADR-0003: Use Argo CD for GitOps](decisions/0003-use-argo-cd-for-gitops.md)
- [ADR-0004: Use a phased platform architecture](decisions/0004-use-a-phased-platform-architecture.md)
- [ADR-0005: Use a three-node local cluster](decisions/0005-use-a-three-node-local-cluster.md)
- [ADR-0006: Reserve local HTTP and HTTPS ports](decisions/0006-reserve-local-http-and-https-ports.md)
- [ADR-0007: Isolate platform namespaces](decisions/0007-isolate-platform-namespaces.md)
- [ADR-0008: Constrain local workload resources](decisions/0008-constrain-local-workload-resources.md)
- [ADR-0009: Use Python and FastAPI for the reference API](decisions/0009-use-python-and-fastapi.md)
- [ADR-0010: Use a minimal non-root application container](decisions/0010-use-a-minimal-container.md)
- [ADR-0011: Package the reference application with Helm](decisions/0011-package-applications-with-helm.md)
- [ADR-0012: Use Traefik with Kubernetes Gateway API](decisions/0012-use-traefik-with-gateway-api.md)

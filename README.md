# Platform Engineering Lab

A maintainable reference environment for designing, operating, and validating an internal developer platform from first principles.

## Problem statement

Platform teams need a safe way to evaluate delivery standards, GitOps workflows, policy, and observability without hiding the operational details. This repository will provide that environment while keeping every capability explicit, reproducible, and reviewable.

Phase 0 established repository governance and validation. Phase 1 defines the local Kubernetes baseline. Phase 2 now defines a reference API, secure image contract, Helm packaging, and Gateway API configuration; runtime state remains independently verifiable and is never inferred from repository content.

## Platform capabilities

The following capabilities are planned and will be delivered incrementally:

- Reproducible local Kubernetes with kind
- Helm-based application packaging and a documented workload contract
- Argo CD reconciliation and environment promotion through Git
- Metrics, dashboards, alerting, and reliability exercises
- Kubernetes admission policy and workload isolation
- Reusable service onboarding and an optional developer portal
- An optional cloud implementation using Terraform

## Architecture

```mermaid
flowchart LR
    Developer[Developer] --> Git[Git repository]
    Git --> CI[Safe validation]
    Developer --> Build[Revision-labelled image build]
    Build --> Kind[kind image load]
    Git -. planned .-> Argo[Argo CD]
    Argo -. planned reconciliation .-> Kind
    Kind --> Gateway[Traefik Gateway API]
    Gateway --> App[Golden-path API]
    Kind -. planned .-> Observability[Observability stack]
```

Solid lines describe implemented repository workflows; they do not claim that runtime components are installed. Dashed lines are planned capabilities. See the [architecture overview](docs/architecture/overview.md) for boundaries and ownership.

## Technology stack

| Area | Technology | Status |
| --- | --- | --- |
| Repository automation | Make and portable shell | Available in Phase 0 |
| Local Kubernetes | kind and kubectl | Phase 1 repository implementation available |
| Packaging | Helm | Phase 2 repository implementation available |
| Local routing | Traefik and Gateway API | Phase 2 repository implementation available |
| Infrastructure | Terraform and Ansible | Reserved for later phases |
| Continuous delivery | Argo CD | Planned for Phase 4 |
| Policy | Kyverno | Planned for Phase 6 |
| Observability | Prometheus and Grafana | Planned for Phase 5 |

## Roadmap

0. **Repository foundation:** complete—governance, documentation, ADRs, diagnostics, and safe validation.
1. **Kubernetes baseline:** complete—three-node kind cluster, guarded lifecycle, isolation, and runtime validation.
2. **Golden-path workload:** repository implementation available—reference API, secure container, Helm chart, and Gateway API configuration; runtime deployment pending approval.
3. **Continuous integration:** planned workload and supply-chain validation.
4. **GitOps:** planned Argo CD reconciliation and promotion.
5. **Observability and reliability:** planned metrics infrastructure, dashboards, alerts, and failure exercises.
6. **Policy and security:** planned admission controls and workload standards.
7. **Self-service and cloud extensions:** planned templates, optional portal, and managed infrastructure.

## Development status

**Phase 2 repository implementation is available for review.** It defines application source, tests, a container build, a Helm chart, and pinned Traefik Gateway API configuration. This does not claim that the application or Gateway layer is installed. The project does not claim production readiness.

## Prerequisites

Repository validation requires Git, GNU Make, kubectl, and a POSIX-like shell. Cluster creation additionally requires a reachable Docker runtime and stable kind v0.31.0. Supported versions are listed in the [tooling reference](docs/reference/tooling.md).

## Quick start

Validate the repository without changing a cluster:

```sh
make help
make doctor
make validate
```

`make doctor` inspects the environment without installing software or changing machine or cluster state.

After reviewing any existing cluster and persistent data, follow the [cluster creation tutorial](docs/tutorials/create-local-cluster.md). Cluster lifecycle commands are intentionally guarded against the wrong context and arbitrary cluster names.

The [golden-path deployment tutorial](docs/tutorials/deploy-golden-path-application.md) separates repository validation from image builds and cluster mutations.

## Security principles

- Prefer least privilege and deny-by-default controls.
- Keep credentials and private material out of Git.
- Pin third-party automation to immutable versions.
- Validate changes before they reach runtime environments.
- Separate bootstrap authority from continuously reconciled state.
- Introduce policy in audit mode before enforcement where appropriate.

See [SECURITY.md](SECURITY.md) for reporting and handling vulnerabilities.

## Documentation

- [Architecture overview](docs/architecture/overview.md)
- [Local Kubernetes architecture](docs/architecture/local-kubernetes.md)
- [Golden-path application architecture](docs/architecture/golden-path-application.md)
- [Architecture decisions](docs/architecture/decisions/0001-use-kind-for-local-kubernetes.md)
- [Cluster creation tutorial](docs/tutorials/create-local-cluster.md)
- [Cluster reference](docs/reference/cluster.md)
- [Application reference](docs/reference/application.md)
- [Gateway API reference](docs/reference/gateway.md)
- [Platform engineering concept](docs/concepts/platform-engineering.md)
- [Tooling reference](docs/reference/tooling.md)
- [Troubleshooting](docs/troubleshooting.md)

## Contributing

Contributions are welcome through focused issues and pull requests. Read [CONTRIBUTING.md](CONTRIBUTING.md), the [Code of Conduct](CODE_OF_CONDUCT.md), and the [security policy](SECURITY.md) before contributing.

This project is licensed under the [Apache License 2.0](LICENSE).

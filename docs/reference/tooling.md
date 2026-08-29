# Tooling reference

Phase 0 validation uses common command-line tools and does not install them. Version floors are compatibility guidance and will be revised when runtime phases pin exact supported versions.

| Tool | Minimum | Role |
| --- | ---: | --- |
| Git | 2.30 | Source control and formatting checks |
| GNU Make | 4.0 | Stable task interface |
| POSIX shell | POSIX.1-2008 | Repository automation |
| Docker | 24.0 | kind node runtime |
| kubectl | 1.34 | Baseline rendering and cluster operations |
| kind | 0.31.0 | Pinned local cluster lifecycle |
| Helm | 3.14 | Application packaging and pinned Traefik lifecycle |
| Terraform | 1.7 | Version check only |
| Ansible | 2.16 | Version check only |

Optional validation tools are `markdownlint-cli2`, `yamllint`, `shellcheck`, `actionlint`, `kubeconform`, and `gitleaks`. When absent locally, validation reports a warning and retains built-in checks. CI provisions pinned Markdown, YAML, workflow, and Kubernetes schema validators and uses the runner-provided ShellCheck; portable checks cover secret patterns.

Run `make doctor` for readiness details and `make validate` for repository validation. Neither command installs dependencies or changes Kubernetes resources.

Phase 1 pins Kubernetes v1.35.0 to the immutable node-image digest recorded in `platform/bootstrap/kind/cluster.yaml`. The kubectl client must remain within one minor version of that API server. Runtime cluster operations require exactly stable kind v0.31.0; repository validation does not.

To upgrade, select a node image and digest published in the target stable kind release, update all node entries, the runtime version constants, and Pod Security version labels together, then recreate the disposable cluster only after reviewing its workloads and persistent volumes.

Phase 2 pins Traefik Proxy v3.7.10, Traefik chart 41.2.0, and Gateway API Standard CRDs v1.6.1. Upgrade all three only after reviewing their primary-source compatibility notes and rendered RBAC. Python dependencies and the base image are also pinned; application upgrades require a new version and revision-labelled image tag.

Phase 3 uses pip-tools 7.6.1 in a pinned Python container to generate requirement hashes. The Python 3.13.15 slim-bookworm base is pinned to its 2026-08-25 multi-platform security refresh; Bookworm replaces the Trivy-vulnerable Trixie snapshot found during the Phase 3 review. Trivy 0.74.0 runs from the complete multi-platform image digest recorded in ADR-0014. GitHub Actions use full commit pins; upgrades require matching each commit to an official release.

Phase 4 pins Argo CD v3.5.2, chart 10.4.0, and Redis 8.6.4-alpine. Chart retrieval verifies the OCI manifest digest, archive and provenance checksums, and the Argo Helm signing-key fingerprint before rendering. `make gitops-cli-install` installs the official v3.5.2 CLI into the ignored `.tools` cache after checking the pinned official checksum manifest, the exact OS/architecture artifact checksum and size, and the binary's reported version. It does not modify the system path. Promotion uses a checksum-verified GitHub CLI v2.98.0 archive rather than the workstation CLI. Upgrade only after reviewing Argo's Kubernetes compatibility table, every intermediate upgrade note, the complete rendered RBAC and workload set, and all replacement digests.

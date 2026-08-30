# Changelog

All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project intends to follow [Semantic Versioning](https://semver.org/) after its first release.

## [Unreleased]

### Added

- Repository-local, checksum-pinned Argo CD v3.5.2 CLI provisioning for guarded diff and synchronization commands.
- Fail-closed runtime discovery, identity checks, exact `/32` Argo API policies, and worker-pinned network preflight tests for kind/kindnet.
- A manually dispatched, source-run-bound GHCR publication gate that cannot rebuild, promote, or contact Kubernetes.
- A manual, pre-publication image-validation path that cannot authorize GHCR publication or promotion.
- Phase 4 repository contracts for verified public-image publication, reviewed immutable-digest promotion, and manual Argo CD reconciliation.
- A restricted local AppProject, digest-only desired-state template, lightweight pinned Argo CD configuration, and guarded GitOps ownership commands.
- A restricted root Application for merged desired-state detection and separate chart-only promotion without image rebuilds.
- Phase 3 workload and supply-chain validation with a build-once image artifact, CycloneDX SBOM, vulnerability policy, artifact attestations, and weekly dependency update proposals.
- Hash-locked Python dependencies and a pinned containerized lock compiler.
- Phase 2 golden-path FastAPI source, secure container definition, Helm chart, Traefik Gateway API configuration, guarded automation, and documentation.
- Phase 0 repository governance, architecture documentation, diagnostics, and validation.
- Phase 1 three-node kind configuration, namespace baseline, resource controls, network isolation, guarded lifecycle automation, runtime validation, and operational documentation.

### Changed

- Record Phase 3 CI as complete and preserve its residual vulnerability and attestation-verification risks in the Phase 4 promotion evidence.
- Support immutable registry digests in the application chart while preserving the Phase 2 local-tag workflow.
- Separate chart, image-source, OCI, SBOM, and vulnerability-report identities in promotion evidence.
- Resolve root reconciliation to an immutable environment revision and verify a deterministic child-specification checksum before and after synchronization.
- Record completion of the Phase 2 runtime gate while preserving fresh-environment installation caveats.

### Fixed

- Keep the GitOps workload chart within `platform-apps` and create the observability metrics egress policy only as a guarded temporary validation resource.
- Distinguish expected Argo CD diffs from operational failures and accept them only after bounded semantic resource validation.
- Retain atomic, sanitized guarded-diff evidence with canonical JSON-Pointer diagnostics for every proposed Application mismatch.
- Permit only Argo CD's identity-derived child tracking annotation during guarded root-diff normalization.
- Bind every guarded Argo CD core-mode diff and synchronization command to `gitops` through an isolated validated kubeconfig and credential-free core client context.
- Enable Argo CD's RBAC-aware cache so unrelated API denials do not require broader controller visibility.
- Express both dedicated AppProjects' cluster-resource denial as an empty allowlist and test their exact namespaced permissions.
- Adopt Argo CD's permissive built-in default project through an identity-bound, dry-run-validated, resource-specific ownership transfer.
- Harden the built-in Argo CD `default` AppProject to a checksummed repository-owned deny-all specification after controller installation.
- Distinguish an expected absent pre-bootstrap Application from missing CRDs, authorization failures, API failures, and malformed responses.

- Give the single atomic Argo CD installation 15 minutes for initial pinned-image pulls and retain bounded failure diagnostics.
- Make GitOps network-test cleanup UID-aware, observable, idempotent, and tolerant only of verified deletion races.
- Isolate POSIX shell diagnostic helper state and reject artifact path traversal, symlinks, and file-directory collisions.
- Split ambiguous GitOps network checks into bounded single-assertion Pods with structured, sanitized pre-cleanup diagnostics.
- Replace ineffective pre-DNAT Kubernetes Service allowances with verified post-DNAT API endpoint policies for Argo CD.
- Resolve application validation from the deployed Helm or Argo image identity instead of the current repository revision.
- Permit only the Argo CD Redis initialization hook to reach Kubernetes API TCP 443 under default-deny egress.
- Isolate Trivy cache state from the allowlisted publication-evidence artifact.
- Refresh Python dependencies and use the fixed Bookworm base after the supply-chain gate identified fixable HIGH vulnerabilities.
- Validate scalar EndpointSlice readiness, use authorized in-cluster clients, and secure temporary network-test Pods.
- Give the application ten seconds to bind its listening socket before startup probes begin.
- Validate Traefik's digest-only runtime image reference and disable unnecessary outbound version checks.
- Record the complete Git commit in OCI revision metadata while retaining readable 12-character image tags.
- Restrict public routing to the exact root path and verify pinned Gateway artifacts before installation.
- Route localhost HTTP and HTTPS through fixed Traefik NodePorts without Pod host ports, preserving Baseline Pod Security enforcement.
- Use a realistic finite timeout for runtime cluster health checks.
- Make shell validation deterministic and enable pinned GitHub Actions workflow linting in CI.
- Resolve shared cluster-library paths correctly during ShellCheck validation.

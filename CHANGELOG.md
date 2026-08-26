# Changelog

All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project intends to follow [Semantic Versioning](https://semver.org/) after its first release.

## [Unreleased]

### Added

- Phase 2 golden-path FastAPI source, secure container definition, Helm chart, Traefik Gateway API configuration, guarded automation, and documentation.
- Phase 0 repository governance, architecture documentation, diagnostics, and validation.
- Phase 1 three-node kind configuration, namespace baseline, resource controls, network isolation, guarded lifecycle automation, runtime validation, and operational documentation.

### Fixed

- Validate scalar EndpointSlice readiness, use authorized in-cluster clients, and secure temporary network-test Pods.
- Give the application five seconds to bind its listening socket before startup probes begin.
- Validate Traefik's digest-only runtime image reference and disable unnecessary outbound version checks.
- Record the complete Git commit in OCI revision metadata while retaining readable 12-character image tags.
- Restrict public routing to the exact root path and verify pinned Gateway artifacts before installation.
- Route localhost HTTP and HTTPS through fixed Traefik NodePorts without Pod host ports, preserving Baseline Pod Security enforcement.
- Use a realistic finite timeout for runtime cluster health checks.
- Make shell validation deterministic and enable pinned GitHub Actions workflow linting in CI.
- Resolve shared cluster-library paths correctly during ShellCheck validation.

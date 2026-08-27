# ADR-0015: Separate CI validation from deployment

- Status: Accepted
- Date: 2026-08-27

## Context

Phase 3 must validate contributor changes safely, including fork pull requests, without risking the persistent local platform.

## Decision

Phase 3 CI receives no kubeconfig, deployment credential, or image publication permission. It does not contact Kubernetes, use `pull_request_target`, publish to GHCR, enable HPA, or configure TLS. Default workflow permission is `contents: read`; only the main-push attestation job receives identity-token and attestation write permissions.

Phase 4 extends this decision through [ADR-0016](0016-publish-images-to-ghcr.md): a separately gated job may publish a verified artifact, but it still cannot deploy or edit desired state. Publication and deployment authority remain separated.

## Consequences

The pipeline proves source, image, Helm, and supply-chain contracts but does not prove deployment behavior on every change. A disposable-cluster integration job remains a separately approved future extension. GitOps deployment begins in Phase 4, not here.

# ADR-0015: Separate CI validation from deployment

- Status: Accepted
- Date: 2026-08-27

## Context

Phase 3 must validate contributor changes safely, including fork pull requests, without risking the persistent local platform.

## Decision

CI receives no kubeconfig, deployment credential, or image publication permission. It does not contact Kubernetes, use `pull_request_target`, publish to GHCR, enable HPA, or configure TLS. Default workflow permission is `contents: read`; only the main-push attestation job receives identity-token and attestation write permissions.

## Consequences

The pipeline proves source, image, Helm, and supply-chain contracts but does not prove deployment behavior on every change. A disposable-cluster integration job remains a separately approved future extension. GitOps deployment begins in Phase 4, not here.

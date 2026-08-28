# ADR-0019: Discover kind API endpoints for NetworkPolicy

- Status: Accepted
- Date: 2026-08-28

## Context

kindnet evaluated cross-node Pod egress after kube-proxy translated the Kubernetes Service from `10.96.0.1:443` to the control-plane endpoint. A policy allowing only the Service ClusterIP therefore blocked the Argo CD Redis initialization hook. Kubernetes documents the order of Service translation and NetworkPolicy enforcement as implementation dependent.

## Decision

The guarded Argo CD installer discovers exactly one Ready Kubernetes EndpointSlice endpoint and verifies it against the control-plane InternalIP, kind Docker-network attachment, and host-networked kube-apiserver TCP 6443 listener. It renders three `/32` egress policies from a version-controlled template for the Redis secret-init hook, application controller, and internal API server.

Canonical snapshots A, B, and C cover discovery, immediately-before-Helm, and post-Helm state. Any protected identity change stops the transaction. A SHA-256 over the canonical identity binds the generated and live policies. Worker-pinned, single-assertion preflight Pods prove the three selected identities can reach the API while repository-server, Redis, unlabelled, public TCP 443, and unrelated TCP 6443 paths remain denied.

Each probe has a two-second operation timeout inside a twenty-second Pod deadline and emits one structured JSON result. Pod logs, status, termination state, description, events, policy YAML, EndpointSlice identity, and node placement are sanitized and retained under the ignored `.artifacts/gitops-network` directory before cleanup. Missing or credential-bearing diagnostics stop cleanup so evidence is not destroyed.

The hook, application controller, and API server use chart-supported required node affinity that excludes control-plane nodes. This prevents kind's node-local traffic exception from concealing an incorrect policy.

## Consequences

This is deliberately kind/kindnet-specific and fail-closed. Cluster recreation or an API endpoint change requires regeneration through the installer; no subnet is widened and no address is hard-coded. The generated policy is runtime state, while its template and validation are version controlled.

Traefik currently retains a ClusterIP API rule and runs on the control plane, where node-local behavior can mask the same assumption. That Phase 2 policy requires a separate future review and is unchanged by this decision.

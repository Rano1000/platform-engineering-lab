# ADR-0006: Reserve local HTTP and HTTPS ports

- Status: Accepted
- Date: 2026-08-14

## Context

Planned ingress needs stable local entry points without exposing development services to the surrounding network.

## Decision

Map host ports 80 and 443 on `127.0.0.1` to the control-plane node and label that node `ingress-ready=true`. Do not install an ingress controller in Phase 1.

## Consequences

Later ingress can use conventional URLs without recreating the cluster. Cluster creation fails safely when either host port is occupied. Remote clients cannot use these loopback bindings directly.

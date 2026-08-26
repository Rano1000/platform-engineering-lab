# ADR-0006: Reserve local HTTP and HTTPS ports

- Status: Accepted
- Date: 2026-08-14
- Amended: 2026-08-26

## Context

Planned ingress needs stable local entry points without exposing development services to the surrounding network.

## Decision

Map `127.0.0.1:80` to control-plane container port 30080 and `127.0.0.1:443` to control-plane container port 30443. These are fixed NodePorts for the Phase 2 Traefik Service. Label the node `ingress-ready=true`. Do not install a Gateway controller in Phase 1.

## Consequences

Local clients retain conventional URLs, and remote clients cannot use the loopback bindings directly. Traefik can satisfy Baseline Pod Security because it does not need `hostPort` or `hostNetwork`. Cluster creation fails safely when either host port is occupied.

kind port mappings are immutable. The mapping amendment therefore requires one separately approved recreation of an existing cluster after repository review and commit.

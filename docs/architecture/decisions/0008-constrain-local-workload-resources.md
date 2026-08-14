# ADR-0008: Constrain local workload resources

- Status: Accepted
- Date: 2026-08-14

## Context

Unbounded workloads can exhaust an 8 GiB-class workstation and destabilize the local control plane.

## Decision

Apply a LimitRange and ResourceQuota to `platform-apps`. Default each container to a 100m CPU and 128 MiB request with a 500m CPU and 512 MiB limit. Cap aggregate application memory limits at 3 GiB, Pod count at 15, requested storage at 20 GiB, and each claim at 10 GiB.

## Consequences

Accidental resource consumption is bounded and omitted container resources receive defaults. These values are local safety limits, not production capacity guidance, and must be reviewed as platform services are added.

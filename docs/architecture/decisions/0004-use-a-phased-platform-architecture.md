# ADR-0004: Use a phased platform architecture

- Status: Accepted
- Date: 2026-08-13

## Context

Installing every planned platform component at once would hide dependencies, consume unnecessary resources, and make failures difficult to isolate.

## Decision

Deliver the platform in independently verifiable phases: repository foundation, Kubernetes baseline, golden-path workload, CI, GitOps, observability, policy, and optional self-service and cloud extensions.

## Consequences

Each phase has explicit prerequisites and exit criteria. Documentation must distinguish current from planned behavior. Some end-to-end capabilities remain intentionally unavailable until their owning phase is complete.

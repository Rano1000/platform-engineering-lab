# ADR-0007: Isolate platform namespaces

- Status: Accepted
- Date: 2026-08-14

## Context

Unrestricted namespace traffic makes application dependencies implicit and weakens containment.

## Decision

Create five owned namespaces with default-deny ingress and egress. Permit only DNS egress to CoreDNS initially. Enforce Restricted Pod Security for applications and Baseline with Restricted warnings and audit for future controller namespaces.

## Consequences

New workloads cannot communicate until their required flows are reviewed and declared. Later phases must add narrowly scoped policies with each component. Kubernetes system namespaces remain unchanged.

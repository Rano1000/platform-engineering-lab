# ADR-0003: Use Argo CD for GitOps

- Status: Accepted
- Date: 2026-08-13

## Context

The platform needs an observable reconciliation loop that compares approved Git state with Kubernetes state and supports controlled recovery from drift.

## Decision

Use Argo CD for continuous delivery beginning in Phase 4. Git will describe desired state; routine deployment will occur through reviewed repository changes.

## Consequences

Deployment state and drift become visible, and rollback can follow Git history. Argo CD introduces a privileged control plane component, so bootstrap permissions, project boundaries, and repository credentials require careful design before installation.

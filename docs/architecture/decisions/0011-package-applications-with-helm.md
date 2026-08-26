# ADR-0011: Package the reference application with Helm

- Status: Accepted
- Date: 2026-08-26

## Context

The application needs a reusable workload contract with validated configuration and secure defaults.

## Decision

Package the API as a Helm application chart with JSON Schema validation. Include the Deployment, Service, ConfigMap, ServiceAccount, HTTPRoute, NetworkPolicy, PodDisruptionBudget, and optional HorizontalPodAutoscaler.

## Consequences

Rendered manifests remain reviewable and environment inputs are explicit. Helm becomes required for application lifecycle operations. Autoscaling stays disabled until a resource metrics API is deliberately installed.

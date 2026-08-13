# ADR-0002: Use Helm for application packaging

- Status: Accepted
- Date: 2026-08-13

## Context

Applications need a versioned, reusable packaging format with configurable environment values and pre-deployment rendering checks.

## Decision

Use Helm charts for application packaging. Charts will own workload-specific Kubernetes resources and will expose a constrained, schema-validated values interface beginning in Phase 2.

## Consequences

Teams gain standard packaging, templating, and release metadata. Templates can become difficult to understand if they contain excessive logic, so chart helpers and values will remain deliberately narrow and rendered output will be validated.

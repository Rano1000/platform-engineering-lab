# ADR-0009: Use Python and FastAPI for the reference API

- Status: Accepted
- Date: 2026-08-26

## Context

The golden-path workload needs concise health, metrics, lifecycle, configuration, logging, and test behavior without adding a database.

## Decision

Use Python 3.13, FastAPI, Uvicorn, and the Prometheus Python client. Pin direct and transitive dependencies. Keep configuration environment-backed and the service stateless.

## Consequences

The implementation is small enough to audit while still demonstrating an ASGI lifecycle and production-style probes. Python runtime and dependency updates require explicit review and image rebuilds.

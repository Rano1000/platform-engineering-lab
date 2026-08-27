# ADR-0017: Run a lightweight pinned Argo CD installation

- Status: Accepted
- Date: 2026-08-27

## Context

The local cluster needs an observable reconciliation loop without exceeding a 7.6 GiB workstation budget or exposing another administrative endpoint.

## Decision

Use Argo CD Helm chart 10.4.0 at OCI digest `sha256:8ff18ee7a22670305555167ea31f24a88e2f912cf0a872f852e1880886d4c308`. Verify its content archive checksum, provenance-layer checksum, and Helm signature against the pinned Argo Helm signing key fingerprint `2B8F22F57260EFA67BE1C5824B11F800CD9D2252`. The chart declares Argo CD 3.5.1; override every Argo component with v3.5.2 at `sha256:e2aadfae709d904e87f46ba4aa49601d827b3022db22cd4d03aae816a2e7097b`. Use Redis 8.6.4-alpine at `sha256:2cc044fc5a07c9b701f8f1255a309ae9ad7856e694ac03513bf3648c01e40763`.

The complete chart was rendered for Kubernetes 1.35. Argo CD 3.5 officially tests Kubernetes 1.35, and its patch-release policy treats 3.5.2 as non-breaking. Rendering contains no 3.5.1-specific image or configuration dependency. ApplicationSet renders as a zero-replica Deployment because the chart has no full disable switch; its dormant manifest is still resource- and security-constrained.

## Consequences

This is non-HA and makes no availability claim. Dex, notifications, active ApplicationSet, exporters, external routes, HPA, and persistent storage are disabled. Chart upgrades require reviewing CRDs, rendering every image by digest, and reading all intermediate Argo upgrade notes.

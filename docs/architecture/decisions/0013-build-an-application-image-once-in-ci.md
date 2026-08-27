# ADR-0013: Build an application image once in CI

- Status: Accepted
- Date: 2026-08-27

## Context

Rebuilding in separate jobs can produce different bytes even when the source revision is unchanged. Downstream evidence must describe the artifact that passed testing.

## Decision

CI builds one runtime image after unit tests. The tag uses the first 12 commit characters and the OCI revision uses the complete commit. CI exports one tar archive, records its SHA-256, and passes it through a 14-day workflow artifact. Inspection, SBOM generation, scanning, and attestation consume that exact archive.

## Consequences

CI uses more artifact storage but avoids rebuild ambiguity. No image is published and no registry write permission is granted. The build refuses a dirty local worktree to prevent false revision labels.

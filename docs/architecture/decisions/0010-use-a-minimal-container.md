# ADR-0010: Use a minimal non-root application container

- Status: Accepted
- Date: 2026-08-26

## Context

The reference image must support restricted Kubernetes Pod Security and make its source revision observable.

## Decision

Use a multi-stage Dockerfile based on a digest-pinned Python 3.13 slim image. Run as UID and GID 10001, write logs only to stdout, expose no secrets, and label the image with its complete Git revision. Tags use `0.1.0-<12-character-git-sha>` and never `latest`.

## Consequences

Builds require committed application sources. The readable tag contains the first 12 revision characters, while `org.opencontainers.image.revision` contains the complete 40-character revision. Version changes create a new tag instead of replacing an existing local image.

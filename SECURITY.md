# Security Policy

## Supported versions

The project has not published a stable release. Security fixes are applied to the current `main` branch; no historical release line is supported yet.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub private vulnerability reporting for this repository when available. If it is unavailable, contact the repository maintainers privately through the owning organization.

Include the affected component, reproduction conditions, impact, and any known mitigations. Do not include real credentials or sensitive production data.

Maintainers should acknowledge a report within five business days, establish a private remediation plan, and coordinate disclosure with the reporter. Timelines depend on severity and verification complexity.

## Repository security boundaries

- Examples must use non-sensitive placeholders.
- Local `.env` files, kubeconfigs, keys, state files, and credentials are excluded from version control.
- CI validation must not deploy resources or require production credentials.
- Third-party GitHub Actions are pinned to immutable commit SHAs.

This policy covers the repository content. Future deployed components will document their own threat model and support boundaries before release.

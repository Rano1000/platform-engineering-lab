# Publish and promote an image

Image publication is not enabled by repository content alone. A repository administrator must separately approve first publication, set `GHCR_PUBLICATION_APPROVED=true`, and confirm that Actions may create pull requests.

When an image input changes, Application CI builds once, verifies the archive and SBOM attestations with pinned GitHub CLI v2.98.0, and publishes the exact archive. The first package may be private. Change visibility to public manually, link it to this repository, and rerun the failed job; automation never changes visibility.

Promotion then rescans the exact registry digest, verifies its attestation, and opens a pull request. Review `chartRevision`, `imageSourceRevision`, the complete digest, OCI revision, archive/SBOM/vulnerability-report checksums, vulnerability totals, fixable counts, Trivy version, and database timestamp.

A chart-only change does not build or publish. It validates the chart with the currently approved digest and opens a separate PR changing only `chartRevision` and its matching Application annotation. A desired-state or documentation change creates no promotion PR.

A promotion created with `GITHUB_TOKEN` never auto-merges or auto-approves. A repository writer must manually run or approve the required workflows for its head revision before merge.

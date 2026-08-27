# Publish and promote an image

Image publication is not enabled by repository content alone. A repository administrator must separately approve first publication, set `GHCR_PUBLICATION_APPROVED=true`, and confirm that Actions may create pull requests.

Application CI builds and attests an image but never publishes it. Record the successful forced run ID, source revision, and the archive, SBOM, and vulnerability-report checksums. The separately dispatched `Publish verified image` workflow validates that run through GitHub's API, downloads the retained artifacts, verifies their attestations, and rescans the archive before its write-scoped job can start.

Set `GHCR_PUBLICATION_APPROVED=true` only after reviewing the workflow inputs. The typed confirmation is `Rano1000/platform-engineering-lab/<source-revision>/<archive-sha256>`. The first package may be private. Change visibility to public and link it to this repository manually; automation never changes visibility.

Publication attests and rescans the exact registry digest, then creates checksummed and attested promotion evidence. It never opens a pull request. A later, separately approved promotion workflow must consume that evidence. Review `chartRevision`, `imageSourceRevision`, the complete digest, OCI revision, archive/SBOM/vulnerability-report checksums, vulnerability totals, fixable counts, Trivy version, and database timestamp.

A chart-only change does not build or publish. It validates the chart with the currently approved digest and opens a separate PR changing only `chartRevision` and its matching Application annotation. A desired-state or documentation change creates no promotion PR.

A promotion created with `GITHUB_TOKEN` never auto-merges or auto-approves. A repository writer must manually run or approve the required workflows for its head revision before merge.

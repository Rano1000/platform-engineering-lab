# Continuous integration reference

## Workflows

`Repository validation` retains the general repository checks. `Application supply chain` always runs on pull requests and pushes to `main`, and supports manual dispatch. Its jobs are:

1. `changes`: classify image, chart-only, desired-state-only, or unrelated changes.
2. `repository`: validate repository, dependency-lock, exception-policy, and GitOps contracts.
3. `image`: when required, run unit tests, build one immutable runtime image, and upload its checksummed archive.
4. `supply-chain`: reload that archive, scan secrets and vulnerabilities, and generate a CycloneDX SBOM.
5. `attest-artifacts`: on eligible `main` pushes or forced validation dispatches, attest the exact image archive and SBOM.
6. `chart-promotion`: for chart-only main changes, validate with the approved digest and open a chart-revision-only PR without building.

`Publish verified image` is a separate manual workflow. It accepts an exact successful source run and checksums, verifies source-run identity and retained artifacts, rescans without rebuilding, and requires both the approval variable and typed confirmation. Trivy cache state stays in the runner's temporary directory. An allowlisted staging step rejects non-regular or unexpected inputs and uploads only named evidence files with a checksummed manifest. The original report, pre-publication rescan, and registry-digest rescan are retained separately. Only its final publication job receives `packages: write`. Registry attestation and evidence generation follow publication, but no promotion PR is created.

Artifacts are retained for 14 days. Workflow permissions default to `contents: read`; only publication receives `packages: write`, only attestation receives OIDC and attestation writes, and only promotion receives repository and pull-request writes. Job summaries include unit-test status, immutable image identity, archive and SBOM checksums, finding totals by severity and fix availability, and scanner database metadata.

Application source, its Dockerfile, runtime locks, and image-content build scripts are image inputs. Chart changes form their own category. `environments/local` changes are desired-state-only, and documentation is unrelated. A mixed image-and-chart change updates both revisions; an image-only change preserves the approved chart revision. Promotion PRs therefore cannot publish an image or create another promotion PR, while every category still completes the required workflow.

## Vulnerability policy

Exceptions live in `config/supply-chain/vulnerability-exceptions.json`. Each entry must contain exactly:

- `id`: one CVE or GHSA identifier; wildcards are forbidden.
- `reason`: why the temporary risk is accepted.
- `owner`: person responsible for resolution.
- `created`: ISO date.
- `expires`: ISO date no more than 90 days after creation.

Expired or malformed entries fail before scanning. The full Trivy JSON report includes unfixed findings. The enforcement pass rejects unexcepted, fixable HIGH and CRITICAL findings.

## Artifact identity

The image tag contains the first 12 characters of the workflow commit. The OCI revision label contains the complete 40-character commit. `golden-path-api.tar.sha256` authenticates the archive passed between jobs. The SBOM companion summary records the image reference, revision, Trivy version, and SBOM checksum.

Publication never rebuilds. A pinned, checksum-verified GitHub CLI verifies the archive and SBOM attestations and binds them to the source run before the archive is pushed. The publication workflow verifies the registry-image attestation, records package visibility and linkage, rescans the complete registry digest, and produces attested evidence. Promotion remains a later reviewed operation. The OCI revision must match the image source revision; the child Application renders the chart from the separately approved chart revision.

## Updating dependencies

Edit the direct requirements in `runtime.in` or `test.in`, then run `make dependency-locks-update`. The target builds `tools/dependency-lock/Dockerfile` and invokes pip-compile with `--generate-hashes` inside that pinned container. The compiler's own dependencies are hash-locked in the same directory. Review every resolved-version change and run all application and supply-chain validation. Never edit or invent hashes manually.

Dependabot proposes weekly GitHub Actions, Python, and Docker updates. It cannot merge automatically; every proposal must pass both workflows and normal review.

## Code-scanning availability

The repository is public, but the authenticated read-only API check could not access code-scanning alerts with the current token. Phase 3 therefore retains Trivy JSON as a normal artifact and does not add SARIF permissions. This avoids making an optional account feature a workflow dependency.

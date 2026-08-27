# Continuous integration reference

## Workflows

`Repository validation` retains the general repository checks. `Application supply chain` always runs on pull requests and pushes to `main`, and supports manual dispatch. Its jobs are:

1. `repository`: validate repository, dependency-lock, and exception-policy contracts.
2. `image`: run unit tests, build one immutable runtime image, and upload its checksummed archive.
3. `supply-chain`: reload that archive, scan secrets and vulnerabilities, and generate a CycloneDX SBOM.
4. `attest`: on `main` pushes only, attest the image archive and SBOM without publishing an image.

Artifacts are retained for 14 days. The workflow never uses `packages: write`. Job summaries include unit-test status, immutable image identity, archive and SBOM checksums, finding totals by severity and fix availability, and scanner database metadata.

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

## Updating dependencies

Edit the direct requirements in `runtime.in` or `test.in`, then run `make dependency-locks-update`. The target builds `tools/dependency-lock/Dockerfile` and invokes pip-compile with `--generate-hashes` inside that pinned container. The compiler's own dependencies are hash-locked in the same directory. Review every resolved-version change and run all application and supply-chain validation. Never edit or invent hashes manually.

Dependabot proposes weekly GitHub Actions, Python, and Docker updates. It cannot merge automatically; every proposal must pass both workflows and normal review.

## Code-scanning availability

The repository is public, but the authenticated read-only API check could not access code-scanning alerts with the current token. Phase 3 therefore retains Trivy JSON as a normal artifact and does not add SARIF permissions. This avoids making an optional account feature a workflow dependency.

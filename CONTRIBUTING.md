# Contributing

Thank you for improving Platform Engineering Lab. Contributions should make the platform easier to operate, review, or understand without weakening its security boundaries.

## Before opening a change

1. Search existing issues and architecture decisions.
2. Discuss broad or irreversible design changes before implementation.
3. Keep the change within one architectural phase where practical.
4. Do not include credentials, private infrastructure details, or copied production configuration.

## Development workflow

Create a focused branch from `main`, make the smallest coherent change, and run:

```sh
make doctor
make validate
make ci-check
```

`make doctor` reports environmental readiness. `make validate` performs repository checks and must not modify infrastructure.

Application dependency changes start in the `.in` files and require regeneration with the pinned containerized pip-tools environment. Never hand-edit generated hashes. Dependabot proposals are review requests, not automatic approvals or merges.

Pull requests should state the problem, the chosen approach, validation performed, operational or security implications, and documentation changes. Breaking changes require an ADR and a changelog entry.

## Commit and review expectations

- Write imperative, specific commit subjects.
- Separate refactoring from behavioral changes when possible.
- Update tests and documentation with behavior.
- Resolve automated checks and reviewer feedback before merge.
- Expect additional review for governance, security, CI, and architecture files.

By participating, contributors agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities through the private process in [SECURITY.md](SECURITY.md), not a public issue.

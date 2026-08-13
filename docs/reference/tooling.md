# Tooling reference

Phase 0 validation uses common command-line tools and does not install them. Version floors are compatibility guidance and will be revised when runtime phases pin exact supported versions.

| Tool | Minimum | Phase 0 role |
| --- | ---: | --- |
| Git | 2.30 | Source control and formatting checks |
| GNU Make | 4.0 | Stable task interface |
| POSIX shell | POSIX.1-2008 | Repository automation |
| Docker | 24.0 | Connectivity check only |
| kubectl | 1.30 | Client and context check only |
| kind | 0.23 | Version check only |
| Helm | 3.14 | Version check only |
| Terraform | 1.7 | Version check only |
| Ansible | 2.16 | Version check only |

Optional validation tools are `markdownlint-cli2`, `yamllint`, `shellcheck`, `actionlint`, and `gitleaks`. When absent locally, validation reports a warning and retains built-in checks. CI provisions pinned Markdown and YAML validators and uses the runner-provided ShellCheck; portable checks cover the remaining categories.

Run `make doctor` for readiness details and `make validate` for repository validation. Neither command installs dependencies or changes Kubernetes resources.

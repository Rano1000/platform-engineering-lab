# Troubleshooting

## Doctor reports Docker connectivity failure

Confirm the Docker service or Docker Desktop is running, then run `docker info`. On Linux, verify that your user is authorized to access the configured Docker socket. Do not change socket permissions broadly; use the operating system's documented Docker group or rootless setup.

## A Kubernetes context exists but is unreachable

Run `kubectl config current-context` and confirm it names the cluster you intend to inspect. Then run `kubectl cluster-info`. A stale kind context can remain after its containers stop. Phase 0 does not recreate or delete that cluster.

## Ansible cannot create its temporary directory

Set `ANSIBLE_LOCAL_TEMP` to a writable, private directory for the current session. Managed or containerized environments may expose the home directory as read-only. The doctor uses a temporary location without modifying Ansible configuration.

## Optional linters are missing

Read [the tooling reference](reference/tooling.md) for supported validators. Local validation still performs portable formatting, link, shell syntax, Make parsing, and secret-pattern checks. CI runs the complete pinned validator set.

## Internal link validation fails

Use repository-relative Markdown links, preserve filename case, and avoid linking to files that are planned but do not exist. External URLs are not contacted by the local link check.

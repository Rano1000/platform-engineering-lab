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

## Cluster creation reports an existing context

The lifecycle script refuses to overwrite `kind-platform-engineering-lab` when Docker cannot discover a matching cluster. Inspect `kind get clusters`, `kubectl config get-contexts`, and Docker containers from the normal workstation shell. Do not remove the context until its ownership and any surviving cluster state are understood.

## Ports 80 or 443 are occupied

Inspect both host listeners and published Docker ports. On Linux, `ss -ltn` shows listeners; `docker ps` shows container mappings. Stop only the known owner or revise the architecture through an ADR. The cluster script never takes over an occupied port.

## Runtime validation rejects the active context

Run `kubectl config current-context`. If the intended cluster has been reviewed, select it explicitly with `kubectl config use-context kind-platform-engineering-lab`. The guard prevents validation or mutation of cloud and work clusters.

## Nodes or system Pods do not become Ready

Run `make cluster-status`, then inspect `kubectl describe node` and Pods in `kube-system`. Common causes include memory pressure, an incomplete node-image pull, or Docker resource limits. Preserve the failed cluster for diagnosis rather than recreating it immediately.

## Networked workloads cannot connect

Default-deny policies are intentional. DNS is the only initial egress allowance. Add a reviewed NetworkPolicy for each required source, destination, and port; do not remove the default-deny policy as a shortcut.

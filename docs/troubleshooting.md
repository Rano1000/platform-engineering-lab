# Troubleshooting

## Application image is not found

The chart deliberately uses `imagePullPolicy: Never`. Run `make app-build` from committed sources and `make app-load` before deployment. Confirm that the tag contains the first 12 characters of the current Git revision and the OCI revision label contains all 40; never substitute `latest`.

## HTTPRoute is not accepted

Confirm the Gateway API Standard CRDs are v1.6.1, the `platform-traefik` GatewayClass is Accepted, and `platform-system/platform-gateway` is Programmed. The Gateway accepts routes only from `platform-apps`.

## Traefik NodePorts do not receive localhost traffic

Confirm the Traefik Service owns NodePorts 30080 and 30443 and uses `externalTrafficPolicy: Local`. The Traefik Pod must run on the ingress-ready control-plane. Docker must publish `127.0.0.1:80` to container port 30080 and `127.0.0.1:443` to container port 30443. If the cluster predates this mapping, preserve and inventory it; kind mappings are immutable, so correction requires one separately approved recreation after the repository change is reviewed and committed.

## HPA is absent

This is expected in Phase 2. The chart validates its HPA template statically, but autoscaling defaults off because Metrics Server is not installed.

## Image publication does not run

The workflow publishes only when reviewed image inputs change on `main` and the `GHCR_PUBLICATION_APPROVED` repository variable is `true`. A chart-, documentation-, or environment-only change deliberately reports that publication is not required. First publication and changing the package to public visibility require separate approval.

## A promotion pull request is not created

Confirm the GHCR package is public and linked to this repository, all three attestations verify, the digest rescan passed, and no different promotion PR remains open. The repository must also allow GitHub Actions to create pull requests. This setting is not changed by repository automation, and workflows on a PR created with `GITHUB_TOKEN` require a repository writer to approve or start them.

## Helm application commands refuse to run

This is expected after the `gitops/golden-path-api` Application exists. Use `make app-ownership-status` to inspect ownership. Do not use Helm as a second active manager; follow the documented GitOps reversal procedure before returning ownership to Helm.

## Root synchronization reports that origin/main changed

This is a safety stop. Root diff and sync operate on one complete `environmentRevision`, not mutable `main`. Update local `main`, rerun the root diff, review the new environment revision and child-specification checksum, and confirm again. Never substitute an abbreviated SHA or bypass the second remote check.

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

If `argocd-redis-secret-init` times out while checking its Secret, verify that the repository-owned hook policy selects only that hook and permits `10.96.0.1/32` on TCP 443. This address is the lab's Kubernetes Service IP and assumes kindnet enforces policy before kube-proxy Service translation. Do not add namespace-wide or general HTTPS egress.

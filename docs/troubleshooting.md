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

## A Helm-owned metrics-test policy remains in observability

Earlier Phase 2 chart revisions installed `NetworkPolicy/observability/golden-path-golden-path-api-metrics-test-egress`. The policy is a validation fixture, not application desired state. Do not widen `AppProject/platform-apps` or delete the live policy during repository reconciliation.

First review the root and child diffs. Because pruning is disabled, synchronizing the corrected chart does not delete the existing Helm-owned policy. A separate exact-resource runtime gate must record its UID and Helm ownership, delete only that named policy, and then run `make app-network-test`. The guarded test creates a uniquely named replacement policy, proves approved and denied metrics flows, and removes its temporary policy and Pods.

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

If `argocd-redis-secret-init` times out while checking its Secret, inspect the endpoint identity printed by `make gitops-install`. The generated hook policy must contain the verified control-plane `/32` and actual kube-apiserver TCP port, not the Kubernetes Service ClusterIP. Compare the Service, Ready EndpointSlice, control-plane InternalIP, kind Docker attachment, and kube-apiserver host IP. Do not hard-code the current Docker address, allow a bridge subnet, add general HTTPS, or disable default-deny.

An A/B/C snapshot mismatch means the protected API identity changed during installation. Preserve the state for diagnosis and start a separately approved clean transaction after the endpoint is stable; do not retry automatically. Generated endpoint policies must be regenerated after kind cluster recreation.

The first Argo CD installation may take several minutes while digest-pinned images are pulled. The guarded Helm operation waits for at most 15 minutes and never retries automatically. Cached images can make a later approved attempt faster, but correctness must not depend on cache state. When the deadline or another Helm check fails, inspect `.artifacts/gitops-install`; atomic rollback removes release workloads but may leave CRDs, hook RBAC, hook-generated Secrets, or other hook resources. Remove residuals only through a separately approved exact-name cleanup.

If GitOps validation reports that `AppProject/default` is permissive, missing, or owned unexpectedly, do not bootstrap an Application. Compare it with `platform/addons/argocd/default-project.yaml`. For an untouched built-in project, `argocd-server` legitimately owns the three wildcard fields. `make gitops-default-project-harden` recognizes only that exact conflict, performs a forced server-side dry-run, verifies the mutation scope, repeats UID/resource-version/specification/owner checks around the identity-bound confirmation, and executes one live apply. Do not manually add `--force-conflicts`: any different manager, specification, Application reference, or concurrent change requires review.

If the post-apply or five-second stabilization check fails, do not retry. Preserve the live object and managed fields for review; the guard treats restored permissions, changed UID, unexpected generation, or lost dedicated ownership as a failure.

Before bootstrap, an absent Application is expected. Runtime validation distinguishes a missing Application CRD from an absent object; authorization, API transport, and malformed-response failures remain errors rather than being reported as absence.

If an Application remains `Unknown` with a cluster-cache denial for an unrelated API such as `ValidatingWebhookConfiguration`, verify the rendered `argocd-cm` contains `resource.respectRBAC: normal` and the application-controller ClusterRole matches the exact repository rules. Do not grant the denied kind one at a time. Normal mode intentionally learns from forbidden list responses and excludes resources outside the controller's RBAC. Applying this configuration requires a separately approved guarded Helm reconciliation; it must not synchronize an Application.

If a guarded GitOps diff reports that the Argo CD CLI is unavailable, run `make gitops-cli-install`. Do not substitute `kubectl exec`, install an unpinned package, or download `latest`. The installer accepts only the official v3.5.2 release artifact for the detected supported platform, verifies it against the pinned official checksum manifest, and stores it beneath the ignored `.tools` directory. A checksum, size, version, redirect-host, platform, or destination-path failure must be investigated rather than bypassed.

Argo CD v3.5.2 normally returns a nonzero status when differences exist. Repository commands assign expected differences the dedicated status `20` and validate every resource and change type before returning success. An empty, additional, malformed, modified root, deleted, or operationally failed diff is a safety stop. Review the sanitized diagnostic and original exit status; do not bypass the validator or add `|| true`.

When the proposed root Application differs from the repository manifest, inspect the unique ignored directory under `.artifacts/gitops-diff`. `differences.json` reports every JSON Pointer, expected and proposed value, missing/additional/changed state, and diagnostic classification. The checksummed evidence manifest must be complete. Defaulted, representational, or Argo-added metadata remains rejected until a separate semantic review approves a narrowly scoped correction.

The sole approved root-diff metadata normalization is Argo's exact child tracking annotation. Missing, duplicate, repository-supplied, or altered tracking identity fails, as does any additional annotation, label, or metadata field. Inspect `normalization-decisions.json`; do not add the runtime annotation to the desired-state manifest.

If core mode reports that `argocd-cm` is absent from the default `argocd` namespace, the guarded namespace isolation is missing or invalid. All repository commands must use the validated temporary kubeconfig and explicit `--app-namespace gitops` binding. Do not change the user's current kubeconfig namespace, export an Argo namespace variable, or copy configuration from a running Pod.

If a GitOps network assertion fails, inspect its unique directory under `.artifacts/gitops-network`. Every probe log is one JSON object naming the source identity, worker, destination, expectation, observation, duration, exit code, and error category. Pod status, termination state, description, events, policies, EndpointSlice, and node evidence are captured before cleanup. An empty or unsafe diagnostic set deliberately leaves temporary resources for separate inspection.

Cleanup evidence is stored beside those records under `cleanup/`. Each JSON file records the original UID, delete command output and status, final GET, duration, and classification. A `NotFound` race is successful only when the final GET independently proves the original UID is absent. Authorization, connectivity, timeout, malformed-response, surviving-UID, and name-reuse results fail closed without deleting a replacement resource.

The original preflight combined API access and two denied destinations in one silent process, then waited only for Pod success. Its timeout therefore could not identify which connection blocked, and cleanup removed the logs. The corrected harness uses one operation per Pod and treats a terminal `Failed` phase immediately rather than waiting for the outer deadline.

A retry intentionally refuses while the obsolete `networkpolicy/argocd-redis-secret-init` from the failed installation remains. Remove it only through a separately approved exact-name cleanup together with the previously recorded hook ServiceAccount, Role, RoleBinding, Job, and Pod residuals. Do not remove baseline resource controls or unrelated NetworkPolicies.

# Create the local Kubernetes cluster

This procedure creates the exact `platform-engineering-lab` kind cluster. It does not install ingress, GitOps, observability, security controllers, or applications.

## Before you begin

Verify that Docker is available from the same shell and that stable kind v0.31.0 is installed:

```sh
docker info
kind version
make doctor
make validate
```

The host must have ports 80 and 443 available on `127.0.0.1`. Three nodes require roughly 2.5–4 GiB before application and platform workloads are added; 8 GiB host memory is recommended.

## Protect an existing cluster

If `kind-platform-engineering-lab` already exists, inspect it before replacement:

```sh
kubectl config use-context kind-platform-engineering-lab
make cluster-status
kubectl get all --all-namespaces
kubectl get persistentvolumes,persistentvolumeclaims --all-namespaces
```

Do not recreate the cluster until its workloads and persistent data are understood. Recreation permanently removes its namespaces, workloads, Services, configuration, Secrets, RBAC, CRDs, and local persistent-volume data.

## Create a new cluster

When no cluster or conflicting context exists:

```sh
make cluster-create
```

The command checks Docker, kind, the target identity, kubeconfig, and host ports before creating anything. It waits for nodes and system Pods, then applies the namespace baseline declaratively.

## Validate the result

```sh
kubectl config current-context
make cluster-status
make cluster-validate
```

Validation intentionally fails if another context is active.

## Lifecycle operations

Use `make namespaces-apply` after reviewing namespace definition changes. Use `make policies-apply` after reviewing quota, limit, or network-policy changes.

`make cluster-destroy` and `make cluster-recreate` are destructive. They display workloads and persistent storage, explain the loss, and require the exact cluster name as confirmation. Never use them until the inventory has been reviewed.

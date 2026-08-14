# Local cluster reference

## Identity and versions

| Property | Value |
| --- | --- |
| Cluster | `platform-engineering-lab` |
| Context | `kind-platform-engineering-lab` |
| kind | v0.31.0 |
| Kubernetes | v1.35.0 |
| Nodes | One control plane, two workers |
| IP family | IPv4 |
| Pod subnet | `10.244.0.0/16` |
| Service subnet | `10.96.0.0/16` |
| HTTP | `127.0.0.1:80` |
| HTTPS | `127.0.0.1:443` |

The node image tag and SHA-256 digest are pinned in `platform/bootstrap/kind/cluster.yaml`. Upgrade kind and Kubernetes together by selecting an image listed in the target stable kind release, updating the version constants and Pod Security version labels, recreating the disposable cluster, and running all static and runtime validation.

kind v0.31.0 generates kubeadm v1beta3 configuration for Kubernetes 1.35.x, so the ingress node-label patch deliberately uses `kubeadm.k8s.io/v1beta3` and its map-form `kubeletExtraArgs`. kind changes its generated configuration to v1beta4 for Kubernetes 1.36+, where the equivalent arguments use `name` and `value` entries. A Kubernetes upgrade across that boundary must update the patch structure in the same change.

## Namespaces

| Namespace | Purpose | Enforced Pod Security |
| --- | --- | --- |
| `platform-system` | Shared platform services | Baseline |
| `platform-apps` | Application workloads | Restricted |
| `observability` | Telemetry services | Baseline |
| `security` | Security services | Baseline |
| `gitops` | Delivery controllers | Baseline |

All owned namespaces identify their environment, owner, purpose, and managing project. Infrastructure namespaces warn and audit against Restricted.

## Application resource budget

Containers without explicit resources receive requests of 100 millicores and 128 MiB, with limits of 500 millicores and 512 MiB. The namespace allows at most 15 Pods, 2 CPU and 2 GiB requested, 4 CPU and 3 GiB limited, five PersistentVolumeClaims, and 20 GiB of requested storage. A single claim cannot exceed 10 GiB.

## Networking

Every owned namespace denies ingress and egress by default. A second policy permits DNS queries only to CoreDNS. Phase 2 application traffic and later platform-controller traffic require explicit policy additions before they can communicate.

## Storage

Runtime validation requires exactly one default StorageClass. The expected kind local-path provisioner is sufficient for disposable development data; no additional storage software is part of Phase 1.

## Commands

| Command | Effect |
| --- | --- |
| `make cluster-create` | Create the exact cluster and apply its baseline |
| `make cluster-status` | Read cluster and system status |
| `make cluster-validate` | Validate topology, controls, storage, and port bindings |
| `make namespaces-apply` | Apply owned namespaces to the exact context |
| `make policies-apply` | Apply resource and network controls to the exact context |
| `make cluster-destroy` | Inventory, confirm, and delete the exact cluster |
| `make cluster-recreate` | Inventory, confirm, delete, and rebuild the exact cluster |

The lifecycle scripts do not accept a cluster-name argument. This prevents convenient commands from being redirected toward another environment.

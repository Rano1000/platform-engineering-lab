# ADR-0005: Use a three-node local cluster

- Status: Accepted
- Date: 2026-08-14

## Context

The local baseline must expose node roles and scheduling behavior while remaining usable on an 8 GiB-class workstation.

## Decision

Run one control-plane and two worker nodes as Docker containers in kind. Pin all nodes to Kubernetes v1.35.0 using the image digest published with kind v0.31.0.

Use a versioned kubeadm v1beta3 node-registration patch for the ingress-ready label. kind v0.31.0 generates v1beta3 configuration for Kubernetes 1.35.x; v1beta4 becomes the kind-generated format at Kubernetes 1.36 and requires list-form extra arguments.

## Consequences

The topology supports worker-oriented exercises and costs more memory than a single node. It is not highly available: all nodes share one host and the sole control plane is a single point of failure.

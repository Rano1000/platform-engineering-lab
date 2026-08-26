# ADR-0012: Use Traefik with Kubernetes Gateway API

- Status: Accepted
- Date: 2026-08-26

## Context

The local platform needs maintained HTTP routing. ingress-nginx was retired in March 2026 and no longer receives security updates, so it is unsuitable for a new implementation.

## Decision

Use Traefik Proxy `v3.7.10` through Helm chart `41.2.0` and Gateway API Standard-channel CRDs `v1.6.1`.

Pin the Proxy image to multi-platform index digest `sha256:9c3b91d5fb7770853ca5c1124a23c34bf2d9b47ffaebeab2614cbaf410dcb2ac`. The repository declares the collision-resistant `platform-traefik` GatewayClass with Traefik's documented `traefik.io/gateway-controller` controller name rather than enabling the chart's bundled default Gateway.

Primary-source evidence reviewed on 2026-08-26:

- The [Traefik chart `41.2.0` release](https://github.com/traefik/traefik-helm-chart/releases/tag/v41.2.0) declares Proxy `v3.7.10` as its default supported version.
- The [Traefik `v3.7.10` release](https://github.com/traefik/traefik/releases/tag/v3.7.10) updates its Gateway API dependency to `v1.6.1`.
- The [Traefik Gateway provider documentation](https://doc.traefik.io/traefik/reference/install-configuration/providers/kubernetes/kubernetes-gateway/) states support for Gateway API Standard `v1.6.1` and provides the official Standard-channel installation URL.
- The [Gateway API `v1.6.1` release](https://github.com/kubernetes-sigs/gateway-api/releases/tag/v1.6.1) is the selected upstream CRD release.

The repository owns the `platform-traefik` GatewayClass and `platform-system/platform-gateway`; the listener accepts routes only from `platform-apps`. Only the Kubernetes Gateway provider is enabled; Ingress, Traefik CRD, file, experimental Gateway, and dashboard exposure are disabled.

The Traefik Service uses fixed NodePorts 30080 and 30443 with `externalTrafficPolicy: Local`. kind forwards loopback host ports 80 and 443 to those ports on the control-plane container. The single Traefik endpoint is scheduled on that same node through `ingress-ready=true` and a control-plane toleration. Chart 41.2.0 supports the selection through `service.spec.externalTrafficPolicy` and the `ports.*.nodePort` values.

## Consequences

Gateway API separates platform listener ownership from application route ownership. Traefik requires a service-account token and narrowly scoped API egress because it watches Kubernetes resources. NodePort delivery avoids non-zero `hostPort`, enabled host networking, privileged Pods, and Pod Security exemptions, preserving Baseline enforcement in `platform-system`. The chart OCI digest, downloaded chart checksum, and Gateway API bundle checksum are verified before runtime installation. The kind mapping is immutable and requires one separately approved cluster recreation after repository review and commit. Version upgrades require reviewing the Traefik chart release, Proxy compatibility, Gateway API release, chart values, CRDs, rendered RBAC, and all recorded checksums before changing the pins together.

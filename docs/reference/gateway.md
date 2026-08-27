# Gateway API reference

## Pinned components

| Component | Version |
| --- | --- |
| Traefik Proxy | v3.7.10 |
| Traefik image | `sha256:9c3b91d5fb7770853ca5c1124a23c34bf2d9b47ffaebeab2614cbaf410dcb2ac` |
| Traefik Helm chart | 41.2.0 |
| Chart OCI digest | `sha256:5d1a255b73e5dd67d70fc21b1536a405d88bf6b63896bc78dbefa15e9bfb371b` |
| Chart archive SHA-256 | `f7f8b70f021f34164709bc6440165c0ccb79073dccb6369310d95a1c3cf8a2f0` |
| Gateway API Standard CRDs | v1.6.1 |
| Standard bundle SHA-256 | `24d931f22abd8e40c973264319ead7cfa09d0fb7716b7ab1ee2ff174cb063a73` |

Traefik runs as one lightweight Pod in `platform-system`, scheduled only on the ingress-ready control-plane. Its NodePort Service owns 30080 and 30443, while kind maps `127.0.0.1:80` and `127.0.0.1:443` to those control-plane ports. The rendered chart declares `hostNetwork: false` and no `hostPort`; validation rejects `hostNetwork: true` and every non-zero host port. No privileged mode or Pod Security exemption is used. No HTTPS listener is created until a trusted local certificate strategy is approved.

The Service uses `externalTrafficPolicy: Local`. This prevents the mapped control-plane NodePorts from forwarding to an endpoint on another node; the single Traefik replica is deliberately pinned to that same control-plane by `ingress-ready=true` and its control-plane toleration. Traefik chart 41.2.0 exposes `service.spec` and per-entry-point `nodePort` values for this configuration.

Only the Kubernetes Gateway provider is enabled. Provider namespace watching is limited to `platform-system` and `platform-apps`; the GatewayClass label selector limits reconciliation to the repository-owned `platform-traefik` class. The Proxy image is pinned to its multi-platform OCI index digest as well as its readable version. Release checks and anonymous usage reporting are disabled to avoid unnecessary outbound traffic.

`gateway-install` verifies the chart's OCI digest and archive checksum and verifies the versioned Gateway API bundle checksum before making any cluster change. It then installs the Standard-channel CRDs, network policy, chart, and platform Gateway. `gateway-uninstall` removes the Gateway and chart release after exact confirmation but preserves shared cluster-scoped Gateway API CRDs.

The maintained kind cluster has the required immutable mappings. A cluster created from an older configuration must be inventoried and separately approved for recreation before installation; localhost exposure remains unchanged from the user's perspective.

The Traefik service account must retain token automount because its controller needs authenticated Kubernetes API access. This is a controller-specific exception; the application service account disables token automount.

## Network-policy assumptions

The Traefik policy admits its HTTP and HTTPS entry-point ports because NodePort source addresses depend on kind, Docker, kube-proxy, and CNI packet-processing order. It allows egress to the fixed Kubernetes Service IP `10.96.0.1/32` on TCP 443, to labelled application Pods on TCP 8080, and to labelled CoreDNS Pods on TCP and UDP 53. Kubernetes permits node-to-local-Pod traffic for kubelet probes, so the management port is not opened by policy.

Runtime validation confirmed controller API and DNS access and the required application path. Docker and kind translated localhost traffic to source address `172.18.0.1` at Traefik, so `externalTrafficPolicy: Local` avoids a second Service hop but does not preserve the original localhost address end to end. Revalidate the policy after CNI or Docker-network changes.

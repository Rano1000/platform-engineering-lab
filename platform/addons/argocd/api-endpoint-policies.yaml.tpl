apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-redis-secret-init-api
  namespace: gitops
  labels:
    app.kubernetes.io/managed-by: platform-engineering-lab
  annotations:
    platform.engineering-lab/api-endpoint-identity-sha256: "${ENDPOINT_IDENTITY_SHA256}"
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-redis-secret-init
      app.kubernetes.io/component: redis-secret-init
      app.kubernetes.io/instance: argocd
  policyTypes: [Egress]
  egress:
    - to:
        - ipBlock:
            cidr: ${API_ENDPOINT_CIDR}
      ports:
        - {protocol: TCP, port: ${API_ENDPOINT_PORT}}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-application-controller-api
  namespace: gitops
  labels:
    app.kubernetes.io/managed-by: platform-engineering-lab
  annotations:
    platform.engineering-lab/api-endpoint-identity-sha256: "${ENDPOINT_IDENTITY_SHA256}"
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-application-controller
      app.kubernetes.io/component: application-controller
      app.kubernetes.io/instance: argocd
  policyTypes: [Egress]
  egress:
    - to:
        - ipBlock:
            cidr: ${API_ENDPOINT_CIDR}
      ports:
        - {protocol: TCP, port: ${API_ENDPOINT_PORT}}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-server-api
  namespace: gitops
  labels:
    app.kubernetes.io/managed-by: platform-engineering-lab
  annotations:
    platform.engineering-lab/api-endpoint-identity-sha256: "${ENDPOINT_IDENTITY_SHA256}"
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-server
      app.kubernetes.io/component: server
      app.kubernetes.io/instance: argocd
  policyTypes: [Egress]
  egress:
    - to:
        - ipBlock:
            cidr: ${API_ENDPOINT_CIDR}
      ports:
        - {protocol: TCP, port: ${API_ENDPOINT_PORT}}

# Deploy the golden-path application

This is the repeatable procedure used for the completed Phase 2 runtime gate. A fresh environment still requires separate approval for every mutating step.

## Validate repository content

```sh
make validate
make app-test
```

## Install the Gateway layer

```sh
make gateway-install
make gateway-validate
```

The install target verifies `kind-platform-engineering-lab`, installs pinned Gateway API Standard CRDs, and deploys pinned Traefik into `platform-system`.

Before installation, the cluster must have been created from the current kind configuration. Its immutable mappings forward localhost ports 80 and 443 to NodePorts 30080 and 30443. Replacing an older cluster is a separate, destructive operation and requires explicit approval.

## Build, load, and deploy

Application and chart sources must be committed before image creation. The immutable tag uses the first 12 Git revision characters; the OCI revision label records the complete 40-character revision.

```sh
make app-build
make app-load
make app-deploy
make app-validate
```

Test the public route:

```sh
curl --fail http://golden-path-api.localhost/
```

Run mutating reliability checks only after reading their explanation and confirmation prompt:

```sh
make app-network-test
make app-recovery-test
```

For the network test, enter `app-network-policy-test` after reviewing the stated scope. It keeps at most two temporary resources in `observability` at once, records ten independent outcomes, captures sanitized evidence under `.artifacts/app-network/`, and removes each exact resource through UID-aware cleanup only after diagnostics are complete. Do not rerun or clean resources manually if the command preserves evidence after a failure.

## Remove Phase 2 runtime resources

```sh
make app-uninstall
make gateway-uninstall
```

Gateway API CRDs remain installed because cluster-scoped CRDs may be shared by other routes or controllers.

# Validate the application supply chain

This procedure uses Docker but never contacts Kubernetes.

## Static contracts

```sh
make ci-check
make app-test
```

## Build one reviewable artifact

The build refuses a dirty repository so uncommitted content cannot be labelled with a committed revision.

```sh
make app-image-artifact
make app-image-inspect
```

The image archive and checksum are written below `.artifacts/supply-chain/`, which Git ignores.

## Generate evidence and enforce policy

```sh
make supply-chain-secret-scan
make app-sbom
make app-scan
```

The SBOM is CycloneDX JSON. The vulnerability JSON retains unfixed findings for review; the enforcement pass rejects unexcepted, fixable HIGH and CRITICAL findings.

## Update dependency locks

Modify the `.in` files, run `make dependency-locks-update`, and review all resolved versions and generated hashes. The target uses the pinned compiler container; do not install pip-tools globally or hand-edit hashes.

SHELL := /bin/sh

.DEFAULT_GOAL := help

.PHONY: help doctor validate lint docs-check cluster-create cluster-status cluster-validate cluster-destroy cluster-recreate namespaces-apply policies-apply app-test app-build app-load app-deploy app-status app-validate app-uninstall app-ownership-status app-network-test app-recovery-test gateway-install gateway-status gateway-validate gateway-uninstall dependency-locks-check dependency-locks-update supply-chain-policy-test supply-chain-secret-scan app-image-artifact app-image-inspect app-sbom app-scan promotion-policy-test phase4-check ci-check gitops-install gitops-bootstrap gitops-status gitops-root-status gitops-root-diff gitops-root-sync gitops-app-status gitops-app-diff gitops-app-sync gitops-validate gitops-uninstall

help: ## Show available targets.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

doctor: ## Inspect local tool and runtime readiness without making changes.
	@./scripts/doctor.sh

validate: ## Run every safe repository validation.
	@./scripts/validate.sh all

lint: ## Lint Markdown, YAML, shell, Make, and GitHub workflow files.
	@./scripts/validate.sh lint

docs-check: ## Check Markdown formatting and internal documentation links.
	@./scripts/validate.sh docs

dependency-locks-check: ## Confirm Python installs require generated package hashes.
	@./scripts/supply-chain.sh locks

dependency-locks-update: ## Regenerate Python locks with the pinned compiler (mutating).
	@./scripts/supply-chain.sh locks-update

supply-chain-policy-test: ## Test vulnerability exception validation and expiry handling.
	@./scripts/supply-chain.sh policy-test

supply-chain-secret-scan: ## Scan repository content using the pinned Trivy image.
	@./scripts/supply-chain.sh secret-scan

app-image-artifact: ## Build the image once and export its checksummed archive.
	@./scripts/supply-chain.sh build-artifact

app-image-inspect: ## Inspect the immutable application image contract.
	@./scripts/supply-chain.sh inspect

app-sbom: ## Generate and validate the CycloneDX application SBOM.
	@./scripts/supply-chain.sh sbom

app-scan: ## Report vulnerabilities and reject fixable HIGH or CRITICAL findings.
	@./scripts/supply-chain.sh scan

promotion-policy-test: ## Test image-impact, artifact-integrity, and promotion policies.
	@./scripts/detect-image-impact.py --self-test
	@./scripts/validate-promotion.py --self-test
	@./scripts/update-chart-promotion.py --self-test
	@./scripts/validate-reconciliation.py --self-test
	@./scripts/verify-promotion-artifacts.sh self-test
	@./scripts/publish-image.sh self-test

phase4-check: ## Render and validate Phase 4 repository contracts without contacting Kubernetes.
	@./scripts/validate-phase4.sh

ci-check: validate dependency-locks-check supply-chain-policy-test promotion-policy-test ## Run non-cluster CI contract checks.

cluster-create: ## Create the exact local lab cluster and apply its baseline (mutating).
	@./scripts/cluster.sh create

cluster-status: ## Display the exact local lab cluster status (read-only).
	@./scripts/cluster.sh status

cluster-validate: ## Validate the exact local lab cluster (read-only).
	@./scripts/cluster.sh validate

cluster-destroy: ## Confirm and destroy only the exact local lab cluster (destructive).
	@./scripts/cluster.sh destroy

cluster-recreate: ## Confirm, destroy, and recreate only the exact lab cluster (destructive).
	@./scripts/cluster.sh recreate

namespaces-apply: ## Apply owned namespace definitions to the exact lab context (mutating).
	@./scripts/cluster.sh namespaces-apply

policies-apply: ## Apply resource and network policies to the exact lab context (mutating).
	@./scripts/cluster.sh policies-apply

app-test: ## Run application unit tests in the pinned container build environment.
	@./scripts/app.sh test

app-build: ## Build an immutable revision-labelled application image.
	@./scripts/app.sh build

app-load: ## Load the exact application image into the lab kind cluster.
	@./scripts/app.sh load

app-deploy: ## Deploy or upgrade the application in the exact lab context.
	@./scripts/app.sh deploy

app-status: ## Display application release and workload status (read-only).
	@./scripts/app.sh status

app-validate: ## Validate the deployed application without changing it.
	@./scripts/app.sh validate

app-uninstall: ## Confirm and remove only the application Helm release.
	@./scripts/app.sh uninstall

app-ownership-status: ## Show the active application lifecycle owner without changing it.
	@./scripts/app.sh ownership-status

app-network-test: ## Create temporary Pods to test allowed and denied application traffic.
	@./scripts/app.sh network-test

app-recovery-test: ## Confirm deletion of one application Pod and validate recovery.
	@./scripts/app.sh recovery-test

gateway-install: ## Install pinned Gateway API CRDs and Traefik in the exact lab cluster.
	@./scripts/gateway.sh install

gateway-status: ## Display Traefik and Gateway API status (read-only).
	@./scripts/gateway.sh status

gateway-validate: ## Validate Traefik and the platform Gateway (read-only).
	@./scripts/gateway.sh validate

gateway-uninstall: ## Confirm and remove Traefik while preserving shared CRDs.
	@./scripts/gateway.sh uninstall

gitops-install: ## Confirm and install the exact pinned Argo CD release.
	@./scripts/gitops.sh install

gitops-bootstrap: ## Apply the restricted project and verified Application desired state.
	@./scripts/gitops.sh bootstrap

gitops-status: ## Display Argo CD and Application status without changing it.
	@./scripts/gitops.sh status

gitops-root-status: ## Show root Application status without changing it.
	@./scripts/gitops.sh root-status

gitops-root-diff: ## Show the pending child-Application definition change.
	@./scripts/gitops.sh root-diff

gitops-root-sync: ## Confirm and synchronize only the root Application.
	@./scripts/gitops.sh root-sync

gitops-app-status: ## Show child workload Application status without changing it.
	@./scripts/gitops.sh app-status

gitops-app-diff: ## Show the pending workload change without syncing.
	@./scripts/gitops.sh app-diff

gitops-app-sync: ## Confirm and synchronize only the child workload Application.
	@./scripts/gitops.sh app-sync

gitops-validate: ## Validate the installed Argo CD runtime without changing it.
	@./scripts/gitops.sh validate

gitops-uninstall: ## Confirm removal of Argo CD while preserving CRDs and workloads.
	@./scripts/gitops.sh uninstall

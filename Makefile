SHELL := /bin/sh

.DEFAULT_GOAL := help

.PHONY: help doctor validate lint docs-check cluster-create cluster-status cluster-validate cluster-destroy cluster-recreate namespaces-apply policies-apply app-test app-build app-load app-deploy app-status app-validate app-uninstall app-network-test app-recovery-test gateway-install gateway-status gateway-validate gateway-uninstall

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

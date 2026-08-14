SHELL := /bin/sh

.DEFAULT_GOAL := help

.PHONY: help doctor validate lint docs-check cluster-create cluster-status cluster-validate cluster-destroy cluster-recreate namespaces-apply policies-apply

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

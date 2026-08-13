SHELL := /bin/sh

.DEFAULT_GOAL := help

.PHONY: help doctor validate lint docs-check

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

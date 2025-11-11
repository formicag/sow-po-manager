.PHONY: help setup clean lint test plan deploy verify-tags cost-report cost-report-detailed enable-cost-tracking package-lambdas ui

# Default target
help:
	@echo "SOW/PO Document Management System - Available Commands"
	@echo ""
	@echo "Development:"
	@echo "  make setup                  - Create virtual environment and install dependencies"
	@echo "  make clean                  - Remove virtual environment and build artifacts"
	@echo "  make lint                   - Run code linting (ruff + black)"
	@echo "  make test                   - Run tests with coverage report"
	@echo ""
	@echo "AWS Deployment:"
	@echo "  make plan                   - Run Terraform plan"
	@echo "  make deploy                 - Deploy infrastructure to AWS"
	@echo "  make verify-tags            - Verify all AWS resources are properly tagged"
	@echo "  make package-lambdas        - Package all Lambda functions into ZIP files"
	@echo ""
	@echo "Cost Tracking:"
	@echo "  make enable-cost-tracking   - Enable cost allocation tags (safe to run multiple times)"
	@echo "  make cost-report            - Show monthly costs for this project"
	@echo "  make cost-report-detailed   - Show costs by Purpose tag"
	@echo ""
	@echo "Local UI:"
	@echo "  make ui                     - Run local Flask UI (with smart port selection)"

# Variables
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff
BLACK := $(VENV)/bin/black
TERRAFORM := terraform
AWS := aws

# Setup virtual environment and install dependencies
setup:
	@echo "Creating virtual environment..."
	python3 -m venv $(VENV)
	@echo "Installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "✅ Setup complete! Activate with: source $(VENV)/bin/activate"

# Clean build artifacts
clean:
	@echo "Cleaning up..."
	rm -rf $(VENV)
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.zip" -delete
	@echo "✅ Cleanup complete!"

# Lint code
lint:
	@echo "Running linters..."
	$(RUFF) check src/ tests/ ui/
	$(BLACK) --check src/ tests/ ui/
	@echo "✅ Linting passed!"

# Format code
format:
	@echo "Formatting code..."
	$(BLACK) src/ tests/ ui/
	$(RUFF) check --fix src/ tests/ ui/
	@echo "✅ Code formatted!"

# Run tests with coverage
test:
	@echo "Running tests with coverage..."
	$(PYTEST) tests/ -v --cov=src --cov-report=term-missing --cov-report=html
	@echo "✅ Tests complete! Coverage report: htmlcov/index.html"

# Package Lambda functions
package-lambdas:
	@echo "Packaging Lambda functions..."
	@mkdir -p dist
	@for lambda_dir in src/lambdas/*; do \
		lambda_name=$$(basename $$lambda_dir); \
		echo "Packaging $$lambda_name..."; \
		cd $$lambda_dir && \
		if [ -f requirements.txt ]; then \
			pip install -r requirements.txt -t . --upgrade; \
		fi && \
		zip -r ../../../dist/$$lambda_name.zip . -x "*.pyc" -x "__pycache__/*" && \
		cd ../../..; \
	done
	@echo "✅ Lambda functions packaged in dist/"

# Terraform plan
plan:
	@echo "Running Terraform plan..."
	cd terraform && $(TERRAFORM) init && $(TERRAFORM) plan
	@echo "✅ Terraform plan complete!"

# Deploy to AWS
deploy: verify-tags package-lambdas
	@echo "Deploying to AWS..."
	cd terraform && $(TERRAFORM) init && $(TERRAFORM) apply -auto-approve
	@echo "✅ Deployment complete!"

# Verify all resources are tagged
verify-tags:
	@echo "Verifying resource tags..."
	@bash scripts/verify-tags.sh
	@echo "✅ Tag verification complete!"

# Enable cost allocation tags
enable-cost-tracking:
	@echo "Enabling cost allocation tags..."
	@$(AWS) ce update-cost-allocation-tags-status \
		--cost-allocation-tags-status \
		'[{"TagKey":"Project","Status":"Active"},{"TagKey":"Owner","Status":"Active"},{"TagKey":"Environment","Status":"Active"},{"TagKey":"Purpose","Status":"Active"},{"TagKey":"CostCenter","Status":"Active"},{"TagKey":"Application","Status":"Active"}]' \
		2>/dev/null || echo "Note: Cost allocation tags may already be enabled or require AWS Billing access"
	@echo "✅ Cost tracking enabled!"

# Show monthly costs
cost-report:
	@echo "Fetching monthly costs for sow-po-manager..."
	@$(AWS) ce get-cost-and-usage \
		--time-period Start=$$(date -v-1m +%Y-%m-01),End=$$(date +%Y-%m-01) \
		--granularity MONTHLY \
		--metrics "UnblendedCost" \
		--filter file://cost-filter.json \
		--query 'ResultsByTime[*].[TimePeriod.Start,Total.UnblendedCost.Amount,Total.UnblendedCost.Unit]' \
		--output table

# Show detailed costs by Purpose tag
cost-report-detailed:
	@echo "Fetching detailed costs by Purpose tag..."
	@$(AWS) ce get-cost-and-usage \
		--time-period Start=$$(date -v-1m +%Y-%m-01),End=$$(date +%Y-%m-01) \
		--granularity MONTHLY \
		--metrics "UnblendedCost" \
		--filter file://cost-filter.json \
		--group-by Type=TAG,Key=Purpose \
		--query 'ResultsByTime[*].Groups[*].[Keys[0],Metrics.UnblendedCost.Amount]' \
		--output table

# Run local Flask UI
ui: setup
	@echo "Starting local Flask UI..."
	@$(PYTHON) ui/app.py

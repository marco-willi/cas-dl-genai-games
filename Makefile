#################################################################################
# GLOBALS                                                                       #
#################################################################################

ifneq (,$(wildcard ./.env))
    include .env
    export
endif

#################################################################################
# COMMANDS                                                                      #
#################################################################################

.PHONY: help
help: ## Show all available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install dependencies with dev extras
	poetry install --with dev

.PHONY: run
run: ## Start the Streamlit app
	poetry run streamlit run app.py

.PHONY: test
test: ## Run tests
	poetry run pytest tests/

.PHONY: lint
lint: ## Lint source and tests with ruff
	poetry run ruff check src tests

.PHONY: format
format: ## Format source and tests with ruff
	poetry run ruff format src tests

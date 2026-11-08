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
	uv sync

.PHONY: run
run: ## Start the Streamlit app
	uv run streamlit run app.py

.PHONY: test
test: ## Run tests
	uv run pytest tests/

.PHONY: lint
lint: ## Lint source and tests with ruff
	uv run ruff check src tests

.PHONY: format
format: ## Format source and tests with ruff
	uv run ruff format src tests

THEME ?= classroom

.PHONY: theme
theme: ## Switch UI theme: make theme THEME=classroom|studio|lab
	@test -f .streamlit/themes/$(THEME).toml || { echo "Unknown THEME '$(THEME)'. See .streamlit/themes/"; exit 1; }
	sed -i 's|^base = ".streamlit/themes/.*"|base = ".streamlit/themes/$(THEME).toml"|' .streamlit/config.toml
	@echo "Theme set to $(THEME). Refresh the browser (no restart needed)."

.PHONY: vote-images
vote-images: ## Re-encode + shuffle vote images from their manifest (originals untouched)
	uv run python scripts/prepare_vote_images.py \
		--manifest assets/vote_images/spot_the_fake/manifest.json --task-id spot_the_fake

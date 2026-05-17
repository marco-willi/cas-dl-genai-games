# Makefile Skill

When creating or modifying Makefiles, follow these conventions.

## Structure

Makefiles should follow this structure:

```makefile
#################################################################################
# GLOBALS                                                                       #
#################################################################################

# Load .env file
ifneq (,$(wildcard ./.env))
    include .env
    export
endif

# Common variables
CURRENT_UID := $(shell id -u)
CURRENT_GID := $(shell id -g)

# Project-specific variables
DATA_DIR := data
...

#################################################################################
# COMMANDS                                                                      #
#################################################################################

.PHONY: help
help: ## Show all available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

##### SECTION NAME

.PHONY: target-name
target-name: ## Description of what this target does
	command here

##### ANOTHER SECTION

.PHONY: another-target
another-target: dependency ## Description with dependency
	another command
```

## Rules

### PHONY Declaration
Place `.PHONY: target` **directly above each target**, not in a combined list at the top:

```makefile
# GOOD
.PHONY: build
build: ## Build the project
	...

.PHONY: test
test: ## Run tests
	...

# BAD - do not list all at top
.PHONY: build test clean install
```

### Self-Documenting Commands
Every command must have a `## Description` comment for the help system:

```makefile
.PHONY: train
train: ## Train the model with default config
	python scripts/train.py
```

### Help Target
Use this help target that displays all commands with descriptions:

```makefile
.PHONY: help
help: ## Show all available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
```

This produces colorized output:
```
help                 Show all available commands
build                Build the project
test                 Run tests
```

### Sections
Group related targets with section headers using `#####`:

```makefile
##### DATA

.PHONY: download
download: ## Download raw data
	...

.PHONY: prepare
prepare: ## Prepare data for training
	...

##### TRAINING

.PHONY: train
train: ## Train model
	...
```

### Environment Variables
Load from `.env` file and reference with `${VAR}` or `$(VAR)`:

```makefile
ifneq (,$(wildcard ./.env))
    include .env
    export
endif

GCS_BUCKET := ${GCS_BUCKET}
```

### Variable Assignment
Use `:=` for immediate evaluation (recommended) or `=` for deferred evaluation:

```makefile
# Immediate - evaluated once when Makefile is parsed
BUILD_TIME := $(shell date +%Y%m%d)

# Deferred - evaluated each time variable is used
CURRENT_BRANCH = $(shell git branch --show-current)
```

### Shell Commands in Recipes
- Prefix with `@` to suppress command echo
- Use `$$` to escape shell variables (Make interprets single `$`)
- Use line continuation `\` for multi-line commands
- Each line runs in a separate shell unless continued

```makefile
.PHONY: example
example: ## Example with shell variables
	@if [ -z "$(VAR)" ]; then \
		echo "VAR is not set"; \
		exit 1; \
	fi
	@RESULT=$$(echo "hello"); \
	echo "Result: $$RESULT"
```

### Dependencies
Specify dependencies after the target name:

```makefile
.PHONY: data
data: download extract prepare ## Full data pipeline
	@echo "Data pipeline complete"

.PHONY: prepare
prepare: extract ## Prepare requires extract first
	python scripts/prepare.py
```

### Parameterized Targets
Accept parameters via environment or Make variables:

```makefile
.PHONY: evaluate
evaluate: ## Evaluate model (usage: make evaluate RUN_ID=xxx)
	@if [ -z "$(RUN_ID)" ]; then \
		echo "ERROR: RUN_ID not specified"; \
		echo "Usage: make evaluate RUN_ID=<run_id>"; \
		exit 1; \
	fi
	python scripts/evaluate.py $(RUN_ID)
```

### Script Execution
For complex logic, delegate to shell scripts:

```makefile
.PHONY: setup
setup: ## Setup development environment
	@./scripts/setup.sh
```

### Passing Arguments to Scripts
Use `$(ARGS)` pattern for flexible argument passing:

```makefile
.PHONY: train
train: ## Train model (pass args via ARGS="...")
	python scripts/train.py $(ARGS)
```

Usage: `make train ARGS="experiment=smoke_test epochs=5"`

## Common Patterns

### Conditional IP/Instance Discovery
```makefile
.PHONY: ssh
ssh: ## SSH into remote instance
	@if [ -z "$(INSTANCE_IP)" ]; then \
		if [ -f /tmp/instance_ip ]; then \
			ssh user@$$(cat /tmp/instance_ip); \
		else \
			echo "ERROR: INSTANCE_IP not set"; \
			exit 1; \
		fi \
	else \
		ssh user@$(INSTANCE_IP); \
	fi
```

### File Upload with Fallback
```makefile
.PHONY: sync-env
sync-env: ## Upload .env to remote
	@if [ -z "$(INSTANCE_IP)" ] && [ -f /tmp/instance_ip ]; then \
		scp .env user@$$(cat /tmp/instance_ip):~/.env; \
	elif [ -n "$(INSTANCE_IP)" ]; then \
		scp .env user@$(INSTANCE_IP):~/.env; \
	else \
		echo "ERROR: No instance IP found"; \
		exit 1; \
	fi
```

### Idempotent Directory Creation
```makefile
.PHONY: prepare
prepare: ## Prepare directories and data
	mkdir -p data/raw data/processed logs
	@if [ ! -f "data/processed/manifest.json" ]; then \
		python scripts/prepare.py; \
	else \
		echo "Already prepared, skipping."; \
	fi
```

## Reference
See `examples/sat-change/Makefile` for a complete working example.
```

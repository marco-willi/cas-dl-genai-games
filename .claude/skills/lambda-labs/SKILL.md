# Lambda Labs Training Setup Skill

When setting up Lambda Labs GPU instances for training, follow this pattern based on `/workspace/examples/sat-change/`.

## Prerequisites

### Environment Variables (.env)
Required environment variables:
```bash
# Lambda Labs API (required)
LAMBDA_API_KEY=your-lambda-api-key

# Instance Configuration
LAMBDA_INSTANCE_TYPE=gpu_1x_a10  # Default instance type
LAMBDA_REGION=us-west-1          # Preferred region
LAMBDA_SSH_KEY_NAME=your-key     # SSH key registered on Lambda Labs

# GitHub (for private repos)
GITHUB_USER=your-username
GITHUB_ACCESS_TOKEN=ghp_...

# GCS for data sync (optional but recommended)
GCS_BUCKET=your-bucket-name
GCP_PROJECT_ID=your-project-id
```

### SSH Key Setup
1. Register your SSH public key at https://cloud.lambdalabs.com/ssh-keys
2. Set `LAMBDA_SSH_KEY_NAME` in `.env` to match the registered key name

## Directory Structure

Create `scripts/lambda/` directory with the following scripts:

```
scripts/lambda/
├── list_instances.sh      # List running instances and available types
├── setup_instance.sh      # Launch new instance via API
├── setup_remote.sh        # Configure environment on instance
├── setup_gcp.sh           # GCP authentication for data sync
├── get_instance_ip.sh     # Auto-discover instance IP
├── terminate_instance.sh  # Terminate instance via API
├── train_and_shutdown.sh  # Train with auto-sync and termination
└── train_multi.sh         # Sequential multi-experiment training
```

## Makefile Targets

Add these targets to your Makefile:

```makefile
##### LAMBDA LABS

# Lambda Labs Configuration (from .env)
LAMBDA_API_KEY := ${LAMBDA_API_KEY}
LAMBDA_INSTANCE_TYPE := ${LAMBDA_INSTANCE_TYPE}
LAMBDA_REGION := ${LAMBDA_REGION}
LAMBDA_SSH_KEY_NAME := ${LAMBDA_SSH_KEY_NAME}
LAMBDA_INSTANCE_IP := ${LAMBDA_INSTANCE_IP}

lambda-list: ## List Lambda Labs instances and available types
	@./scripts/lambda/list_instances.sh

lambda-setup: ## Launch a new Lambda Labs instance
	@./scripts/lambda/setup_instance.sh

lambda-ssh: ## SSH into Lambda Labs instance
	@if [ -z "$(LAMBDA_INSTANCE_IP)" ]; then \
		if [ -f /tmp/lambda_instance_ip ]; then \
			ssh ubuntu@$$(cat /tmp/lambda_instance_ip); \
		else \
			echo "ERROR: LAMBDA_INSTANCE_IP not set. Run 'make lambda-list' to find IP."; \
			exit 1; \
		fi \
	else \
		ssh ubuntu@$(LAMBDA_INSTANCE_IP); \
	fi

lambda-sync-env: ## Upload .env file to Lambda instance
	@if [ -z "$(LAMBDA_INSTANCE_IP)" ] && [ -f /tmp/lambda_instance_ip ]; then \
		scp .env ubuntu@$$(cat /tmp/lambda_instance_ip):~/.env; \
	elif [ -n "$(LAMBDA_INSTANCE_IP)" ]; then \
		scp .env ubuntu@$(LAMBDA_INSTANCE_IP):~/.env; \
	else \
		echo "ERROR: LAMBDA_INSTANCE_IP not set"; \
		exit 1; \
	fi
	@echo ".env uploaded"

lambda-setup-remote: ## Setup environment on Lambda instance
	@echo "Uploading .env and setup script..."
	@IP=$${LAMBDA_INSTANCE_IP:-$$(cat /tmp/lambda_instance_ip 2>/dev/null)}; \
	if [ -z "$$IP" ]; then echo "ERROR: No instance IP found"; exit 1; fi; \
	scp .env ubuntu@$$IP:~/.env; \
	scp scripts/lambda/setup_remote.sh ubuntu@$$IP:~/setup_remote.sh; \
	echo "Running remote setup..."; \
	ssh ubuntu@$$IP "GITHUB_USER=$(GITHUB_USER) GITHUB_ACCESS_TOKEN=$(GITHUB_ACCESS_TOKEN) GCS_BUCKET=$(GCS_BUCKET) bash ~/setup_remote.sh"

lambda-setup-gcp: ## Authenticate with GCP (run on Lambda instance)
	@GCP_PROJECT_ID=$(GCP_PROJECT_ID) GCS_BUCKET=$(GCS_BUCKET) ./scripts/lambda/setup_gcp.sh

lambda-sync-data: ## Download data from GCS (run on remote)
	@echo "Downloading data from gs://$(GCS_BUCKET)/data/..."
	mkdir -p data/extracted data/processed
	gsutil -m rsync -r gs://$(GCS_BUCKET)/data/extracted/ data/extracted/ || true
	gsutil -m rsync -r gs://$(GCS_BUCKET)/data/processed/ data/processed/ || true

lambda-train-auto: ## Train with auto-sync to GCS and terminate on success
	@./scripts/lambda/train_and_shutdown.sh $(ARGS)

lambda-train-multi: ## Train multiple experiments, then terminate
	@./scripts/lambda/train_multi.sh $(ARGS)

lambda-terminate: ## Terminate Lambda Labs instance
	@./scripts/lambda/terminate_instance.sh
```

## Lambda Labs API Patterns

### API Base URL
```bash
API_BASE="https://cloud.lambdalabs.com/api/v1"
```

### Authentication
All API calls require Bearer token:
```bash
curl -s -H "Authorization: Bearer $LAMBDA_API_KEY" "$API_BASE/..."
```

### Common Endpoints
- `GET /instances` — List running instances
- `GET /instance-types` — List available instance types with capacity
- `GET /ssh-keys` — List registered SSH keys
- `POST /instance-operations/launch` — Launch new instance
- `POST /instance-operations/terminate` — Terminate instance

## Remote Setup Best Practices

### Virtual Environment
Lambda Labs instances come with pre-installed Lambda Stack (PyTorch, CUDA, NumPy). Use `--system-site-packages` to inherit these:

```bash
python3 -m venv --system-site-packages ~/.venvs/myproject
source ~/.venvs/myproject/bin/activate
pip install -e ".[dev]"
```

### GPU Verification
```bash
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
```

### Add venv activation to bashrc
```bash
if ! grep -q "myproject" ~/.bashrc; then
    echo "source ~/.venvs/myproject/bin/activate" >> ~/.bashrc
fi
```

## Training with Auto-Termination

### Key Features
1. **Auto-sync logs to GCS** after training completes
2. **Auto-terminate on success** to save costs
3. **Keep instance on failure** for debugging
4. **Run in tmux** to survive SSH disconnections

### Usage
```bash
# On local machine
make lambda-setup               # Launch instance
make lambda-setup-remote        # Configure environment

# SSH into instance
make lambda-ssh

# On remote (inside tmux!)
tmux new -s train
make lambda-train-auto ARGS="experiment=my_experiment"
# Ctrl+B, D to detach
```

### Self-Termination Pattern
Get instance ID by matching public IP against Lambda API:
```bash
MY_IP=$(curl -s ifconfig.me)
INSTANCE_ID=$(curl -s -H "Authorization: Bearer $LAMBDA_API_KEY" \
    "$API_BASE/instances" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for inst in data.get('data', []):
    if inst.get('ip') == '$MY_IP':
        print(inst['id'])
        break
")
```

## Workflow Summary

### Local → Lambda Training Workflow

1. **Prepare data locally**, upload to GCS:
   ```bash
   make data                    # Process data
   make gcp-sync-up             # Upload to GCS
   ```

2. **Launch instance**:
   ```bash
   make lambda-list            # Check availability
   make lambda-setup           # Launch instance
   ```

3. **Configure instance**:
   ```bash
   make lambda-setup-remote    # Clone repo, install deps, upload .env
   make lambda-ssh             # SSH in
   make lambda-setup-gcp       # Authenticate GCP (on instance)
   make lambda-sync-data       # Download data from GCS (on instance)
   ```

4. **Train** (inside tmux on instance):
   ```bash
   tmux new -s train
   make lambda-train-auto ARGS="experiment=my_exp"  # Auto-terminates on success
   ```

5. **Download results** (after training):
   ```bash
   make gcp-sync-down          # Download logs from GCS
   ```

## Reference Implementation
See `examples/sat-change/scripts/lambda/` for complete working examples of all scripts.
```

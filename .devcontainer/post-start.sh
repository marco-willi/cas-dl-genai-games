#!/bin/bash
# Post-start command: Runs every time the container starts

set -e

echo "Running post-start tasks..."

# Ensure user-local tools (claude, cli-tools) are on PATH
export PATH="$HOME/.local/bin:$PATH"

# Install CLI tools
bash "$(dirname "$0")/cli-tools.sh"

echo ""
echo "uv: $(uv --version)"
echo "Python: $(which python) ($(python --version))"

echo ""
echo "Container ready!"

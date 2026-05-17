#!/bin/bash
# Post-create command: Runs once after container is created

set -e

echo "Running post-create setup..."

# Install Claude Code CLI
curl -fsSL https://claude.ai/install.sh | bash


# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -
export PATH="$HOME/.local/bin:$PATH"

# Ensure we're in the workspace
cd /workspace

# Place venv on native Linux filesystem for performance (avoids slow 9p scan by Quarto)
poetry config virtualenvs.in-project false
poetry config virtualenvs.path "$HOME/.venvs"

poetry install --with dev

# Resolve the actual venv path Poetry created and symlink it to /workspace/.venv
VENV_REAL=$(poetry env info --path)
# rm -rf /workspace/.venv
# ln -s "$VENV_REAL" /workspace/.venv

# Auto-activate the venv in every new terminal session
VENV_ACTIVATE=$VENV_REAL/bin/activate

for RC in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -f "$RC" ]; then
        if ! grep -q "source $VENV_ACTIVATE" "$RC"; then
            {
                echo ""
                echo "# Auto-activate Poetry venv"
                echo "[ -f $VENV_ACTIVATE ] && source $VENV_ACTIVATE"
            } >> "$RC"
        fi
    fi
done

# Install pre-commit hooks if .pre-commit-config.yaml exists
if [ -f ".pre-commit-config.yaml" ]; then
    echo ""
    echo "Installing pre-commit hooks..."
    poetry run pre-commit install || echo "Warning: Failed to install pre-commit hooks (continuing anyway)"
fi



echo ""
echo "Post-create setup complete!"
echo "Venv : /workspace/.venv -> $VENV_REAL (native fs)"
echo "Python: $($VENV_REAL --version)"

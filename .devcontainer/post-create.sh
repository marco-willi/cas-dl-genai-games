#!/bin/bash
# Post-create command: Runs once after container is created

set -e

echo "Running post-create setup..."

# Install dotfiles (agent skills etc.). Runs early so a later failure under `set -e` can't skip it,
# and doesn't rely on VS Code's dotfiles.repository setting (ignored by the devcontainer CLI and
# "Attach to Running Container"). Skipped if ~/dotfiles already exists (e.g. VS Code cloned it).
# Non-fatal: a clone failure (private repo, no network) must not abort container setup.
DOTFILES_REPO="${DOTFILES_REPO:-https://github.com/marco-willi/dotfiles.git}"
if [ ! -d "$HOME/dotfiles" ]; then
    git clone --depth 1 "$DOTFILES_REPO" "$HOME/dotfiles" \
        || echo "Warning: could not clone $DOTFILES_REPO (continuing anyway)"
fi
if [ -x "$HOME/dotfiles/install.sh" ]; then
    "$HOME/dotfiles/install.sh" || echo "Warning: dotfiles install.sh failed (continuing anyway)"
fi

# Install Claude Code CLI
curl -fsSL https://claude.ai/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"

# Ensure we're in the workspace
cd /workspace

# Remove a leftover .venv symlink from the old Poetry setup (pointed to ~/.venvs/...),
# so uv can create a real in-project venv.
if [ -L .venv ]; then
    rm .venv
fi

# Creates .venv/ in-project and installs the default dependency groups (see
# [tool.uv] default-groups in pyproject.toml). Also writes uv.lock on first run.
uv sync

# Auto-activate the in-project venv in every new terminal session
VENV_ACTIVATE="/workspace/.venv/bin/activate"

for RC in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -f "$RC" ]; then
        if ! grep -q "source $VENV_ACTIVATE" "$RC"; then
            {
                echo ""
                echo "# Auto-activate uv venv"
                echo "[ -f $VENV_ACTIVATE ] && source $VENV_ACTIVATE"
            } >> "$RC"
        fi
    fi
done

# Install pre-commit hooks if .pre-commit-config.yaml exists
if [ -f ".pre-commit-config.yaml" ]; then
    echo ""
    echo "Installing pre-commit hooks..."
    uv run pre-commit install || echo "Warning: Failed to install pre-commit hooks (continuing anyway)"
fi

echo ""
echo "Post-create setup complete!"
echo "Venv : /workspace/.venv"
echo "Python: $(/workspace/.venv/bin/python --version)"

#!/usr/bin/env bash
# Install developer tools from GitHub releases (best-effort — failures are non-fatal)
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"

# Helper: check if tool exists and works (not just any binary with same name)
tool_exists() {
    local name="$1"
    # Check LOCAL_BIN first, then PATH
    if [[ -x "$LOCAL_BIN/$name" ]]; then
        return 0
    elif [[ -x "/usr/local/bin/$name" ]]; then
        return 0
    fi
    return 1
}

# yq — YAML processor (single binary)
if ! tool_exists yq; then
    echo "Installing yq..."
    curl -fsSL "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64" \
        -o "$LOCAL_BIN/yq" && chmod +x "$LOCAL_BIN/yq" \
        || echo "Warning: failed to install yq"
else
    echo "yq: already installed"
fi

# git-delta — better git diffs
if ! tool_exists delta; then
    echo "Installing delta..."
    ASSET=$(curl -fsSL https://api.github.com/repos/dandavison/delta/releases/latest \
        | grep browser_download_url | grep x86_64-unknown-linux-musl.tar.gz | cut -d'"' -f4 | head -1)
    curl -fsSL "$ASSET" | tar xz -C /tmp \
        && mv /tmp/delta-*-x86_64-unknown-linux-musl/delta "$LOCAL_BIN/delta" \
        && rm -rf /tmp/delta-* \
        || echo "Warning: failed to install delta"
else
    echo "delta: already installed"
fi

# hyperfine — benchmarking
if ! tool_exists hyperfine; then
    echo "Installing hyperfine..."
    ASSET=$(curl -fsSL https://api.github.com/repos/sharkdp/hyperfine/releases/latest \
        | grep browser_download_url | grep x86_64-unknown-linux-musl.tar.gz | cut -d'"' -f4 | head -1)
    curl -fsSL "$ASSET" | tar xz -C /tmp \
        && mv /tmp/hyperfine-*-x86_64-unknown-linux-musl/hyperfine "$LOCAL_BIN/hyperfine" \
        && rm -rf /tmp/hyperfine-* \
        || echo "Warning: failed to install hyperfine"
else
    echo "hyperfine: already installed"
fi

# watchexec — file watcher
if ! tool_exists watchexec; then
    echo "Installing watchexec..."
    ASSET=$(curl -fsSL https://api.github.com/repos/watchexec/watchexec/releases/latest \
        | grep browser_download_url | grep x86_64-unknown-linux-musl | grep '\.tar\.xz' | cut -d'"' -f4 | head -1)
    curl -fsSL "$ASSET" | tar xJ -C /tmp \
        && mv /tmp/watchexec-*-x86_64-unknown-linux-musl/watchexec "$LOCAL_BIN/watchexec" \
        && rm -rf /tmp/watchexec-* \
        || echo "Warning: failed to install watchexec"
else
    echo "watchexec: already installed"
fi

# ast-grep (sg) — structural code search (NOTE: /usr/bin/sg is a different Unix tool)
if ! tool_exists sg; then
    echo "Installing ast-grep (sg)..."
    ASSET=$(curl -fsSL https://api.github.com/repos/ast-grep/ast-grep/releases/latest \
        | grep browser_download_url | grep x86_64-unknown-linux-gnu.zip | cut -d'"' -f4 | head -1)
    if [[ -n "$ASSET" ]]; then
        curl -fsSL "$ASSET" -o /tmp/sg.zip \
            && unzip -o /tmp/sg.zip -d "$LOCAL_BIN" \
            && chmod +x "$LOCAL_BIN/sg" "$LOCAL_BIN/ast-grep" 2>/dev/null \
            && rm -f /tmp/sg.zip \
            || echo "Warning: failed to install sg"
    else
        echo "Warning: failed to find ast-grep release asset"
    fi
else
    echo "sg (ast-grep): already installed"
fi

# difftastic (difft) — structural diffing
if ! tool_exists difft; then
    echo "Installing difft..."
    ASSET=$(curl -fsSL https://api.github.com/repos/Wilfred/difftastic/releases/latest \
        | grep browser_download_url | grep x86_64-unknown-linux-gnu.tar.gz | cut -d'"' -f4 | head -1)
    curl -fsSL "$ASSET" | tar xz -C "$LOCAL_BIN" difft \
        || echo "Warning: failed to install difft"
else
    echo "difft: already installed"
fi

# sd — modern sed replacement
if ! tool_exists sd; then
    echo "Installing sd..."
    SD_VERSION="1.0.0"
    curl -fsSL "https://github.com/chmln/sd/releases/download/v${SD_VERSION}/sd-v${SD_VERSION}-x86_64-unknown-linux-gnu.tar.gz" \
        | tar xz -C /tmp \
        && mv /tmp/sd-v${SD_VERSION}-x86_64-unknown-linux-gnu/sd "$LOCAL_BIN/sd" \
        && rm -rf /tmp/sd-* \
        || echo "Warning: failed to install sd"
else
    echo "sd: already installed"
fi

# scc — fast code counter
if ! tool_exists scc; then
    echo "Installing scc..."
    ASSET=$(curl -fsSL https://api.github.com/repos/boyter/scc/releases/latest \
        | grep browser_download_url | grep Linux_x86_64.tar.gz | cut -d'"' -f4 | head -1)
    curl -fsSL "$ASSET" | tar xz -C "$LOCAL_BIN" scc \
        || echo "Warning: failed to install scc"
else
    echo "scc: already installed"
fi

# jq — JSON processor (critical for .ipynb notebook inspection)
if ! tool_exists jq; then
    echo "Installing jq..."
    curl -fsSL "https://github.com/jqlang/jq/releases/latest/download/jq-linux-amd64" \
        -o "$LOCAL_BIN/jq" && chmod +x "$LOCAL_BIN/jq" \
        || echo "Warning: failed to install jq"
else
    echo "jq: already installed"
fi

# bat — syntax-highlighted file viewer with line ranges
if ! tool_exists bat; then
    echo "Installing bat..."
    ASSET=$(curl -fsSL https://api.github.com/repos/sharkdp/bat/releases/latest \
        | grep browser_download_url | grep x86_64-unknown-linux-musl.tar.gz | cut -d'"' -f4 | head -1)
    curl -fsSL "$ASSET" | tar xz -C /tmp \
        && mv /tmp/bat-*-x86_64-unknown-linux-musl/bat "$LOCAL_BIN/bat" \
        && rm -rf /tmp/bat-* \
        || echo "Warning: failed to install bat"
else
    echo "bat: already installed"
fi

# fd — fast file finder with sane defaults
if ! tool_exists fd; then
    echo "Installing fd..."
    ASSET=$(curl -fsSL https://api.github.com/repos/sharkdp/fd/releases/latest \
        | grep browser_download_url | grep x86_64-unknown-linux-musl.tar.gz | cut -d'"' -f4 | head -1)
    curl -fsSL "$ASSET" | tar xz -C /tmp \
        && mv /tmp/fd-*-x86_64-unknown-linux-musl/fd "$LOCAL_BIN/fd" \
        && rm -rf /tmp/fd-* \
        || echo "Warning: failed to install fd"
else
    echo "fd: already installed"
fi

# fzf — fuzzy finder for interactive selection
if ! tool_exists fzf; then
    echo "Installing fzf..."
    ASSET=$(curl -fsSL https://api.github.com/repos/junegunn/fzf/releases/latest \
        | grep browser_download_url | grep linux_amd64.tar.gz | cut -d'"' -f4 | head -1)
    curl -fsSL "$ASSET" | tar xz -C "$LOCAL_BIN" fzf \
        || echo "Warning: failed to install fzf"
else
    echo "fzf: already installed"
fi

# duf — disk usage overview
if ! tool_exists duf; then
    echo "Installing duf..."
    ASSET=$(curl -fsSL https://api.github.com/repos/muesli/duf/releases/latest \
        | grep browser_download_url | grep linux_x86_64.tar.gz | cut -d'"' -f4 | head -1)
    curl -fsSL "$ASSET" | tar xz -C "$LOCAL_BIN" duf \
        || echo "Warning: failed to install duf"
else
    echo "duf: already installed"
fi

# dust — visual disk usage (sorted, intuitive)
if ! tool_exists dust; then
    echo "Installing dust..."
    ASSET=$(curl -fsSL https://api.github.com/repos/bootandy/dust/releases/latest \
        | grep browser_download_url | grep x86_64-unknown-linux-musl.tar.gz | cut -d'"' -f4 | head -1)
    curl -fsSL "$ASSET" | tar xz -C /tmp \
        && mv /tmp/dust-*-x86_64-unknown-linux-musl/dust "$LOCAL_BIN/dust" \
        && rm -rf /tmp/dust-* \
        || echo "Warning: failed to install dust"
else
    echo "dust: already installed"
fi

# qsv — fast CSV processor (for metadata.csv inspection)
if ! tool_exists qsv; then
    echo "Installing qsv..."
    ASSET=$(curl -fsSL https://api.github.com/repos/jqnatividad/qsv/releases/latest \
        | grep browser_download_url | grep x86_64-unknown-linux-musl.zip | cut -d'"' -f4 | head -1)
    if [[ -n "$ASSET" ]]; then
        curl -fsSL "$ASSET" -o /tmp/qsv.zip \
            && unzip -o /tmp/qsv.zip qsv -d "$LOCAL_BIN" \
            && chmod +x "$LOCAL_BIN/qsv" \
            && rm -f /tmp/qsv.zip \
            || echo "Warning: failed to install qsv"
    else
        echo "Warning: failed to find qsv release asset"
    fi
else
    echo "qsv: already installed"
fi

# rtk — AI code generation tool
if ! tool_exists rtk; then
    echo "Installing rtk..."
    curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh \
        && rtk init -g \
        || echo "Warning: failed to install rtk"
else
    echo "rtk: already installed"
fi

# Improve diff readability in code reviews when optional tools are present.
if tool_exists delta; then
    git config --global core.pager "delta"
    git config --global interactive.diffFilter "delta --color-only"
    git config --global delta.navigate true
    git config --global delta.light false
    git config --global merge.conflictstyle zdiff3
fi

if tool_exists difft; then
    git config --global alias.difft "difft"
fi

# Claude plugins
if command -v claude >/dev/null 2>&1; then
    claude plugin marketplace add JuliusBrussee/caveman || echo "Warning: failed to add caveman marketplace"
    claude plugin install caveman@caveman || echo "Warning: failed to install caveman plugin"
else
    echo "Warning: claude CLI not found, skipping plugin install"
fi

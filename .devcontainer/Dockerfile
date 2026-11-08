# Dev container image for genai-cv-game
#
# Base: Debian bookworm + Python 3.14 (devcontainers image => non-root `vscode`
# user, zsh, git and common build tooling already present).
ARG VARIANT="3-3.14-bookworm"
FROM mcr.microsoft.com/devcontainers/python:${VARIANT}

# uv (fast Python package/project manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# UV_LINK_MODE=copy: the workspace is a bind mount on a different filesystem than the
# uv cache, so hardlinking is not possible (avoids a warning on every `uv sync`).
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    SHELL=/usr/bin/zsh

# System dependencies.
#   - libgl1 / libglib2.0-0: image libraries
#   - make: Makefile targets
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    libgl1 \
    libglib2.0-0 \
    make \
    pkg-config \
    rsync \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# 8501 Streamlit
EXPOSE 8501

CMD ["/usr/bin/zsh"]

# ===========================================================================
# Remora Sandbox — lightweight Python dev environment for code validation
# ===========================================================================
# This image provides Python 3.13 + common dev tools (pytest, mypy, ruff)
# pre-installed so it can run with --network none (fully air-gapped).
#
# Usage:
#   docker run --rm remora-sandbox:latest python -c "print('hello')"
#   docker run --rm -v /path/to/code:/workspace remora-sandbox:latest pytest -q
#   docker run --rm --network none remora-sandbox:latest ruff check .
# ===========================================================================

FROM python:3.13-slim AS base

# Install minimal system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        coreutils \
        findutils \
        git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user 'sandbox' and workspace directory
RUN useradd -m -s /bin/bash sandbox && \
    mkdir -p /workspace && \
    chown sandbox:sandbox /workspace

USER sandbox
WORKDIR /home/sandbox

# Install Python dev tools into user site-packages.
# These are the tools needed for validation checks (syntax, types, lint, tests).
# Pinned to avoid surprise breakage; update versions as needed.
RUN pip install --user --no-cache-dir \
        pytest>=8.0 \
        mypy>=1.10 \
        ruff>=0.5

# Verify tools are installed and on PATH
ENV PATH="/home/sandbox/.local/bin:$PATH"
RUN python --version && pytest --version && mypy --version && ruff --version

# Copy entrypoint
COPY --chown=sandbox:sandbox entrypoint.sh /home/sandbox/entrypoint.sh
USER root
RUN chmod +x /home/sandbox/entrypoint.sh
USER sandbox

WORKDIR /workspace

ENTRYPOINT ["/home/sandbox/entrypoint.sh"]
CMD ["bash"]

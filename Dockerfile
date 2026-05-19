# syntax=docker/dockerfile:1.7
#
# AMR Learning Agent — Hugging Face Spaces (Docker SDK) image.
#
# HF Spaces requirements addressed here:
#   - Listens on port 7860 (HF default)
#   - Runs as a non-root UID 1000 user
#   - HOME points at a writable directory so caches / Streamlit state work
#
# Build locally with:
#   docker build -t amr-ai .
#   docker run --rm -p 7860:7860 \
#       -e OPENAI_API_KEY=... \
#       -e LOGFIRE_API_KEY=... \
#       amr-ai
#
FROM python:3.13-slim AS base

# Streamlit / Python runtime tweaks
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

# Minimal system packages. We dropped scrapy/lxml/docling from the runtime
# image, so we no longer need build-essential, libxml2-dev, etc. — only the
# bits chromadb's onnxruntime and httpx actually need.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# uv (single static binary, copied from the official image)
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

# ---------------------------------------------------------------------------
# Non-root user (HF Spaces convention: uid 1000, $HOME writable)
# ---------------------------------------------------------------------------
RUN useradd --create-home --uid 1000 --shell /bin/bash user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    XDG_CACHE_HOME=/home/user/.cache

WORKDIR /app

# ---------------------------------------------------------------------------
# Dependency install (cached layer — only re-runs when pyproject/lock change)
# ---------------------------------------------------------------------------
COPY --chown=user:user pyproject.toml uv.lock ./

# Install ONLY the runtime deps:
#   --frozen                : use the locked versions
#   --no-dev                : skip pytest/ruff
#   --no-install-project    : we don't need an editable install of "amr-ai"
#   (pipeline + notebook groups are off by default in uv)
RUN uv sync --frozen --no-dev --no-install-project \
    && chown -R user:user /app

# ---------------------------------------------------------------------------
# App source + prebuilt ChromaDB collection
# ---------------------------------------------------------------------------
COPY --chown=user:user src/ ./src/
COPY --chown=user:user app.py ./app.py
COPY --chown=user:user data/chroma_db/ ./data/chroma_db/

# Make the virtualenv the default Python and expose src/ for imports
ENV VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app

# Streamlit config — quiet, headless, on the HF port
ENV STREAMLIT_SERVER_PORT=7860 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=true

USER user

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl --fail http://localhost:7860/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py"]

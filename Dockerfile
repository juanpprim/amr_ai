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
# ---------------------------------------------------------------------------
# Builder: compile chroma-hnswlib (no py3.13 wheel on PyPI yet)
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Runtime image (HF Spaces)
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime-only system packages (scrapy/lxml/docling stay out of this image).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Non-root user (HF Spaces convention: uid 1000, $HOME writable)
# ---------------------------------------------------------------------------
RUN useradd --create-home --uid 1000 --shell /bin/bash user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    XDG_CACHE_HOME=/home/user/.cache

WORKDIR /app

COPY --from=builder --chown=user:user /app/.venv /app/.venv

# ---------------------------------------------------------------------------
# App source + (optional) prebuilt ChromaDB collection
#
# data/chroma_db/ is NOT committed to git. On HF Spaces it is uploaded out-of-
# band via `huggingface-cli upload ... --repo-type=space`, so by the time the
# Space builds the image the directory is present in the build context.
#
# Locally, the directory may or may not exist; we copy the whole data/ folder
# (data/raw and data/markdown are excluded by .dockerignore) so the build
# never fails on a missing chroma_db — the app falls back gracefully when
# the collection is absent (see app.py / agents.py).
# ---------------------------------------------------------------------------
COPY --chown=user:user src/ ./src/
COPY --chown=user:user app.py ./app.py
COPY --chown=user:user data/ ./data/

# Surface in the build log whether the prebuilt index made it into the image.
RUN if [ -f /app/data/chroma_db/chroma.sqlite3 ]; then \
        echo "ChromaDB bundled: $(du -sh /app/data/chroma_db | cut -f1)"; \
    else \
        echo "WARNING: no ChromaDB in build context — search_knowledge_base tool will return 'unavailable' at runtime"; \
    fi

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

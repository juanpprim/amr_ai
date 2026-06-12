---
title: AMR Learning Agent
emoji: 🧬
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# AMR Awareness Platform

AI-powered educational platform for Antimicrobial Resistance (AMR) awareness.

## Tech Stack

- **Document Processing:** Scrapy (HTML scraping), Docling (PDF/HTML to markdown)
- **LLM Framework:** PydanticAI with Claude claude-sonnet-4-6
- **Vector DB:** ChromaDB with BioBERT embeddings
- **Retrieval:** Hybrid semantic + BM25 with Reciprocal Rank Fusion
- **UI:** Gradio 5
- **Runtime:** Python 3.13 + uv

## Quick Start

```bash
# Install dependencies
uv sync

# Copy and configure environment
cp .env.example .env

# List available data sources
uv run python scripts/download.py --list

# Download a single source
uv run python scripts/download.py --source who-amr-topics

# Download all sources
uv run python scripts/download.py

# Ingest markdown into ChromaDB
uv run python scripts/ingest.py

# Check collection stats
uv run python scripts/ingest.py --stats

# Run tests
uv run pytest
```

## Project Structure

```
src/
  config.py              # Application settings
  models.py              # Pydantic models
  pipeline/
    sources.py           # Source registry (15 AMR sources)
    scraper.py           # Download logic
    converter.py         # Docling document-to-markdown
    downloader.py        # Pipeline orchestrator
  rag/
    ingestor.py          # Markdown chunking + ChromaDB ingestion
    retriever.py         # Semantic retrieval from ChromaDB
scripts/
  download.py            # CLI for downloading sources
  ingest.py              # CLI for ChromaDB ingestion
data/
  raw/                   # Downloaded PDFs/HTML
  markdown/              # Converted markdown files
  chroma_db/             # ChromaDB persistent storage
```

## Data Sources

The platform ingests content from 15 authoritative AMR sources across 3 categories:

- **API Sources** (5): PubMed, WHO GLASS, CARD, Our World in Data, NCBI NDARO
- **HTML Sources** (5): WHO, CDC, FAO, UK Government, Lancet/PMC
- **PDF Sources** (5): WHO Global Action Plan, US CARB NAP, UN Declaration, World Bank, CDC Threats Report

## Deploying

The same image (`deploy/Dockerfile`) runs on both **Railway** and **Fly.io**:
nginx reverse proxy + OAuth2 Proxy (Auth0 OIDC, multi-user) + Streamlit, with
**Chroma Cloud** as the vector store. Only the way you set env vars differs
per platform.

### Architecture (shared)

```
edge (HTTPS) → nginx :8080 → oauth2-proxy :4180 (Auth0 OIDC)
                          ↘ Streamlit :7860 (127.0.0.1 only)
Chroma Cloud (remote) ← retriever
OpenAI API   (remote) ← agents
```

No persistent volume — vectors live in Chroma Cloud, Streamlit session
state is in-memory (lost on redeploy, which is acceptable for the MVP).

### Prerequisites (shared)

1. **Chroma Cloud** — sign up at <https://trychroma.com/cloud>, create a
   database, copy the API key, tenant name, and database name.
2. **Auth0** — create a *Regular Web Application*. Copy Domain, Client ID,
   Client Secret. The callback URL is platform-specific (see below).
3. **OpenAI** — create a **project-scoped** key (`sk-proj-*`, not the org
   master key) and set a hard monthly spend cap in the org's billing
   settings.
4. **Cookie secret** — generate with `openssl rand -base64 32`.

### One-time Chroma Cloud ingest

Populate Chroma Cloud locally so the first deploy doesn't have to ingest
on cold start:

```bash
export CHROMA_API_KEY=...
export CHROMA_TENANT=...
export CHROMA_DATABASE=...
uv run python scripts/download.py   # if data/markdown/ is empty
uv run python scripts/ingest.py
```

### Required environment variables (shared)

| Variable | Source |
|---|---|
| `OPENAI_API_KEY` | OpenAI project key (`sk-proj-…`) |
| `CHROMA_MODE` | optional — `cloud` (default) or `local` |
| `CHROMA_API_KEY` / `CHROMA_TENANT` / `CHROMA_DATABASE` | Chroma Cloud (required when `CHROMA_MODE=cloud`) |
| `AUTH0_DOMAIN` / `AUTH0_CLIENT_ID` / `AUTH0_CLIENT_SECRET` | Auth0 app |
| `OAUTH2_PROXY_COOKIE_SECRET` | `openssl rand -base64 32` |
| `PUBLIC_HOSTNAME` | the public hostname, no `https://` prefix |
| `OAUTH2_ALLOWED_EMAILS` | **required** — comma-separated allowlist |
| `LOGFIRE_API_KEY` | optional, for observability |

### Local vs cloud ChromaDB

`CHROMA_MODE` controls the vector-store backend for both ingestion and
retrieval:

- `cloud` (default) — `chromadb.CloudClient` with the `CHROMA_*` env vars
  above. This is what Railway and Fly.io should run.
- `local` — `chromadb.PersistentClient` at `chroma_persist_dir`
  (default `./data/chroma_db`). Useful for offline development and tests.

Flip it on the fly without editing `.env`:

```bash
# Ingest into the local DB
CHROMA_MODE=local uv run python scripts/ingest.py

# Run the app against the local DB
CHROMA_MODE=local uv run streamlit run app.py
```

### Railway

1. New project → *Deploy from GitHub repo* → branch `main` → enable
   auto-deploy on push.
2. *Service → Build*: Dockerfile path = `deploy/Dockerfile`.
3. *Service → Networking*: generate a Railway domain (or attach a custom
   one). Set `PUBLIC_HOSTNAME` to that domain.
4. *Service → Healthcheck*: path `/_stcore/health`, port `8080`.
5. *Service → Variables*: paste in the table above.
6. **Auth0 callback URL**: `https://<your>.up.railway.app/oauth2/callback`.
7. Push to `main` → Railway builds and deploys automatically. First build
   takes ~5 min (`uv` compiles `chroma-hnswlib` from source).

### Fly.io

```bash
./scripts/deploy_fly.sh --init     # one-time: launches app on Fly.io

fly secrets set \
    OPENAI_API_KEY=sk-proj-... \
    CHROMA_API_KEY=... CHROMA_TENANT=... CHROMA_DATABASE=... \
    AUTH0_DOMAIN=yourtenant.eu.auth0.com \
    AUTH0_CLIENT_ID=... AUTH0_CLIENT_SECRET=... \
    OAUTH2_PROXY_COOKIE_SECRET="$(openssl rand -base64 32)" \
    PUBLIC_HOSTNAME=amr-learning-agent.fly.dev \
    OAUTH2_ALLOWED_EMAILS=a@x.com,b@y.com

./scripts/deploy_fly.sh            # build + deploy
```

**Auth0 callback URL**: `https://amr-learning-agent.fly.dev/oauth2/callback`.

### Security checklist (applies to both platforms)

- `OAUTH2_ALLOWED_EMAILS` is **not optional**. Without it, anyone with any
  Auth0-federated identity (Google, GitHub, etc.) can log in and incur
  OpenAI charges.
- OpenAI key must be project-scoped with a hard monthly spend cap.
- Auth0 callback URL must match `PUBLIC_HOSTNAME` exactly (https, no
  trailing slash).
- Cookie secret must be 32 bytes from `openssl rand -base64 32`.
- Do **not** enable public log sharing (Railway *Settings → Public Logs* or
  Fly.io public dashboards) — Logfire captures prompts.

### Verification (shared)

After the first deploy:

1. `curl https://<domain>/_stcore/health` → 200 (unauthenticated).
2. `curl https://<domain>/robots.txt` → noindex file (unauthenticated).
3. Visit `https://<domain>/` in an incognito window → redirected to Auth0.
4. Log in with a non-allowlisted email → 403 from oauth2-proxy.
5. Log in with an allowlisted email, ask "What is AMR?" → response streams
   and the `search_knowledge_base` tool fires (visible in Logfire).
6. Platform logs should show
   `Chroma Cloud collection 'amr_knowledge_base' ready (N chunks)` on boot.

If `/_stcore/health` returns 502, the Dockerfile path is wrong. On Railway,
set *Build → Dockerfile path* to `deploy/Dockerfile`. On Fly.io, confirm
`deploy/fly.toml` has `dockerfile = "deploy/Dockerfile"` under `[build]`.

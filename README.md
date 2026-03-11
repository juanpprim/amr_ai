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
scripts/
  download.py            # CLI for downloading sources
data/
  raw/                   # Downloaded PDFs/HTML
  markdown/              # Converted markdown files
```

## Data Sources

The platform ingests content from 15 authoritative AMR sources across 3 categories:

- **API Sources** (5): PubMed, WHO GLASS, CARD, Our World in Data, NCBI NDARO
- **HTML Sources** (5): WHO, CDC, FAO, UK Government, Lancet/PMC
- **PDF Sources** (5): WHO Global Action Plan, US CARB NAP, UN Declaration, World Bank, CDC Threats Report

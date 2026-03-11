# AMR GenAI Platform

## Overview

AI-powered Antimicrobial Resistance (AMR) education platform. Prototype built with PydanticAI agents, ChromaDB RAG, and Gradio UI. Full specs in Obsidian vault `AI/Prototype/Specs/`.

**Current phase:** Data Collection (SPEC-01) -- downloading sources and converting to markdown.

## Tech Stack

- **Runtime:** Python 3.13 + uv
- **Scraping:** Scrapy (HTML), httpx (APIs), Docling (PDF/HTML to markdown)
- **Future:** PydanticAI, Claude claude-sonnet-4-6, ChromaDB, BioBERT embeddings, Gradio 5

## Project Structure

```
src/
  config.py                # Settings model (pydantic-settings, loads .env)
  models.py                # ALL Pydantic models -- single source of truth
  pipeline/
    sources.py             # Phase 1 source registry (15 sources)
    scraper.py             # Download logic (httpx for APIs/PDFs, Scrapy for HTML)
    converter.py           # Docling document-to-markdown conversion
    downloader.py          # Orchestrates download + conversion pipeline
data/
  raw/                     # Downloaded PDFs/HTML (gitignored)
  markdown/                # Converted markdown files (gitignored)
scripts/
  download.py              # CLI: download and convert sources
tests/
  conftest.py              # Shared test fixtures
```

## Coding Conventions (from SPEC-00)

- **Style:** PEP 8, black (line 88), ruff
- **Type hints:** Required on all function signatures -- no bare `Any`
- **Docstrings:** Google style on all public functions and classes
- **Async:** Use async/await throughout agents and scraping
- **Naming:** snake_case files/functions, PascalCase classes, UPPER_SNAKE constants
- **Models:** All Pydantic models in `src/models.py` only, `Field(description=...)` on every field
- **Errors:** Never swallow exceptions silently -- log before re-raising
- **Logging:** Use `logging` module -- no print statements in production code

## Git Commits

```
feat: add new functionality
fix: bug fix
test: add or update tests
docs: documentation changes
chore: dependency updates, config changes
```

## Common Commands

```bash
uv sync                                          # install dependencies
uv run python scripts/download.py --list         # list all sources
uv run python scripts/download.py                # download all sources
uv run python scripts/download.py --source X     # download single source
uv run python scripts/download.py --force        # re-download existing
uv run pytest                                    # run tests
uv run ruff check src/ tests/                    # lint
```

## Build Phases

| Phase | Spec | Status |
|-------|------|--------|
| Data Collection | SPEC-01 | In progress |
| RAG Pipeline | SPEC-02 | Pending |
| AI Agents | SPEC-03 | Pending |
| Flashcard & Judge | SPEC-04 | Pending |
| Gradio UI | SPEC-05 | Pending |
| Deployment | SPEC-06 | Pending |

## AI Agent Instructions

1. Read SPEC-00 (conventions) before implementing any spec
2. Read the target SPEC fully before writing code
3. One spec = one git commit
4. Do not modify `src/models.py` without explicit instruction
5. Run tests after implementation -- all must pass
6. No hardcoded API keys, URLs, or magic numbers

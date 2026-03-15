"""Shared test fixtures for all test modules.

Reference: SPEC-00, Section 7.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Settings
from src.models import SourceConfig

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_settings(monkeypatch):
    """Set required env vars so Settings() can be instantiated in tests."""
    monkeypatch.setenv("PUBMED_API_KEY", "test-key")
    monkeypatch.setenv("PUBMED_EMAIL", "test@test.com")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")


@pytest.fixture
def sample_source():
    """A sample SourceConfig for testing (HTML/Scrapy)."""
    return SourceConfig(
        source_id="test-source",
        title="Test Source",
        url="https://example.com/test",
        organisation="Test Org",
        scraping_method="scrapy",
        expertise_level="beginner",
        content_category="learning",
        document_format="html",
        authority_tier=1,
        crawl_depth=2,
    )


@pytest.fixture
def sample_pdf_source():
    """A sample SourceConfig for testing (PDF/Docling)."""
    return SourceConfig(
        source_id="test-pdf-source",
        title="Test PDF Source",
        url="https://example.com/report.pdf",
        organisation="Test Org",
        scraping_method="docling",
        expertise_level="intermediate",
        content_category="action_plan",
        document_format="pdf",
        authority_tier=1,
    )


@pytest.fixture
def tmp_data_dirs(tmp_path):
    """Create temporary raw and markdown directories."""
    raw_dir = tmp_path / "raw"
    md_dir = tmp_path / "markdown"
    raw_dir.mkdir()
    md_dir.mkdir()
    return raw_dir, md_dir


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    """A Settings instance with data dirs pointing at tmp_path."""
    monkeypatch.setenv("PUBMED_API_KEY", "test-key")
    monkeypatch.setenv("PUBMED_EMAIL", "test@test.com")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    raw_dir = tmp_path / "raw"
    md_dir = tmp_path / "markdown"
    raw_dir.mkdir()
    md_dir.mkdir()
    return Settings(data_raw_dir=raw_dir, data_markdown_dir=md_dir)


@pytest.fixture
def fixture_index_html() -> Path:
    """Path to the sample index HTML fixture."""
    return FIXTURES_DIR / "sample_index.html"


@pytest.fixture
def fixture_subpage_html() -> Path:
    """Path to the sample subpage HTML fixture."""
    return FIXTURES_DIR / "sample_subpage.html"


@pytest.fixture
def fixture_pdf() -> Path:
    """Path to the sample PDF fixture."""
    return FIXTURES_DIR / "sample_report.pdf"

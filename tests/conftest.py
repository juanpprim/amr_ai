"""Shared test fixtures for all test modules.

Reference: SPEC-00, Section 7.
"""

import pytest

from src.models import SourceConfig


@pytest.fixture
def mock_settings(monkeypatch):
    """Set required env vars so Settings() can be instantiated in tests."""
    monkeypatch.setenv("PUBMED_API_KEY", "test-key")
    monkeypatch.setenv("PUBMED_EMAIL", "test@test.com")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")


@pytest.fixture
def sample_source():
    """A sample SourceConfig for testing."""
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
    )


@pytest.fixture
def tmp_data_dirs(tmp_path):
    """Create temporary raw and markdown directories."""
    raw_dir = tmp_path / "raw"
    md_dir = tmp_path / "markdown"
    raw_dir.mkdir()
    md_dir.mkdir()
    return raw_dir, md_dir

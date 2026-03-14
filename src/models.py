"""Pydantic models for the AMR GenAI data pipeline.

All Pydantic models are defined here -- single source of truth.
Other modules import from this file, never define their own models.

Reference: SPEC-00 Section 6, SPEC-01 Section 2.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --- Type Aliases ---

ExpertiseLevel = Literal["beginner", "intermediate", "advanced"]
ContentCategory = Literal["learning", "risk", "impact", "action_plan", "data"]
DocumentFormat = Literal["html", "pdf", "json", "csv", "api"]
ScrapingMethod = Literal[
    "REST_API",
    "scrapy",
    "docling",
    "direct_download",
    "GitHub_API",
]
AuthorityTier = Literal[1, 2, 3, 4]


# --- Pipeline Models (SPEC-01) ---


class SourceConfig(BaseModel):
    """Configuration for a single data source in the pipeline."""

    source_id: str = Field(description="Unique slug e.g. pubmed-amr")
    title: str = Field(description="Human-readable source title")
    url: str = Field(description="Primary URL or API endpoint")
    organisation: str = Field(description="Publishing organisation")
    scraping_method: ScrapingMethod = Field(
        description="Method used to fetch this source"
    )
    expertise_level: ExpertiseLevel = Field(
        description="Target audience expertise level"
    )
    content_category: ContentCategory = Field(
        description="Content classification category"
    )
    document_format: DocumentFormat = Field(
        description="Format of the source document"
    )
    authority_tier: AuthorityTier = Field(
        description="1=WHO/CDC, 2=peer-reviewed, 3=grey, 4=news"
    )
    open_access: bool = Field(
        default=True, description="Whether source is freely accessible"
    )
    api_key_required: bool = Field(
        default=False, description="Whether an API key is needed"
    )
    crawl_depth: int = Field(
        default=1,
        description="Scrapy crawl depth (1=start page only, 2=follow links one level)",
    )


class RawDocument(BaseModel):
    """A raw document fetched from a source before chunking."""

    source_id: str = Field(description="Matches SourceConfig.source_id")
    url: str = Field(description="URL this document was fetched from")
    raw_text: str = Field(description="Raw extracted text content")
    metadata: dict = Field(
        default_factory=dict,
        description="Additional source metadata",
    )


class DownloadResult(BaseModel):
    """Result of downloading and converting a single source."""

    source_id: str = Field(description="Source that was processed")
    success: bool = Field(description="Whether download and conversion succeeded")
    markdown_path: str | None = Field(
        default=None, description="Path to saved markdown file"
    )
    raw_path: str | None = Field(
        default=None, description="Path to saved raw file (PDF/HTML)"
    )
    error_message: str | None = Field(
        default=None, description="Error message if failed"
    )
    char_count: int = Field(
        default=0, description="Character count of converted markdown"
    )

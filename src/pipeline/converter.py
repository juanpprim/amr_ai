"""Document conversion to markdown using Docling.

Converts downloaded PDF and HTML files to clean markdown format
for later chunking and ChromaDB ingestion.

Docling handles complex document layouts including tables,
multi-column PDFs, charts, and nested HTML structures.

Reference: SPEC-01 (adapted from pdfplumber to Docling).
"""

from __future__ import annotations

import logging
from pathlib import Path

from docling.document_converter import DocumentConverter

logger = logging.getLogger(__name__)

# Module-level converter instance -- expensive to create, reuse across calls.
_converter: DocumentConverter | None = None


def _get_converter() -> DocumentConverter:
    """Get or create the shared DocumentConverter instance."""
    global _converter
    if _converter is None:
        logger.info("Initializing Docling DocumentConverter...")
        _converter = DocumentConverter()
        logger.info("Docling DocumentConverter ready")
    return _converter


def convert_file_to_markdown(file_path: Path) -> str:
    """Convert a local PDF or HTML file to markdown using Docling.

    Args:
        file_path: Path to the file to convert (.pdf or .html).

    Returns:
        Markdown text extracted from the document.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file format is not supported.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix not in (".pdf", ".html", ".htm"):
        raise ValueError(f"Unsupported file format: {suffix}")

    logger.info("Converting %s to markdown with Docling...", file_path.name)
    converter = _get_converter()

    result = converter.convert(str(file_path))
    markdown = result.document.export_to_markdown()

    logger.info(
        "Converted %s: %d characters of markdown", file_path.name, len(markdown)
    )
    return markdown


def convert_url_to_markdown(url: str) -> str:
    """Convert a document at a URL directly to markdown using Docling.

    Docling can fetch and convert documents from URLs directly.
    Useful when we don't need to keep the raw file.

    Args:
        url: URL of the document to convert.

    Returns:
        Markdown text extracted from the document.
    """
    logger.info("Converting URL to markdown with Docling: %s", url)
    converter = _get_converter()

    result = converter.convert(url)
    markdown = result.document.export_to_markdown()

    logger.info("Converted URL: %d characters of markdown", len(markdown))
    return markdown


def format_text_as_markdown(
    content: str, title: str, source_id: str, url: str
) -> str:
    """Wrap plain text content (e.g., from API responses) in markdown format.

    Adds a front matter header with source metadata.

    Args:
        content: Raw text content.
        title: Source title.
        source_id: Source identifier.
        url: Source URL.

    Returns:
        Formatted markdown string.
    """
    header = (
        f"# {title}\n\n"
        f"**Source ID:** {source_id}\n"
        f"**URL:** {url}\n\n"
        f"---\n\n"
    )
    return header + content

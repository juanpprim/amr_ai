"""Download orchestrator for the AMR data pipeline.

Ties together scraper and converter to produce markdown files
from all Phase 1 sources. Each source is downloaded, converted
to markdown, and saved to data/markdown/.

For HTML sources (Scrapy), the spider may produce multiple pages,
each saved as a separate markdown file: {source_id}_{page:04d}.md.
For PDF sources, a single markdown file is produced: {source_id}.md.

The pipeline is idempotent: existing markdown files are skipped
unless force=True.

Reference: SPEC-01.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.config import Settings
from src.models import DownloadResult, SourceConfig
from src.pipeline.converter import convert_file_to_markdown
from src.pipeline.scraper import crawl_html, download_pdf

logger = logging.getLogger(__name__)


async def _convert_single_file(
    raw_path: Path, md_path: Path
) -> str:
    """Convert a single raw file to markdown and save it.

    Args:
        raw_path: Path to raw HTML or PDF file.
        md_path: Path to write the markdown output.

    Returns:
        The markdown content.
    """
    markdown = convert_file_to_markdown(raw_path)
    md_path.write_text(markdown, encoding="utf-8")
    logger.info("Saved markdown: %s (%d chars)", md_path.name, len(markdown))
    return markdown


async def download_and_convert(
    source: SourceConfig,
    settings: Settings,
    force: bool = False,
) -> DownloadResult:
    """Download and convert a single source to markdown.

    For Scrapy HTML sources, the spider crawls multiple pages and each
    is converted to a separate markdown file. For PDF sources, a single
    file is produced.

    Args:
        source: Source configuration.
        settings: Application settings.
        force: If True, re-download even if markdown exists.

    Returns:
        DownloadResult with success status and file paths.
    """
    raw_dir = settings.data_raw_dir
    md_dir = settings.data_markdown_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)

    if source.scraping_method == "scrapy":
        return await _download_and_convert_html(source, raw_dir, md_dir, force)

    return await _download_and_convert_pdf(source, raw_dir, md_dir, force)


async def _download_and_convert_html(
    source: SourceConfig,
    raw_dir: Path,
    md_dir: Path,
    force: bool,
) -> DownloadResult:
    """Download and convert an HTML source with Scrapy spider.

    Produces one markdown file per crawled page.

    Args:
        source: Source configuration.
        raw_dir: Directory for raw HTML files.
        md_dir: Directory for markdown output.
        force: If True, re-crawl even if markdown exists.

    Returns:
        DownloadResult with aggregated stats.
    """
    # Check if any pages already exist for this source
    existing = sorted(md_dir.glob(f"{source.source_id}_*.md"))
    if existing and not force:
        total_chars = sum(
            len(p.read_text(encoding="utf-8")) for p in existing
        )
        logger.info(
            "Skipping %s (%d pages already exist, %d chars)",
            source.source_id,
            len(existing),
            total_chars,
        )
        return DownloadResult(
            source_id=source.source_id,
            success=True,
            markdown_path=str(existing[0]),
            char_count=total_chars,
        )

    # Step 1: Crawl with Scrapy spider
    try:
        raw_paths = await crawl_html(source, raw_dir)
    except Exception as e:
        logger.error(
            "Crawl failed for %s: %s", source.source_id, e, exc_info=True
        )
        return DownloadResult(
            source_id=source.source_id,
            success=False,
            error_message=f"Crawl failed: {e}",
        )

    if not raw_paths:
        return DownloadResult(
            source_id=source.source_id,
            success=False,
            error_message="Spider produced no pages",
        )

    # Step 2: Convert each page to markdown
    total_chars = 0
    first_md_path: str | None = None

    for raw_path in raw_paths:
        # Derive markdown filename from raw filename
        md_name = raw_path.stem + ".md"
        md_path = md_dir / md_name

        try:
            markdown = await _convert_single_file(raw_path, md_path)
            total_chars += len(markdown)
            if first_md_path is None:
                first_md_path = str(md_path)
        except Exception as e:
            logger.error(
                "Conversion failed for %s: %s", raw_path.name, e, exc_info=True
            )

    if total_chars == 0:
        return DownloadResult(
            source_id=source.source_id,
            success=False,
            error_message="All page conversions failed",
        )

    return DownloadResult(
        source_id=source.source_id,
        success=True,
        markdown_path=first_md_path,
        raw_path=str(raw_paths[0]),
        char_count=total_chars,
    )


async def _download_and_convert_pdf(
    source: SourceConfig,
    raw_dir: Path,
    md_dir: Path,
    force: bool,
) -> DownloadResult:
    """Download and convert a PDF source.

    Produces a single markdown file: {source_id}.md.

    Args:
        source: Source configuration.
        raw_dir: Directory for raw PDF files.
        md_dir: Directory for markdown output.
        force: If True, re-download even if markdown exists.

    Returns:
        DownloadResult with file paths.
    """
    md_path = md_dir / f"{source.source_id}.md"

    # Skip if already exists and not forcing
    if md_path.exists() and not force:
        char_count = len(md_path.read_text(encoding="utf-8"))
        logger.info(
            "Skipping %s (already exists: %d chars)",
            source.source_id,
            char_count,
        )
        return DownloadResult(
            source_id=source.source_id,
            success=True,
            markdown_path=str(md_path),
            char_count=char_count,
        )

    # Step 1: Download PDF
    try:
        raw_path = await download_pdf(source, raw_dir)
    except Exception as e:
        logger.error(
            "Download failed for %s: %s", source.source_id, e, exc_info=True
        )
        return DownloadResult(
            source_id=source.source_id,
            success=False,
            error_message=f"Download failed: {e}",
        )

    if raw_path is None:
        return DownloadResult(
            source_id=source.source_id,
            success=False,
            error_message="Download returned no content",
        )

    # Step 2: Convert to markdown
    try:
        markdown = await _convert_single_file(raw_path, md_path)
    except Exception as e:
        logger.error(
            "Conversion failed for %s: %s", source.source_id, e, exc_info=True
        )
        return DownloadResult(
            source_id=source.source_id,
            success=False,
            raw_path=str(raw_path),
            error_message=f"Conversion failed: {e}",
        )

    return DownloadResult(
        source_id=source.source_id,
        success=True,
        markdown_path=str(md_path),
        raw_path=str(raw_path),
        char_count=len(markdown),
    )


async def download_all(
    sources: list[SourceConfig],
    settings: Settings,
    force: bool = False,
) -> list[DownloadResult]:
    """Download and convert all sources sequentially.

    Processes sources one at a time to respect rate limits.
    Failures are logged but do not stop the pipeline.

    Args:
        sources: List of source configurations.
        settings: Application settings.
        force: If True, re-download even if markdown exists.

    Returns:
        List of DownloadResult for each source.
    """
    results: list[DownloadResult] = []
    total = len(sources)

    for i, source in enumerate(sources, 1):
        logger.info(
            "Processing [%d/%d] %s (%s)...",
            i,
            total,
            source.source_id,
            source.scraping_method,
        )
        result = await download_and_convert(source, settings, force=force)
        results.append(result)

        if result.success:
            logger.info(
                "[%d/%d] %s: OK (%d chars)",
                i,
                total,
                source.source_id,
                result.char_count,
            )
        else:
            logger.warning(
                "[%d/%d] %s: FAILED - %s",
                i,
                total,
                source.source_id,
                result.error_message,
            )

    # Summary
    successes = sum(1 for r in results if r.success)
    failures = total - successes
    total_chars = sum(r.char_count for r in results)
    logger.info(
        "Pipeline complete: %d/%d succeeded, %d failed, %d total chars",
        successes,
        total,
        failures,
        total_chars,
    )

    return results

"""Download orchestrator for the AMR data pipeline.

Ties together scraper and converter to produce markdown files
from all Phase 1 sources. Each source is downloaded, converted
to markdown, and saved to data/markdown/{source_id}.md.

The pipeline is idempotent: existing markdown files are skipped
unless force=True.

Reference: SPEC-01.
"""

from __future__ import annotations

import logging

from src.config import Settings
from src.models import DownloadResult, SourceConfig
from src.pipeline.converter import convert_file_to_markdown, format_text_as_markdown
from src.pipeline.scraper import download_raw

logger = logging.getLogger(__name__)


async def download_and_convert(
    source: SourceConfig,
    settings: Settings,
    force: bool = False,
) -> DownloadResult:
    """Download and convert a single source to markdown.

    Flow:
    1. Check if markdown already exists (skip if not force).
    2. Download raw content to data/raw/.
    3. Convert to markdown using Docling (PDF/HTML) or format API text.
    4. Save markdown to data/markdown/{source_id}.md.

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

    # Step 1: Download raw content
    try:
        raw_path = await download_raw(source, raw_dir, settings)
    except Exception as e:
        logger.error("Download failed for %s: %s", source.source_id, e, exc_info=True)
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
        if raw_path.suffix in (".pdf", ".html", ".htm"):
            markdown = convert_file_to_markdown(raw_path)
        else:
            # API/text content -- wrap in markdown format
            raw_text = raw_path.read_text(encoding="utf-8")
            markdown = format_text_as_markdown(
                content=raw_text,
                title=source.title,
                source_id=source.source_id,
                url=source.url,
            )
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

    # Step 3: Save markdown
    md_path.write_text(markdown, encoding="utf-8")
    logger.info(
        "Saved markdown: %s (%d chars)", md_path.name, len(markdown)
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

"""CLI entry point for the AMR data download pipeline.

Downloads source documents and converts them to markdown files
for later chunking and ChromaDB ingestion.

Usage:
    uv run python scripts/download.py                      # download all sources
    uv run python scripts/download.py --source pubmed-amr   # single source
    uv run python scripts/download.py --list                # list all sources
    uv run python scripts/download.py --force               # re-download existing

Reference: SPEC-01, Section 5.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path so src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Settings
from src.pipeline.downloader import download_all, download_and_convert
from src.pipeline.sources import PHASE_1_SOURCES, get_source_by_id


def list_sources() -> None:
    """Print all available sources with their metadata."""
    print(f"\n{'ID':<25} {'Method':<18} {'Format':<8} {'Organisation'}")
    print("-" * 80)
    for source in PHASE_1_SOURCES:
        print(
            f"{source.source_id:<25} "
            f"{source.scraping_method:<18} "
            f"{source.document_format:<8} "
            f"{source.organisation}"
        )
    print(f"\nTotal: {len(PHASE_1_SOURCES)} sources")


async def main() -> None:
    """Run the download pipeline."""
    parser = argparse.ArgumentParser(
        description="Download AMR data sources and convert to markdown"
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Download a single source by source_id",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_sources",
        help="List all available sources",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if markdown already exists",
    )
    args = parser.parse_args()

    if args.list_sources:
        list_sources()
        return

    settings = Settings()
    settings.configure_logging()

    if args.source:
        source = get_source_by_id(args.source)
        if source is None:
            print(f"Error: Unknown source '{args.source}'")
            print("Use --list to see available sources")
            sys.exit(1)

        result = await download_and_convert(source, settings, force=args.force)
        if result.success:
            print(
                f"OK: {result.source_id} -> "
                f"{result.markdown_path} ({result.char_count} chars)"
            )
        else:
            print(f"FAILED: {result.source_id} - {result.error_message}")
            sys.exit(1)
    else:
        results = await download_all(PHASE_1_SOURCES, settings, force=args.force)

        # Print summary table
        print(f"\n{'Source':<25} {'Status':<10} {'Chars':>10} {'Path'}")
        print("-" * 80)
        for r in results:
            status = "OK" if r.success else "FAILED"
            path = r.markdown_path or r.error_message or ""
            print(f"{r.source_id:<25} {status:<10} {r.char_count:>10} {path}")

        successes = sum(1 for r in results if r.success)
        print(f"\nDone: {successes}/{len(results)} succeeded")


if __name__ == "__main__":
    asyncio.run(main())

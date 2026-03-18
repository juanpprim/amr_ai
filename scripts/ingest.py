"""CLI script to ingest markdown files into ChromaDB.

Usage:
    uv run python scripts/ingest.py            # ingest all markdown
    uv run python scripts/ingest.py --stats    # print collection stats
"""

from __future__ import annotations

import argparse
import sys

from src.config import Settings
from src.rag.ingestor import get_or_create_collection, ingest_all_markdown
from src.rag.retriever import get_collection_stats


def main() -> None:
    """Entry point for the ingestion CLI."""
    parser = argparse.ArgumentParser(
        description="Ingest markdown files into ChromaDB"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print collection statistics and exit",
    )
    args = parser.parse_args()

    settings = Settings()
    settings.configure_logging()

    if args.stats:
        collection = get_or_create_collection(settings)
        stats = get_collection_stats(collection)
        print(f"Total chunks: {stats['total_chunks']}")
        print(f"Sources: {', '.join(stats['sources']) or '(none)'}")
        if stats["expertise_breakdown"]:
            print("Expertise breakdown:")
            for level, count in sorted(stats["expertise_breakdown"].items()):
                print(f"  {level}: {count}")
        if stats["category_breakdown"]:
            print("Category breakdown:")
            for cat, count in sorted(stats["category_breakdown"].items()):
                print(f"  {cat}: {count}")
        return

    collection = get_or_create_collection(settings)
    total = ingest_all_markdown(settings, collection=collection)

    if total == 0:
        print("No chunks ingested. Is data/markdown/ populated?", file=sys.stderr)
        sys.exit(1)

    print(f"Done: {total} chunks ingested into ChromaDB.")

    stats = get_collection_stats(collection)
    print(f"Collection now has {stats['total_chunks']} total chunks "
          f"from {len(stats['sources'])} sources.")


if __name__ == "__main__":
    main()

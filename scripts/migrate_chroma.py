"""Migrate vector data from local ChromaDB to Chroma Cloud.

Copies all records from the local PersistentClient collection into a
Chroma Cloud collection configured with Qwen dense + Splade sparse hybrid
Schema. Use when upgrading from local MiniLM embeddings to cloud hybrid search.

Usage:
    uv run python -m scripts.migrate_chroma
    uv run python -m scripts.migrate_chroma --recreate
    uv run python -m scripts.migrate_chroma --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys

import chromadb

from src.config import Settings
from src.rag.chroma_client import create_chroma_client
from src.rag.ingestor import UPSERT_BATCH_SIZE
from src.rag.schema import build_hybrid_schema

logger = logging.getLogger(__name__)

READ_BATCH_SIZE = 500


def _read_local_records(
    local_collection: chromadb.Collection,
) -> tuple[list[str], list[str], list[dict]]:
    """Read all records from a local collection in batches."""
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    offset = 0
    while True:
        batch = local_collection.get(
            limit=READ_BATCH_SIZE,
            offset=offset,
            include=["documents", "metadatas"],
        )
        batch_ids = batch["ids"] or []
        if not batch_ids:
            break
        ids.extend(batch_ids)
        documents.extend(batch["documents"] or [])
        metadatas.extend(batch["metadatas"] or [])
        offset += len(batch_ids)
        if len(batch_ids) < READ_BATCH_SIZE:
            break

    return ids, documents, metadatas


def migrate_local_to_cloud(
    settings: Settings,
    *,
    recreate: bool = False,
    dry_run: bool = False,
) -> int:
    """Copy records from local ChromaDB into Chroma Cloud.

    Args:
        settings: Application settings (cloud credentials via env / .env).
        recreate: Delete the cloud collection before re-creating with Schema.
        dry_run: Count records only; do not write to cloud.

    Returns:
        Number of records migrated (or that would be migrated if dry_run).
    """
    local_settings = settings.model_copy(update={"chroma_mode": "local"})
    local_client = create_chroma_client(local_settings)
    try:
        local_collection = local_client.get_collection(settings.chroma_collection_name)
    except Exception as exc:
        logger.error(
            "Local collection '%s' not found: %s",
            settings.chroma_collection_name,
            exc,
        )
        raise SystemExit(1) from exc

    ids, documents, metadatas = _read_local_records(local_collection)
    total = len(ids)
    logger.info(
        "Found %d records in local collection '%s'",
        total,
        settings.chroma_collection_name,
    )
    if total == 0:
        return 0
    if dry_run:
        logger.info("Dry run — no records written to Chroma Cloud")
        return total

    cloud_client = create_chroma_client(settings)
    name = settings.chroma_collection_name

    if recreate:
        try:
            cloud_client.delete_collection(name)
            logger.info("Deleted existing cloud collection '%s'", name)
        except Exception:
            logger.debug(
                "Cloud collection '%s' did not exist or could not be deleted",
                name,
            )

    cloud_collection = cloud_client.get_or_create_collection(
        name=name,
        schema=build_hybrid_schema(),
    )

    for start in range(0, total, UPSERT_BATCH_SIZE):
        end = start + UPSERT_BATCH_SIZE
        cloud_collection.upsert(
            ids=ids[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
        )
        logger.info("Upserted %d / %d records", min(end, total), total)

    logger.info(
        "Migration complete: %d records in cloud collection '%s'",
        cloud_collection.count(),
        name,
    )
    return total


def main() -> None:
    """CLI entry point for local → Chroma Cloud migration."""
    parser = argparse.ArgumentParser(
        description="Migrate local ChromaDB data to Chroma Cloud (hybrid Schema)"
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and recreate the cloud collection before upserting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count local records without writing to cloud",
    )
    args = parser.parse_args()

    settings = Settings()
    settings.configure_logging()

    if settings.chroma_mode != "cloud":
        logger.warning(
            "CHROMA_MODE is '%s'; cloud credentials still required "
            "for migration target",
            settings.chroma_mode,
        )
    if not settings.chroma_api_key or not settings.chroma_tenant:
        print(
            "Set CHROMA_API_KEY, CHROMA_TENANT, CHROMA_DATABASE, and CHROMA_HOST "
            "in .env before migrating.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        count = migrate_local_to_cloud(
            settings,
            recreate=args.recreate,
            dry_run=args.dry_run,
        )
    except SystemExit:
        raise
    except Exception as exc:
        logger.error("Migration failed: %s", exc, exc_info=True)
        sys.exit(1)

    print(f"Migrated {count} records to Chroma Cloud ({settings.chroma_host}).")


if __name__ == "__main__":
    main()

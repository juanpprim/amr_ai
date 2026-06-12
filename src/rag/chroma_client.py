"""ChromaDB client factory for local and Chroma Cloud backends.

Reference: SPEC-02, Chroma Cloud clients docs.
"""

from __future__ import annotations

import logging

import chromadb

from src.config import Settings

logger = logging.getLogger(__name__)


def create_chroma_client(settings: Settings) -> chromadb.ClientAPI:
    """Create a Chroma client for the configured backend.

    Args:
        settings: Application settings.

    Returns:
        A ChromaDB client (PersistentClient or CloudClient).

    Raises:
        ValueError: If cloud mode is selected but credentials are missing.
        RuntimeError: If the client cannot be created.
    """
    try:
        if settings.chroma_mode == "cloud":
            if not settings.chroma_api_key:
                raise ValueError(
                    "CHROMA_API_KEY is required when CHROMA_MODE=cloud"
                )
            if not settings.chroma_tenant or not settings.chroma_database:
                raise ValueError(
                    "CHROMA_TENANT and CHROMA_DATABASE are required when "
                    "CHROMA_MODE=cloud"
                )
            client = chromadb.CloudClient(
                tenant=settings.chroma_tenant,
                database=settings.chroma_database,
                api_key=settings.chroma_api_key,
                cloud_host=settings.chroma_host,
            )
            logger.debug(
                "Connected to Chroma Cloud (host=%s, db=%s)",
                settings.chroma_host,
                settings.chroma_database,
            )
            return client

        client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
        logger.debug(
            "Connected to local ChromaDB at %s", settings.chroma_persist_dir
        )
        return client
    except ValueError:
        raise
    except Exception as exc:
        logger.error(
            "ChromaDB client creation failed (mode=%s): %s",
            settings.chroma_mode,
            exc,
            exc_info=True,
        )
        raise RuntimeError(
            f"ChromaDB client creation failed (mode={settings.chroma_mode}): {exc}"
        ) from exc

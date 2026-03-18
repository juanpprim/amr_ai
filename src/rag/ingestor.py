"""ChromaDB ingestion: chunk markdown files and store in vector DB.

Handles text chunking with overlap and batch upsert into a persistent
ChromaDB collection using the default embedding function (all-MiniLM-L6-v2).

Reference: SPEC-02, SPEC-00 Section 2.
"""

from __future__ import annotations

import logging
from pathlib import Path

import chromadb

from src.config import Settings

logger = logging.getLogger(__name__)


def get_or_create_collection(
    settings: Settings,
) -> chromadb.Collection:
    """Create or open a persistent ChromaDB collection.

    Uses the default embedding function (all-MiniLM-L6-v2) which is
    built into ChromaDB via sentence-transformers.

    Args:
        settings: Application settings with chroma_persist_dir and
            chroma_collection_name.

    Returns:
        A ChromaDB Collection ready for upsert/query.

    Raises:
        RuntimeError: If ChromaDB connection fails (per SPEC-00 rule 4).
    """
    try:
        persist_dir = str(settings.chroma_persist_dir)
        client = chromadb.PersistentClient(path=persist_dir)
        collection = client.get_or_create_collection(
            name=settings.chroma_collection_name,
        )
        logger.info(
            "ChromaDB collection '%s' ready (%d chunks)",
            settings.chroma_collection_name,
            collection.count(),
        )
        return collection
    except Exception as exc:
        logger.error("ChromaDB connection failed: %s", exc, exc_info=True)
        raise RuntimeError(f"ChromaDB connection failed: {exc}") from exc


def chunk_markdown(
    text: str,
    source_id: str,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
) -> list[dict]:
    """Split markdown text into overlapping chunks with metadata.

    Splits on paragraph boundaries (double newlines) when possible,
    falling back to character-level splitting.

    Args:
        text: Full markdown text to chunk.
        source_id: Source identifier for metadata.
        chunk_size: Target chunk size in characters.
        chunk_overlap: Overlap between consecutive chunks in characters.

    Returns:
        List of dicts with keys: id, text, metadata.
    """
    if not text or not text.strip():
        return []

    paragraphs = text.split("\n\n")
    chunks: list[dict] = []
    current_chunk = ""
    chunk_index = 0

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        candidate = (
            f"{current_chunk}\n\n{paragraph}" if current_chunk else paragraph
        )

        if len(candidate) > chunk_size and current_chunk:
            # Flush current chunk
            chunks.append(
                {
                    "id": f"{source_id}_chunk_{chunk_index:04d}",
                    "text": current_chunk.strip(),
                    "metadata": {
                        "source_id": source_id,
                        "chunk_index": chunk_index,
                    },
                }
            )
            chunk_index += 1

            # Start new chunk with overlap from end of previous
            if chunk_overlap:
                overlap_text = current_chunk[-chunk_overlap:]
                current_chunk = f"{overlap_text}\n\n{paragraph}"
            else:
                current_chunk = paragraph
        else:
            current_chunk = candidate

    # Flush remaining text
    if current_chunk.strip():
        chunks.append(
            {
                "id": f"{source_id}_chunk_{chunk_index:04d}",
                "text": current_chunk.strip(),
                "metadata": {
                    "source_id": source_id,
                    "chunk_index": chunk_index,
                },
            }
        )

    logger.debug(
        "Chunked source '%s': %d chunks from %d chars",
        source_id,
        len(chunks),
        len(text),
    )
    return chunks


def ingest_markdown_file(
    file_path: Path,
    collection: chromadb.Collection,
    settings: Settings,
) -> int:
    """Read a markdown file, chunk it, and upsert into ChromaDB.

    Args:
        file_path: Path to the markdown file.
        collection: ChromaDB collection to upsert into.
        settings: Application settings for chunk size/overlap.

    Returns:
        Number of chunks ingested.

    Raises:
        FileNotFoundError: If file_path does not exist.
    """
    text = file_path.read_text(encoding="utf-8")
    source_id = file_path.stem

    chunks = chunk_markdown(
        text=text,
        source_id=source_id,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )

    if not chunks:
        logger.warning("No chunks produced from %s", file_path)
        return 0

    # Batch upsert into ChromaDB
    collection.upsert(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )

    logger.info(
        "Ingested %s: %d chunks",
        file_path.name,
        len(chunks),
    )
    return len(chunks)


def ingest_markdown_files(
    settings: Settings,
    source_id: str) -> int:
    """Walk data/markdown/ and ingest all .md files into ChromaDB.

    Args:
        settings: Application settings.
        
    Returns:
        Total number of chunks ingested across all files.
    """
    md_dir = settings.data_markdown_dir
    if not md_dir.exists():
        logger.warning("Markdown directory does not exist: %s", md_dir)
        return 0

    md_files = sorted(md_dir.glob("*.md"))
    if not md_files:
        logger.warning("No markdown files found in %s", md_dir)
        return 0

    if source_id:
        md_files = [md_file for md_file in md_files if source_id in md_file.stem]

    total_chunks = 0
    for i, md_file in enumerate(md_files, 1):
        logger.info("[%d/%d] Ingesting %s", i, len(md_files), md_file.name)
        try:
            count = ingest_markdown_file(md_file, collection, settings)
            total_chunks += count
        except Exception as exc:
            logger.warning(
                "Failed to ingest %s: %s", md_file.name, exc, exc_info=True
            )

    logger.info(
        "Ingestion complete: %d chunks from %d files",
        total_chunks,
        len(md_files),
    )
    return total_chunks

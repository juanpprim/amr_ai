"""ChromaDB ingestion: chunk markdown files and store in vector DB.

Cloud mode uses Chroma Cloud with Qwen dense + Splade sparse embeddings
(configured via collection Schema). Local mode uses PersistentClient with
the default MiniLM embedding function for offline dev and tests.

Reference: SPEC-02, SPEC-00 Section 2.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import chromadb

from src.config import Settings
from src.rag.chroma_client import create_chroma_client
from src.rag.schema import build_hybrid_schema

logger = logging.getLogger(__name__)

# Chroma Cloud document size limit (16 KiB per record).
MAX_DOCUMENT_BYTES = 16 * 1024

# Batch size for upsert operations to Chroma Cloud.
UPSERT_BATCH_SIZE = 100


def _normalize_chunk_text(text: str) -> str:
    """Normalize chunk text to make hashing stable across whitespace changes."""
    return re.sub(r"\s+", " ", text).strip()


def _content_hash(text: str) -> str:
    """Compute a SHA-256 hash for normalized chunk text."""
    normalized_text = _normalize_chunk_text(text)
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def _chunk_id(source_id: str, chunk_index: int) -> str:
    """Build a deterministic chunk ID from source and index."""
    return f"{source_id}_chunk_{chunk_index:04d}"


def _truncate_to_byte_limit(text: str, max_bytes: int = MAX_DOCUMENT_BYTES) -> str:
    """Truncate text to fit within Chroma's per-document byte limit."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    # Avoid splitting a multi-byte UTF-8 character.
    while truncated:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return ""


def get_or_create_collection(
    settings: Settings,
) -> chromadb.Collection:
    """Create or open a ChromaDB collection (Chroma Cloud or local).

    Cloud collections are created with a hybrid Schema (Qwen dense + Splade
    sparse). Local collections use the default embedding function so tests
    can run offline.

    Args:
        settings: Application settings.

    Returns:
        A ChromaDB Collection ready for upsert/query.

    Raises:
        RuntimeError: If the backend connection fails (per SPEC-00 rule 4).
    """
    try:
        client = create_chroma_client(settings)

        if settings.chroma_mode == "cloud":
            collection = client.get_or_create_collection(
                name=settings.chroma_collection_name,
                schema=build_hybrid_schema(),
            )
            backend = f"Chroma Cloud ({settings.chroma_host})"
        else:
            collection = client.get_or_create_collection(
                name=settings.chroma_collection_name,
            )
            backend = f"local ({settings.chroma_persist_dir})"

        logger.info(
            "%s collection '%s' ready (%d chunks)",
            backend,
            settings.chroma_collection_name,
            collection.count(),
        )
        return collection
    except Exception as exc:
        logger.error(
            "ChromaDB connection failed (mode=%s): %s",
            settings.chroma_mode,
            exc,
            exc_info=True,
        )
        raise RuntimeError(
            f"ChromaDB connection failed (mode={settings.chroma_mode}): {exc}"
        ) from exc


def chunk_markdown(
    text: str,
    source_id: str,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
) -> list[dict]:
    """Split markdown text into overlapping line-based chunks with metadata.

    Line-based chunking is the recommended starting point for Chroma Cloud.
    Each chunk includes ``source_id`` and ``chunk_index`` metadata for
    GroupBy deduplication at query time. Chunks are capped at 16 KiB.

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

    lines = text.splitlines()
    chunks: list[dict] = []
    current_lines: list[str] = []
    current_len = 0
    chunk_index = 0

    def flush_chunk() -> None:
        nonlocal chunk_index, current_lines, current_len
        if not current_lines:
            return
        chunk_text = _truncate_to_byte_limit("\n".join(current_lines).strip())
        if not chunk_text:
            current_lines = []
            current_len = 0
            return
        chunks.append(
            {
                "id": _chunk_id(source_id, chunk_index),
                "text": chunk_text,
                "metadata": {
                    "source_id": source_id,
                    "chunk_index": chunk_index,
                    "content_hash": _content_hash(chunk_text),
                },
            }
        )
        chunk_index += 1
        if chunk_overlap and chunk_text:
            overlap_text = chunk_text[-chunk_overlap:]
            current_lines = [overlap_text] if overlap_text.strip() else []
            current_len = len(overlap_text)
        else:
            current_lines = []
            current_len = 0

    for line in lines:
        line = line.rstrip()
        if not line and not current_lines:
            continue

        candidate_len = current_len + len(line) + (1 if current_lines else 0)
        if current_lines and candidate_len > chunk_size:
            flush_chunk()

        current_lines.append(line)
        current_len = len("\n".join(current_lines))

        if len(current_lines[-1].encode("utf-8")) > MAX_DOCUMENT_BYTES:
            long_line = current_lines.pop()
            current_len = len("\n".join(current_lines)) if current_lines else 0
            if current_lines:
                flush_chunk()
            split_line = _truncate_to_byte_limit(long_line)
            if split_line:
                current_lines = [split_line]
                current_len = len(split_line)
                flush_chunk()

    if current_lines:
        flush_chunk()

    deduped_chunks: list[dict] = []
    seen_ids: set[str] = set()
    for chunk in chunks:
        cid = str(chunk["id"])
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        deduped_chunks.append(chunk)

    if len(deduped_chunks) != len(chunks):
        logger.debug(
            "Deduplicated source '%s': %d -> %d chunks",
            source_id,
            len(chunks),
            len(deduped_chunks),
        )

    logger.debug(
        "Chunked source '%s': %d chunks from %d chars",
        source_id,
        len(deduped_chunks),
        len(text),
    )
    return deduped_chunks


def _upsert_batches(
    collection: chromadb.Collection,
    chunks: list[dict],
) -> None:
    """Upsert chunks in batches to stay within API payload limits."""
    for start in range(0, len(chunks), UPSERT_BATCH_SIZE):
        batch = chunks[start : start + UPSERT_BATCH_SIZE]
        collection.upsert(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )


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

    collection.delete(where={"source_id": source_id})
    _upsert_batches(collection, chunks)

    logger.info(
        "Ingested %s: %d chunks",
        file_path.name,
        len(chunks),
    )
    return len(chunks)


def ingest_markdown_files(
    settings: Settings,
    source_id: str | None = None,
) -> int:
    """Walk data/markdown/ and ingest all .md files into ChromaDB.

    Args:
        settings: Application settings.
        source_id: Optional filter — ingest only files whose stem contains this.

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

    collection = get_or_create_collection(settings)

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

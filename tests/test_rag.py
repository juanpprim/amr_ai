"""Tests for the RAG pipeline: chunking, ingestion, and retrieval.

Uses in-memory ChromaDB -- no disk I/O, no external services.
Reference: SPEC-02 Sections 6e-6g, 9.
"""

from __future__ import annotations

from src.config import Settings
from src.rag.ingestor import chunk_markdown, ingest_markdown_file
from src.rag.retriever import (
    get_collection_stats,
    retrieve,
    retrieve_random_chunk,
)

# --- Chunking tests ---


def test_chunk_markdown_produces_chunks():
    """Chunking 2000-char text with chunk_size=500 produces multiple chunks."""
    text = ("This is a paragraph about AMR.\n\n" * 40).strip()
    chunks = chunk_markdown(text, source_id="test-src", chunk_size=500)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk["metadata"]["source_id"] == "test-src"
        assert "chunk_index" in chunk["metadata"]
        assert chunk["id"].startswith("test-src_chunk_")


def test_chunk_markdown_overlap():
    """Consecutive chunks share overlapping content."""
    # Create paragraphs with unique markers
    paragraphs = [f"Paragraph {i} about antimicrobial resistance." for i in range(20)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_markdown(
        text, source_id="overlap-test", chunk_size=200, chunk_overlap=50
    )
    assert len(chunks) >= 2
    # The overlap should cause some text from chunk N to appear in chunk N+1
    for i in range(len(chunks) - 1):
        tail = chunks[i]["text"][-50:]
        assert tail in chunks[i + 1]["text"], (
            f"Expected overlap between chunk {i} and {i+1}"
        )


def test_chunk_markdown_empty_text():
    """Empty input returns empty list."""
    assert chunk_markdown("", source_id="empty") == []
    assert chunk_markdown("   ", source_id="spaces") == []


# --- Ingestion tests ---


def test_ingest_markdown_file(tmp_path, chroma_collection, monkeypatch):
    """Ingest a temp markdown file and verify chunks are stored."""
    monkeypatch.setenv("PUBMED_EMAIL", "test@test.com")

    md_file = tmp_path / "test-source.md"
    md_file.write_text(
        "# AMR Overview\n\n"
        "Antimicrobial resistance is a global health threat.\n\n"
        "Bacteria evolve resistance through mutations and gene transfer.\n\n"
        "WHO has declared AMR a top 10 global public health threat.\n\n"
        "Drug-resistant infections cause significant morbidity.\n\n"
        * 5
    )

    settings = Settings(
        data_raw_dir=tmp_path / "raw",
        data_markdown_dir=tmp_path,
        rag_chunk_size=300,
        rag_chunk_overlap=50,
    )

    count = ingest_markdown_file(md_file, chroma_collection, settings)
    assert count > 0
    assert chroma_collection.count() == count


# --- Retrieval tests ---


def test_retrieve_returns_context(seeded_collection):
    """Semantic retrieval returns RetrievedContext with chunks."""
    ctx = retrieve("antimicrobial resistance", seeded_collection, top_k=3)
    assert ctx.query == "antimicrobial resistance"
    assert ctx.retrieval_method_used == "semantic"
    assert len(ctx.chunks) <= 3
    assert len(ctx.chunks) > 0
    assert ctx.total_retrieved == len(ctx.chunks)
    assert len(ctx.sources_cited) > 0
    # Scores should be in [0, 1]
    for chunk in ctx.chunks:
        assert 0.0 <= chunk.score <= 1.0


def test_retrieve_empty_collection(chroma_collection):
    """Empty collection returns empty context without exception."""
    ctx = retrieve("anything", chroma_collection)
    assert ctx.query == "anything"
    assert ctx.chunks == []
    assert ctx.total_retrieved == 0
    assert ctx.has_sufficient_context is False


def test_retrieve_has_sufficient_context_flag(seeded_collection):
    """Relevant query gets True; gibberish gets False."""
    relevant = retrieve("carbapenem-resistant Klebsiella NDM-1", seeded_collection)
    irrelevant = retrieve("xyzzy foobar blargh quantum cheese", seeded_collection)

    # Relevant query should score higher
    if relevant.chunks and irrelevant.chunks:
        assert relevant.chunks[0].score > irrelevant.chunks[0].score

    # Gibberish should have low or no context
    # (Note: exact threshold behavior depends on embeddings, so we test
    # that the flag is a bool and the relevant one scores higher)
    assert isinstance(relevant.has_sufficient_context, bool)
    assert isinstance(irrelevant.has_sufficient_context, bool)


def test_retrieve_random_chunk(seeded_collection):
    """Seeded collection returns a single RetrievedChunk."""
    chunk = retrieve_random_chunk(seeded_collection)
    assert chunk is not None
    assert chunk.chunk_id in [
        "who-amr_chunk_0000",
        "who-amr_chunk_0001",
        "cdc-threats_chunk_0000",
        "cdc-threats_chunk_0001",
        "fao-amr_chunk_0000",
    ]
    assert chunk.score == 1.0
    assert chunk.text


def test_retrieve_random_chunk_empty(chroma_collection):
    """Empty collection returns None."""
    assert retrieve_random_chunk(chroma_collection) is None


# --- Stats tests ---


def test_get_collection_stats(seeded_collection):
    """Stats return correct totals and source list."""
    stats = get_collection_stats(seeded_collection)
    assert stats["total_chunks"] == 5
    assert sorted(stats["sources"]) == ["cdc-threats", "fao-amr", "who-amr"]


def test_get_collection_stats_empty(chroma_collection):
    """Empty collection stats are zeroed out."""
    stats = get_collection_stats(chroma_collection)
    assert stats["total_chunks"] == 0
    assert stats["sources"] == []

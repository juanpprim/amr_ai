"""Hybrid retrieval from ChromaDB.

Cloud mode uses the Chroma Search API with dense + sparse RRF and GroupBy
deduplication by ``source_id``. Local mode falls back to legacy ``query()``
for offline development and tests.

Reference: SPEC-02 Sections 6e, 6f, 6g.
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

import chromadb
from chromadb import K, Knn, Rrf, Search
from chromadb.execution.expression.operator import GroupBy, MinK

from src.models import (
    AuthorityTier,
    ContentCategory,
    ExpertiseLevel,
    RetrievedChunk,
    RetrievedContext,
)
from src.rag.schema import SPARSE_EMBEDDING_KEY

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)

SEMANTIC_THRESHOLD = 0.45
"""Minimum relevance score for has_sufficient_context flag."""

HYBRID_KNN_LIMIT = 200
"""Candidate pool size per ranking arm before RRF fusion."""


def _build_chroma_filter(
    expertise_level: ExpertiseLevel | None = None,
    content_category: ContentCategory | None = None,
    authority_tier_max: AuthorityTier | None = None,
) -> dict | None:
    """Build a ChromaDB where-filter from optional metadata params.

    Args:
        expertise_level: Filter by expertise level.
        content_category: Filter by content category.
        authority_tier_max: Filter by max authority tier (1-4).

    Returns:
        ChromaDB where dict, or None if no filters.
    """
    filters: list[dict] = []

    if expertise_level is not None:
        filters.append({"expertise_level": {"$eq": expertise_level}})
    if content_category is not None:
        filters.append({"content_category": {"$eq": content_category}})
    if authority_tier_max is not None:
        filters.append({"authority_tier": {"$lte": authority_tier_max}})

    if not filters:
        return None
    if len(filters) == 1:
        return filters[0]
    return {"$and": filters}


def _distance_to_similarity(distance: float) -> float:
    """Convert ChromaDB L2 distance to cosine similarity.

    ChromaDB default uses L2 distance on normalised embeddings,
    so: similarity = 1 - (distance / 2), clamped to [0, 1].

    Args:
        distance: ChromaDB distance value.

    Returns:
        Similarity score in [0, 1].
    """
    sim = 1.0 - (distance / 2.0)
    return max(0.0, min(1.0, sim))


def _rrf_score_to_similarity(score: float) -> float:
    """Map an RRF score (negative, closer to zero is better) to [0, 1]."""
    return max(0.0, min(1.0, 1.0 + score))


def _retrieve_hybrid(
    query: str,
    collection: chromadb.Collection,
    top_k: int,
    where_filter: dict | None,
) -> RetrievedContext:
    """Hybrid dense + sparse search with RRF and per-source GroupBy."""
    hybrid_rank = Rrf(
        ranks=[
            Knn(query=query, return_rank=True, limit=HYBRID_KNN_LIMIT),
            Knn(
                query=query,
                key=SPARSE_EMBEDDING_KEY,
                return_rank=True,
                limit=HYBRID_KNN_LIMIT,
            ),
        ],
        weights=[0.7, 0.3],
    )

    search = Search().rank(hybrid_rank).group_by(
        GroupBy(
            keys=K("source_id"),
            aggregate=MinK(keys=K.SCORE, k=1),
        )
    ).limit(top_k).select(K.DOCUMENT, K.SCORE, K.METADATA)

    if where_filter is not None:
        search = search.where(where_filter)

    try:
        results = collection.search(search)
    except Exception as exc:
        logger.error("Chroma Search API failed: %s", exc, exc_info=True)
        return RetrievedContext(
            query=query,
            retrieval_method_used="hybrid",
        )

    rows = results.rows()[0] if results.rows() else []
    chunks: list[RetrievedChunk] = []
    for row in rows:
        meta = row.get("metadata") or {}
        score = _rrf_score_to_similarity(float(row.get("score") or 0.0))
        if score < 0.25:
            continue
        chunks.append(
            RetrievedChunk(
                chunk_id=row["id"],
                source_id=meta.get("source_id", "unknown"),
                text=row.get("document") or "",
                score=score,
                retrieval_method="hybrid",
                metadata=meta,
            )
        )

    has_sufficient = chunks[0].score >= SEMANTIC_THRESHOLD if chunks else False
    sources = list({c.source_id for c in chunks})

    return RetrievedContext(
        query=query,
        chunks=chunks,
        total_retrieved=len(chunks),
        sources_cited=sources,
        retrieval_method_used="hybrid",
        has_sufficient_context=has_sufficient,
    )


def _retrieve_semantic(
    query: str,
    collection: chromadb.Collection,
    top_k: int,
    where_filter: dict | None,
) -> RetrievedContext:
    """Legacy semantic retrieval via collection.query() for local mode."""
    query_kwargs: dict = {
        "query_texts": [query],
        "n_results": min(top_k, collection.count()),
        "include": ["documents", "metadatas", "distances"],
    }
    if where_filter is not None:
        query_kwargs["where"] = where_filter

    try:
        results = collection.query(**query_kwargs)
    except Exception as exc:
        logger.error("ChromaDB query failed: %s", exc, exc_info=True)
        return RetrievedContext(
            query=query,
            retrieval_method_used="semantic",
        )

    ids = results["ids"][0] if results["ids"] else []
    documents = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []
    distances = results["distances"][0] if results["distances"] else []

    chunks: list[RetrievedChunk] = []
    for chunk_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
        sim = _distance_to_similarity(dist)
        if sim < 0.25:
            continue
        chunks.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                source_id=meta.get("source_id", "unknown"),
                text=doc,
                score=sim,
                retrieval_method="semantic",
                metadata=meta,
            )
        )

    has_sufficient = chunks[0].score >= SEMANTIC_THRESHOLD if chunks else False
    sources = list({c.source_id for c in chunks})

    return RetrievedContext(
        query=query,
        chunks=chunks,
        total_retrieved=len(chunks),
        sources_cited=sources,
        retrieval_method_used="semantic",
        has_sufficient_context=has_sufficient,
    )


def retrieve(
    query: str,
    collection: chromadb.Collection,
    top_k: int = 5,
    expertise_level: ExpertiseLevel | None = None,
    content_category: ContentCategory | None = None,
    authority_tier_max: AuthorityTier | None = None,
    settings: Settings | None = None,
) -> RetrievedContext:
    """Retrieve relevant chunks from ChromaDB.

    Uses hybrid RRF search on Chroma Cloud; falls back to semantic query()
    for local PersistentClient collections.

    Args:
        query: User query string.
        collection: ChromaDB collection to search.
        top_k: Number of results to return.
        expertise_level: Optional metadata filter.
        content_category: Optional metadata filter.
        authority_tier_max: Optional metadata filter.
        settings: Optional settings — when ``chroma_mode=cloud``, enables hybrid.

    Returns:
        RetrievedContext with ranked chunks and metadata.
    """
    if collection.count() == 0:
        logger.info("Empty collection, returning empty context")
        return RetrievedContext(
            query=query,
            retrieval_method_used="hybrid"
            if settings and settings.chroma_mode == "cloud"
            else "semantic",
        )

    where_filter = _build_chroma_filter(
        expertise_level, content_category, authority_tier_max
    )

    use_hybrid = settings is not None and settings.chroma_mode == "cloud"
    if use_hybrid:
        return _retrieve_hybrid(query, collection, top_k, where_filter)
    return _retrieve_semantic(query, collection, top_k, where_filter)


def retrieve_random_chunk(
    collection: chromadb.Collection,
    expertise_level: ExpertiseLevel | None = None,
    content_category: ContentCategory | None = None,
) -> RetrievedChunk | None:
    """Fetch one random chunk from ChromaDB.

    Used by the Flashcard Agent. Not query-based -- does not use
    semantic or keyword search.

    Args:
        collection: ChromaDB collection.
        expertise_level: Optional metadata filter.
        content_category: Optional metadata filter.

    Returns:
        A single RetrievedChunk, or None if collection is empty.
    """
    where_filter = _build_chroma_filter(
        expertise_level=expertise_level,
        content_category=content_category,
    )

    get_kwargs: dict = {
        "limit": 100,
        "include": ["documents", "metadatas"],
    }
    if where_filter is not None:
        get_kwargs["where"] = where_filter

    results = collection.get(**get_kwargs)

    ids = results["ids"] if results["ids"] else []
    if not ids:
        return None

    idx = random.randrange(len(ids))
    return RetrievedChunk(
        chunk_id=ids[idx],
        source_id=results["metadatas"][idx].get("source_id", "unknown"),
        text=results["documents"][idx],
        score=1.0,
        retrieval_method="keyword",
        metadata=results["metadatas"][idx],
    )


def get_collection_stats(collection: chromadb.Collection) -> dict:
    """Return summary statistics for a ChromaDB collection.

    Args:
        collection: ChromaDB collection to inspect.

    Returns:
        Dict with total_chunks, sources, expertise_breakdown,
        and category_breakdown.
    """
    total = collection.count()
    if total == 0:
        return {
            "total_chunks": 0,
            "sources": [],
            "expertise_breakdown": {},
            "category_breakdown": {},
        }

    all_data = collection.get(include=["metadatas"])
    metadatas = all_data["metadatas"] or []

    sources: set[str] = set()
    expertise: dict[str, int] = {}
    categories: dict[str, int] = {}

    for meta in metadatas:
        src = meta.get("source_id", "unknown")
        sources.add(src)

        exp = meta.get("expertise_level", "unknown")
        expertise[exp] = expertise.get(exp, 0) + 1

        cat = meta.get("content_category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "total_chunks": total,
        "sources": sorted(sources),
        "expertise_breakdown": expertise,
        "category_breakdown": categories,
    }

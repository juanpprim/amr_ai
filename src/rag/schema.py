"""Chroma Cloud collection schema: dense Qwen + sparse Splade hybrid indexes.

Reference: Chroma Cloud sparse vector search and embedding model docs.
"""

from __future__ import annotations

from chromadb import Schema, SparseVectorIndexConfig, VectorIndexConfig
from chromadb.utils.embedding_functions.chroma_cloud_qwen_embedding_function import (
    ChromaCloudQwenEmbeddingFunction,
    ChromaCloudQwenEmbeddingModel,
)
from chromadb.utils.embedding_functions.chroma_cloud_splade_embedding_function import (
    ChromaCloudSpladeEmbeddingFunction,
)

# Metadata field populated automatically by Chroma when upserting documents.
SPARSE_EMBEDDING_KEY = "sparse_embedding"


def build_hybrid_schema() -> Schema:
    """Build a collection schema with Chroma Cloud Qwen dense + Splade sparse.

    Dense vectors use the default ``#embedding`` field (from ``#document``).
    Sparse vectors are stored under ``sparse_embedding`` and indexed for hybrid
    search with RRF.

    Returns:
        A Schema ready for ``get_or_create_collection(schema=...)``.
    """
    qwen_ef = ChromaCloudQwenEmbeddingFunction(
        model=ChromaCloudQwenEmbeddingModel.QWEN3_EMBEDDING_0p6B,
        task=None,
    )
    splade_ef = ChromaCloudSpladeEmbeddingFunction()

    schema = Schema()
    schema.create_index(
        config=VectorIndexConfig(
            embedding_function=qwen_ef,
            space="cosine",
        )
    )
    schema.create_index(
        config=SparseVectorIndexConfig(
            source_key="#document",
            embedding_function=splade_ef,
        ),
        key=SPARSE_EMBEDDING_KEY,
    )
    return schema

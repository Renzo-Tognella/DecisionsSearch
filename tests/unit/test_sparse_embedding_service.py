from __future__ import annotations

import asyncio

import pytest

from decisionssearch.domain.shared.exceptions import EmbeddingError
from decisionssearch.infrastructure.ai.embeddings.sparse_embedding_service import SparseEmbeddingService


class FakeSparseEmbedding:
    def __init__(self, indices, values):
        self.indices = indices
        self.values = values


class FakeEncoder:
    def __init__(self, embeddings):
        self.embeddings = embeddings
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return iter(self.embeddings)


def test_sparse_encoder_returns_none_when_disabled() -> None:
    encoder = FakeEncoder([FakeSparseEmbedding([1], [0.5])])
    service = SparseEmbeddingService(enabled=False, encoder=encoder)

    assert asyncio.run(service.embed("invoice-v2")) is None
    assert encoder.calls == []


def test_sparse_encoder_converts_fastembed_shape_to_qdrant_vector() -> None:
    encoder = FakeEncoder([FakeSparseEmbedding([3, 9], [0.7, 0.2])])
    service = SparseEmbeddingService(enabled=True, encoder=encoder)

    vector = asyncio.run(service.embed("billing.invoice.created"))

    assert vector is not None
    assert vector.indices == [3, 9]
    assert vector.values == [0.7, 0.2]
    assert encoder.calls == [["billing.invoice.created"]]


def test_sparse_encoder_rejects_mismatched_indices_and_values() -> None:
    encoder = FakeEncoder([FakeSparseEmbedding([3, 9], [0.7])])
    service = SparseEmbeddingService(enabled=True, encoder=encoder)

    with pytest.raises(EmbeddingError, match="tamanhos diferentes"):
        asyncio.run(service.embed("billing"))

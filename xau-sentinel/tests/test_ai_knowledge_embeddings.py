"""Tests for ai/knowledge/embeddings.py: determinism, dimensionality, and
similarity ordering sanity (the properties retrieval actually depends on)."""
import pytest

from ai.knowledge.embeddings import (
    LocalHashingEmbeddingProvider, cosine_similarity, get_embedding_provider,
)


def test_embedding_is_deterministic_across_calls():
    provider = LocalHashingEmbeddingProvider()
    a = provider.embed_one("liquidity sweep and market structure shift")
    b = provider.embed_one("liquidity sweep and market structure shift")
    assert a == b


def test_embedding_is_deterministic_across_fresh_instances():
    """Critical for correctness, not just a nice-to-have: chunk embeddings
    are computed once at seed time and compared against query embeddings
    computed fresh in a LATER, separate process run — if the hash weren't
    stable, stored embeddings would silently stop matching anything."""
    a = LocalHashingEmbeddingProvider().embed_one("displacement and FundedNext risk")
    b = LocalHashingEmbeddingProvider().embed_one("displacement and FundedNext risk")
    assert a == b


def test_embedding_has_the_configured_dimension():
    provider = LocalHashingEmbeddingProvider()
    vec = provider.embed_one("test")
    assert len(vec) == provider.dim == 256


def test_embedding_is_l2_normalized():
    provider = LocalHashingEmbeddingProvider()
    vec = provider.embed_one("some reasonably long sentence about trading strategy rules")
    norm = sum(v * v for v in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_empty_text_produces_a_zero_vector_not_a_crash():
    provider = LocalHashingEmbeddingProvider()
    vec = provider.embed_one("")
    assert vec == [0.0] * provider.dim


def test_stopword_only_text_produces_a_zero_vector():
    provider = LocalHashingEmbeddingProvider()
    vec = provider.embed_one("the a an is are was")
    assert all(v == 0.0 for v in vec)


def test_similar_text_scores_higher_than_unrelated_text():
    provider = LocalHashingEmbeddingProvider()
    query = provider.embed_one("liquidity sweep displacement structure shift")
    near = provider.embed_one("sweep displacement liquidity structure")
    far = provider.embed_one("pizza recipe pineapple topping recommendation")

    assert cosine_similarity(query, near) > cosine_similarity(query, far)


def test_get_embedding_provider_defaults_to_local(monkeypatch):
    import config
    monkeypatch.setattr(config, "AI_EMBEDDING_PROVIDER", "local")
    provider = get_embedding_provider()
    assert provider.name == "local"


def test_get_embedding_provider_rejects_unknown_name():
    with pytest.raises(ValueError):
        get_embedding_provider("some-unknown-provider")


def test_cosine_similarity_handles_mismatched_or_empty_vectors():
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_similarity_of_identical_vectors_is_one():
    provider = LocalHashingEmbeddingProvider()
    vec = provider.embed_one("market structure and liquidity")
    assert abs(cosine_similarity(vec, vec) - 1.0) < 1e-9

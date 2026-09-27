"""Embedding provider abstraction — mirrors ai/providers/base.py's exact
pattern (a swappable interface + factory keyed by config) so a real
dense-model backend (Voyage, OpenAI, a local sentence-transformers model)
can be added later without touching retrieval or the assistant.

The default (and only) provider, `local`, is a dependency-free feature-
hashing vectorizer: no model download, no API key, no network call, fully
deterministic — matching "local/simple development implementation first;
avoid unnecessary infrastructure" from the Stage 5 spec.
"""
import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import List, Optional

import config

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# A raw term-frequency hash vector without this would let common English
# words dominate cosine similarity for EVERY query (they appear in nearly
# every document), making topically-irrelevant queries score just as high
# as relevant ones — this is what "irrelevant retrieval rejection" actually
# depends on with a bag-of-words-style embedding.
_STOPWORDS = frozenset("""
a an the this that these those is are was were be been being am
to of in on at by for with from into over under about as at than then
and or but if not no nor so yet
i you he she it we they me him her us them my your his its our their
do does did done doing have has had having
what which who whom whose when where why how
can could will would shall should may might must
there here
""".split())


class BaseEmbeddingProvider(ABC):
    name: str = "base"
    dim: int = 0

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text])[0]


class LocalHashingEmbeddingProvider(BaseEmbeddingProvider):
    """Tokenize (lowercase, alphanumeric runs) -> hash each token into a
    fixed-size term-frequency vector -> L2-normalize -> compare by cosine
    similarity. Uses hashlib (stable across processes/machines) rather than
    Python's built-in hash(), which is randomized per-process for strings —
    a randomized hash would silently break retrieval, since chunk embeddings
    are computed once at seed time and compared against query embeddings
    computed fresh in a later, separate process run."""
    name = "local"
    dim = 256

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> List[float]:
        vector = [0.0] * self.dim
        tokens = [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]
        for token in tokens:
            idx = int(hashlib.blake2b(token.encode("utf-8"), digest_size=4).hexdigest(), 16) % self.dim
            vector[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector


_PROVIDERS = {"local": LocalHashingEmbeddingProvider}


def get_embedding_provider(name: Optional[str] = None) -> BaseEmbeddingProvider:
    provider_name = (name or config.AI_EMBEDDING_PROVIDER or "local").strip().lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown AI_EMBEDDING_PROVIDER '{provider_name}'. Valid options: {', '.join(_PROVIDERS)}."
        )
    return provider_cls()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

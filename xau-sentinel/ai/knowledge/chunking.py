"""Fixed-size character chunker with overlap. Deliberately simple — no
sentence/paragraph-boundary detection — matching "local/simple development
implementation first" from the Stage 5 spec. Splitting on paragraph breaks
first (so a chunk doesn't open mid-thought when possible), then hard-wrapping
anything still oversized.
"""
import config


def chunk_text(text: str, size: int = None, overlap: int = None) -> list[str]:
    size = size if size is not None else config.AI_KNOWLEDGE_CHUNK_SIZE
    overlap = overlap if overlap is not None else config.AI_KNOWLEDGE_CHUNK_OVERLAP
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    step = max(1, size - overlap)
    while start < n:
        end = min(start + size, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start += step
    return chunks

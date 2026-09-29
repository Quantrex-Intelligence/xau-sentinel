"""Boundary-aware chunker. Still deliberately simple (no NLP dependency),
matching "local/simple development implementation first" from the Stage 5
spec, but a chunk never ends mid-sentence unless a single sentence is
itself longer than `size`.

Order of preference when packing text into chunks of at most `size`
characters:
1. whole paragraphs (split on blank lines), greedily packed together;
2. whole sentences, for a paragraph too long to fit on its own;
3. a hard word-boundary wrap with `overlap` characters of overlap, only for
   a single sentence longer than `size`.

VAL-039: the previous implementation cut on a fixed character window, so a
sentence (and the negation inside it — "do NOT trade ...") could land half
in one chunk and half in the next, and retrieval could return only the half
that reads as the opposite instruction. `overlap` now applies only to the
last-resort hard wrap; boundary-aligned chunks don't need it, since no
sentence is ever split between them.
"""
import re

import config

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _hard_wrap(text: str, size: int, overlap: int) -> list[str]:
    """Last resort for one sentence longer than `size`: cut on the last
    whitespace inside each window (a raw character cut only when a single
    word is longer than the window)."""
    pieces: list[str] = []
    step_back = max(0, min(overlap, size - 1))
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            space = text.rfind(" ", start + 1, end)
            if space > start:
                end = space
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= n:
            break
        next_start = end - step_back
        if step_back:
            # Start the overlap on a word boundary, never mid-word.
            space = text.find(" ", next_start, end)
            next_start = space + 1 if space != -1 else end
        start = max(next_start, start + 1)
    return pieces


def _units(paragraph: str, size: int, overlap: int) -> list[str]:
    """A paragraph that fits is one unit; otherwise each of its sentences
    is, with any oversized sentence hard-wrapped."""
    if len(paragraph) <= size:
        return [paragraph]
    units: list[str] = []
    for sentence in _SENTENCE_END.split(paragraph):
        sentence = sentence.strip()
        if not sentence:
            continue
        units.extend([sentence] if len(sentence) <= size else _hard_wrap(sentence, size, overlap))
    return units


def chunk_text(text: str, size: int = None, overlap: int = None) -> list[str]:
    size = size if size is not None else config.AI_KNOWLEDGE_CHUNK_SIZE
    overlap = overlap if overlap is not None else config.AI_KNOWLEDGE_CHUNK_OVERLAP
    size = max(1, size)
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    current = ""
    for paragraph in _PARAGRAPH_BREAK.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        # A new paragraph rejoins with a blank line; sentences split out of
        # one paragraph rejoin with a single space, their original separator.
        separator = "\n\n"
        for unit in _units(paragraph, size, overlap):
            candidate = f"{current}{separator}{unit}" if current else unit
            if len(candidate) <= size:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = unit
            separator = " "
    if current:
        chunks.append(current)
    return chunks

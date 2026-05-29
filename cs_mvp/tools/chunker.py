from __future__ import annotations

from dataclasses import dataclass

import tiktoken


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    source_id: str
    chunk_index: int
    char_start: int
    char_end: int
    text: str
    estimated_tokens: int


_ENCODER = tiktoken.get_encoding("cl100k_base")


def estimate_tokens(text: str) -> int:
    return len(_ENCODER.encode(text or ""))


def chunk_source(
    source_id: str,
    raw_text: str,
    chunk_tokens: int = 2000,
    overlap_tokens: int = 200,
    max_chunks: int = 4,
    inline_threshold_chars: int = 6000,
) -> list[TextChunk]:
    """Split one source into fixed-size chunks with paragraph-aware boundaries."""
    if not raw_text:
        return []

    if len(raw_text) <= inline_threshold_chars:
        return [
            TextChunk(
                chunk_id=f"{source_id}#chunk-00",
                source_id=source_id,
                chunk_index=0,
                char_start=0,
                char_end=len(raw_text),
                text=raw_text,
                estimated_tokens=estimate_tokens(raw_text),
            )
        ]

    chars_per_chunk = chunk_tokens * 4
    overlap_chars = overlap_tokens * 4
    chunks: list[TextChunk] = []
    cursor = 0

    while cursor < len(raw_text) and len(chunks) < max_chunks:
        end = min(cursor + chars_per_chunk, len(raw_text))
        boundary = _find_paragraph_boundary(raw_text, end, window=150)
        if boundary is not None and boundary > cursor + chars_per_chunk // 2:
            end = boundary

        chunk_text = raw_text[cursor:end].strip()
        if chunk_text:
            chunks.append(
                TextChunk(
                    chunk_id=f"{source_id}#chunk-{len(chunks):02d}",
                    source_id=source_id,
                    chunk_index=len(chunks),
                    char_start=cursor,
                    char_end=end,
                    text=chunk_text,
                    estimated_tokens=estimate_tokens(chunk_text),
                )
            )

        if end >= len(raw_text):
            break
        cursor = max(end - overlap_chars, cursor + 1)

    return chunks


def _find_paragraph_boundary(text: str, pos: int, window: int = 150) -> int | None:
    start = max(0, pos - window)
    end = min(len(text), pos + window)
    segment = text[start:end]
    relative_pos = pos - start

    before = segment.rfind("\n\n", 0, relative_pos)
    if before >= 0:
        return start + before + 2

    after = segment.find("\n\n", relative_pos)
    if after >= 0:
        return start + after + 2

    return None

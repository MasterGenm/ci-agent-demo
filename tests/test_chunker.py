from __future__ import annotations

from cs_mvp.tools.chunker import chunk_source


def test_chunk_short_text_returns_single_chunk() -> None:
    chunks = chunk_source("S-1", "short text " * 100)

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "S-1#chunk-00"
    assert chunks[0].chunk_index == 0


def test_chunk_long_text_respects_max_chunks() -> None:
    chunks = chunk_source("S-1", "long text " * 3000, max_chunks=4)

    assert len(chunks) <= 4


def test_chunk_overlap_present() -> None:
    chunks = chunk_source("S-1", "overlap text " * 3000, max_chunks=4)

    assert len(chunks) >= 2
    assert chunks[1].char_start < chunks[0].char_end


def test_chunk_aligns_to_paragraph_boundary() -> None:
    first = "a" * 7950
    second = "b" * 9000
    raw_text = f"{first}\n\n{second}"

    chunks = chunk_source(
        "S-1",
        raw_text,
        chunk_tokens=2000,
        overlap_tokens=200,
        max_chunks=2,
        inline_threshold_chars=1000,
    )

    assert chunks[0].char_end == len(first) + 2

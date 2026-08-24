"""Coverage for deterministic normalized-document chunking."""

from hashlib import sha256

from legal_chatbot.ingestion import (
    DeterministicChunker,
    IngestionSettings,
    NormalizedBlock,
    NormalizedDocument,
)


def _document(text: str, blocks: tuple[NormalizedBlock, ...]) -> NormalizedDocument:
    return NormalizedDocument(
        text=text,
        sha256=sha256(text.encode("utf-8")).hexdigest(),
        blocks=blocks,
        normalizer_version="html-v1",
    )


def test_chunker_uses_exact_offsets_hashes_overlap_and_block_boundaries() -> None:
    text = "A" * 100 + "B" * 100 + "C" * 100
    document = _document(
        text,
        (
            NormalizedBlock(kind="article", label="Article 1", text=text[:100], start=0, end=100),
            NormalizedBlock(kind="paragraph", text=text[100:200], start=100, end=200),
            NormalizedBlock(kind="paragraph", text=text[200:], start=200, end=300),
        ),
    )
    chunker = DeterministicChunker(
        IngestionSettings(INGESTION_CHUNK_MAX_CHARS=200, INGESTION_CHUNK_OVERLAP_CHARS=50)
    )

    chunks = chunker.chunk(document)

    assert [(chunk.start, chunk.end) for chunk in chunks] == [(0, 200), (150, 300)]
    assert [chunk.ordinal for chunk in chunks] == [0, 1]
    assert chunks[0].text[-50:] == chunks[1].text[:50]
    assert all(chunk.text == text[chunk.start : chunk.end] for chunk in chunks)
    assert all(
        chunk.content_sha256 == sha256(chunk.text.encode("utf-8")).hexdigest() for chunk in chunks
    )
    assert chunks[0].locator == {"kind": "article", "label": "Article 1"}
    assert chunks[0].chunker_version == "legal-block-v1"
    assert chunker.chunk(document) == chunks


def test_chunker_splits_oversized_blocks_and_always_advances_cursor() -> None:
    text = "x" * 450
    document = _document(
        text,
        (NormalizedBlock(kind="article", text=text, start=0, end=len(text)),),
    )
    chunker = DeterministicChunker(
        IngestionSettings(INGESTION_CHUNK_MAX_CHARS=200, INGESTION_CHUNK_OVERLAP_CHARS=50)
    )

    chunks = chunker.chunk(document)

    assert [(chunk.start, chunk.end) for chunk in chunks] == [(0, 200), (150, 350), (300, 450)]
    assert all(0 < len(chunk.text) <= 200 for chunk in chunks)
    assert all(left.start < right.start for left, right in zip(chunks, chunks[1:], strict=False))
    assert all(chunk.locator == {"kind": "article"} for chunk in chunks)


def test_chunker_returns_no_locator_without_source_structure() -> None:
    text = "plain text"
    document = _document(
        text,
        (NormalizedBlock(kind="paragraph", text=text, start=0, end=len(text)),),
    )

    chunk = DeterministicChunker(IngestionSettings()).chunk(document)[0]

    assert chunk.locator is None


def test_chunker_never_assigns_a_future_structural_locator() -> None:
    text = "a" * 400
    document = _document(
        text,
        (
            NormalizedBlock(kind="paragraph", text=text[:200], start=0, end=200),
            NormalizedBlock(kind="article", label="Article 2", text=text[200:], start=200, end=400),
        ),
    )
    chunker = DeterministicChunker(
        IngestionSettings(INGESTION_CHUNK_MAX_CHARS=200, INGESTION_CHUNK_OVERLAP_CHARS=0)
    )

    chunks = chunker.chunk(document)

    assert chunks[0].locator is None
    assert chunks[1].locator == {"kind": "article", "label": "Article 2"}

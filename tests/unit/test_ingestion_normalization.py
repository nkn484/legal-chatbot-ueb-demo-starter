"""Unit coverage for M04 ingestion contracts and HTML normalization only."""

from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError

from legal_chatbot.ingestion import (
    ChunkDraft,
    EmbeddingBatch,
    EmbeddingKind,
    HTMLNormalizer,
    IngestionOutcome,
    IngestionResult,
    IngestionSettings,
    NormalizedBlock,
)


def test_html_normalization_is_nfc_deterministic_and_preserves_block_offsets() -> None:
    html = """
        <div class="prov-chapter" data-label="Chương I">Chu\u031bo\u031bng I</div>
        <p>  Nội   dung &amp; căn cứ. </p>
        <div class="prov-article">Điều 1.  Phạm vi điều chỉnh.</div>
    """

    document = HTMLNormalizer().normalize(html)

    assert document.text == "Chương I\n\nNội dung & căn cứ.\n\nĐiều 1. Phạm vi điều chỉnh."
    assert document.sha256 == sha256(document.text.encode("utf-8")).hexdigest()
    assert [(block.kind, block.label, block.text) for block in document.blocks] == [
        ("chapter", "Chương I", "Chương I"),
        ("paragraph", None, "Nội dung & căn cứ."),
        ("article", None, "Điều 1. Phạm vi điều chỉnh."),
    ]
    assert all(document.text[block.start : block.end] == block.text for block in document.blocks)
    assert HTMLNormalizer().normalize(html) == document


def test_html_normalizer_ignores_executable_and_unrecognized_class_content() -> None:
    document = HTMLNormalizer().normalize(
        "<script>alert('x')</script><style>.x{display:none}</style>"
        "<noscript>fallback</noscript><p class='prov-article-copy'>Safe</p>"
    )

    assert document.text == "Safe"
    assert document.blocks[0].kind == "paragraph"
    assert document.blocks[0].label is None
    with pytest.raises(ValueError, match="no normalizable text"):
        HTMLNormalizer().normalize("<script>do_not_run()</script><style>x</style>")


def test_ingestion_settings_are_bounded_and_use_ingestion_aliases() -> None:
    settings = IngestionSettings(
        INGESTION_CHUNK_MAX_CHARS=800,
        INGESTION_CHUNK_OVERLAP_CHARS=200,
        ignored_setting="ignored",
    )

    assert settings.chunk_max_chars == 800
    assert settings.chunk_overlap_chars == 200
    assert settings.html_normalizer_version == "html-v1"
    assert settings.legal_block_version == "legal-block-v1"
    assert settings.embedding_model == "local-hash-v1"
    assert settings.embedding_dimension == 384
    assert settings.embedding_batch_size == 32
    with pytest.raises(ValidationError, match="less than"):
        IngestionSettings(INGESTION_CHUNK_MAX_CHARS=200, INGESTION_CHUNK_OVERLAP_CHARS=200)
    with pytest.raises(ValidationError):
        IngestionSettings(INGESTION_CHUNK_MAX_CHARS=8_001)


def test_ingestion_models_are_immutable_and_validate_hashes_and_batch_alignment() -> None:
    document_id, version_id = uuid4(), uuid4()
    block = NormalizedBlock(kind="paragraph", text="abc", start=0, end=3)
    draft = ChunkDraft(
        ordinal=0,
        text="abc",
        start=0,
        end=3,
        content_sha256=sha256(b"abc").hexdigest(),
        chunker_version="legal-block-v1",
    )
    batch = EmbeddingBatch(
        embedding_kind=EmbeddingKind.DEMO_NON_SEMANTIC,
        vectors=((1.0,) + tuple(0.0 for _ in range(383)),),
    )
    result = IngestionResult(
        document_id=document_id,
        document_version_id=version_id,
        version_number=1,
        outcome=IngestionOutcome.CREATED,
        block_count=1,
        chunk_count=1,
        embedding_count=1,
    )

    assert hash(block)
    assert hash(batch)
    assert draft.content_sha256 == sha256(b"abc").hexdigest()
    assert result.semantic_ready is False
    with pytest.raises(ValidationError, match="frozen"):
        block.text = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="nonzero"):
        EmbeddingBatch(vectors=(tuple(0.0 for _ in range(384)),))

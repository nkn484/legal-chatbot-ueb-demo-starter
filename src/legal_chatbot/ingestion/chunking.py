"""Deterministic chunking over canonical normalized-document offsets."""

from __future__ import annotations

from hashlib import sha256

from legal_chatbot.ingestion.config import IngestionSettings
from legal_chatbot.ingestion.models import ChunkDraft, NormalizedBlock, NormalizedDocument


class DeterministicChunker:
    """Split normalized text into bounded, overlapping, locator-addressable chunks."""

    def __init__(self, settings: IngestionSettings) -> None:
        self._settings = settings

    def chunk(self, document: NormalizedDocument) -> tuple[ChunkDraft, ...]:
        """Return stable chunks whose offsets resolve exactly into ``document.text``."""
        text = document.text
        chunks: list[ChunkDraft] = []
        start = 0

        while start < len(text):
            end = self._select_end(document, start)
            chunk_text = text[start:end]
            # The selected end is always beyond start; retain this guard if contracts evolve.
            if not chunk_text:
                raise RuntimeError("chunker failed to make cursor progress")
            chunks.append(
                ChunkDraft(
                    ordinal=len(chunks),
                    start=start,
                    end=end,
                    text=chunk_text,
                    content_sha256=sha256(chunk_text.encode("utf-8")).hexdigest(),
                    chunker_version=self._settings.legal_block_version,
                    locator=self._locator(document.blocks, start),
                )
            )
            if end == len(text):
                break
            next_start = end - self._settings.chunk_overlap_chars
            # A small boundary before the overlap must never cause an infinite loop.
            start = next_start if next_start > start else end

        return tuple(chunks)

    def _select_end(self, document: NormalizedDocument, start: int) -> int:
        """Choose the furthest eligible source block end, else a hard character split."""
        ceiling = min(start + self._settings.chunk_max_chars, len(document.text))
        preferred_ends = [
            block.end
            for block in document.blocks
            if start < block.end <= ceiling
            and (
                block.end == len(document.text)
                or block.end - self._settings.chunk_overlap_chars > start
            )
        ]
        return max(preferred_ends, default=ceiling)

    @staticmethod
    def _locator(blocks: tuple[NormalizedBlock, ...], position: int) -> dict[str, str] | None:
        """Use the latest declared structure at or before the chunk's source position."""
        structural = [
            block for block in blocks if block.kind != "paragraph" and block.start <= position
        ]
        if not structural:
            return None
        latest = max(structural, key=lambda block: block.start)
        locator = {"kind": latest.kind}
        if latest.label is not None:
            locator["label"] = latest.label
        return locator

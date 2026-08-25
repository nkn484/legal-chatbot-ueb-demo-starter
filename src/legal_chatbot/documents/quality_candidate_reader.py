"""Read-only Phase-B2 candidate lanes for quality-retrieval evaluation.

This adapter deliberately returns raw, per-lane child chunks.  It neither
collapses documents nor ranks/fuses candidates, and it never embeds a query.
"""

from __future__ import annotations

import json
from enum import StrEnum
from math import isfinite
from time import perf_counter
from typing import Any

from pydantic import model_validator
from sqlalchemy import String, and_, bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.fts_query import build_or_tsquery
from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    SourceProvenanceRecord,
)
from legal_chatbot.retrieval.quality_repair.models import (
    CandidateEvidence,
    DocumentIdentity,
    LaneObservation,
    ProvenanceType,
    RetrievalLane,
    SourceId,
    SourceScopeObservation,
    TransportTrustMode,
    _FrozenContract,
)
from legal_chatbot.retrieval.quality_repair.trace import BufferSummary, LaneMetrics, RejectionCount

_MAX_QUESTION_CHARS = 4_000
_MAX_DIAGNOSTIC_LIMIT = 50
_STRICT_PROVENANCE_TYPES = ("source_fetch", "manual_snapshot")
# The persisted profile contract is intentionally local to this evaluation adapter.
_E5_PROFILE_ID = "e5-small-384-mean-l2-prefix-v1"
_E5_DIMENSION = 384


class FTSQueryMode(StrEnum):
    """Evaluation-only FTS query construction modes; NATURAL remains the default."""

    NATURAL = "NATURAL"
    BOUNDED_OR = "BOUNDED_OR"


class QualityCandidateReadResult(_FrozenContract):
    """Content-free diagnostics and uncollapsed raw candidates from each lane."""

    lane_candidates: dict[RetrievalLane, tuple[CandidateEvidence, ...]]
    lane_metrics: tuple[LaneMetrics, ...]
    data_query_count: int
    explain_query_count: int
    query_count: int
    transaction_elapsed_ms: float
    requested_fts_query_mode: FTSQueryMode = FTSQueryMode.NATURAL
    applied_fts_query_mode: FTSQueryMode = FTSQueryMode.NATURAL
    fts_preparation_query_count: int = 0
    fts_preparation_elapsed_ms: float = 0.0
    bounded_or_selected_lexeme_count: int = 0
    bounded_or_source_lexeme_count: int = 0
    bounded_or_truncated: bool = False
    bounded_or_empty_query: bool = False
    bounded_or_natural_fallback_used: bool = False
    rejections: tuple[RejectionCount, ...] = ()

    @model_validator(mode="after")
    def validate_query_counts(self) -> QualityCandidateReadResult:
        if self.data_query_count < 0 or self.explain_query_count < 0:
            raise ValueError("query counts must be nonnegative")
        if self.query_count != self.data_query_count + self.explain_query_count:
            raise ValueError("query_count must equal data_query_count plus explain_query_count")
        if self.fts_preparation_query_count not in (0, 1):
            raise ValueError("fts_preparation_query_count must be zero or one")
        if self.fts_preparation_query_count > self.data_query_count:
            raise ValueError("fts_preparation_query_count cannot exceed data_query_count")
        if (
            not isfinite(self.fts_preparation_elapsed_ms)
            or self.fts_preparation_elapsed_ms < 0
        ):
            raise ValueError("fts_preparation_elapsed_ms must be finite and nonnegative")
        if self.fts_preparation_query_count == 0 and self.fts_preparation_elapsed_ms != 0:
            raise ValueError("fts_preparation_elapsed_ms requires a preparation query")
        if self.requested_fts_query_mode is FTSQueryMode.NATURAL:
            if self.applied_fts_query_mode is not FTSQueryMode.NATURAL:
                raise ValueError("NATURAL reads must apply NATURAL mode")
            if (
                self.fts_preparation_query_count != 0
                or self.fts_preparation_elapsed_ms != 0
                or self.bounded_or_selected_lexeme_count != 0
                or self.bounded_or_source_lexeme_count != 0
                or self.bounded_or_truncated
                or self.bounded_or_empty_query
                or self.bounded_or_natural_fallback_used
            ):
                raise ValueError("NATURAL reads must report zero bounded-OR preparation and shape")
        else:
            if self.applied_fts_query_mode is not FTSQueryMode.BOUNDED_OR:
                raise ValueError("BOUNDED_OR reads must fail closed without a NATURAL fallback")
            if self.fts_preparation_query_count != 1:
                raise ValueError("BOUNDED_OR reads must report one preparation query")
            if not 0 <= self.bounded_or_selected_lexeme_count <= 32:
                raise ValueError("bounded_or_selected_lexeme_count must be between 0 and 32")
            if self.bounded_or_source_lexeme_count < self.bounded_or_selected_lexeme_count:
                raise ValueError("bounded-OR source lexeme count cannot be below selected count")
            if self.bounded_or_truncated != (
                self.bounded_or_source_lexeme_count > self.bounded_or_selected_lexeme_count
            ):
                raise ValueError("bounded-OR truncation must match its lexeme counts")
            if self.bounded_or_empty_query != (self.bounded_or_source_lexeme_count == 0):
                raise ValueError("bounded-OR empty-query state must match its source lexeme count")
            if self.bounded_or_natural_fallback_used:
                raise ValueError("BOUNDED_OR reads must not use a NATURAL fallback")
        return self

    def to_public_dict(self) -> dict[str, object]:
        """Serialize diagnostics without private chunk, document, or provenance fields."""

        return {
            "lane_candidates": {
                lane.value: [candidate.to_public_dict() for candidate in candidates]
                for lane, candidates in self.lane_candidates.items()
            },
            "lane_metrics": [metric.model_dump(mode="json") for metric in self.lane_metrics],
            "data_query_count": self.data_query_count,
            "explain_query_count": self.explain_query_count,
            "query_count": self.query_count,
            "transaction_elapsed_ms": self.transaction_elapsed_ms,
            "requested_fts_query_mode": self.requested_fts_query_mode.value,
            "applied_fts_query_mode": self.applied_fts_query_mode.value,
            "fts_preparation_query_count": self.fts_preparation_query_count,
            "fts_preparation_elapsed_ms": self.fts_preparation_elapsed_ms,
            "bounded_or_selected_lexeme_count": self.bounded_or_selected_lexeme_count,
            "bounded_or_source_lexeme_count": self.bounded_or_source_lexeme_count,
            "bounded_or_truncated": self.bounded_or_truncated,
            "bounded_or_empty_query": self.bounded_or_empty_query,
            "bounded_or_natural_fallback_used": self.bounded_or_natural_fallback_used,
            "rejections": [rejection.model_dump(mode="json") for rejection in self.rejections],
        }


class PostgresQualityCandidateReader:
    """Evaluation-only PostgreSQL reader with exact semantic and controlled FTS lanes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def read_candidates(
        self,
        question: str,
        active_source_ids: tuple[str, ...],
        query_vector: tuple[float, ...],
        diagnostic_limit: int = _MAX_DIAGNOSTIC_LIMIT,
        explain: bool = False,
        fts_query_mode: FTSQueryMode | str = FTSQueryMode.NATURAL,
    ) -> QualityCandidateReadResult:
        """Read bounded raw candidates in one read-only repeatable-read transaction."""

        sources = self._validate_sources(active_source_ids)
        self._validate_question(question)
        self._validate_vector(query_vector)
        fts_query_mode = self._validate_fts_query_mode(fts_query_mode)
        if (
            not isinstance(diagnostic_limit, int)
            or not 1 <= diagnostic_limit <= _MAX_DIAGNOSTIC_LIMIT
        ):
            raise ValueError("diagnostic_limit must be between 1 and 50")
        if not isinstance(explain, bool):
            raise ValueError("explain must be a boolean")

        started = perf_counter()
        data_query_count = 0
        explain_query_count = 0
        fts_preparation_query_count = 0
        fts_preparation_elapsed = 0.0
        bounded_or_selected_lexeme_count = 0
        bounded_or_source_lexeme_count = 0
        bounded_or_truncated = False
        bounded_or_empty_query = False
        rejections: list[RejectionCount] = []
        async with self._session_factory() as session:
            async with session.begin():
                # This must be the first database statement in the transaction.
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )

                semantic_statement = self._semantic_statement(
                    sources, query_vector, diagnostic_limit
                )
                await session.execute(text("SET LOCAL enable_indexscan = off"))
                await session.execute(text("SET LOCAL enable_bitmapscan = off"))
                semantic_buffers = BufferSummary()
                try:
                    semantic_rows, semantic_elapsed = await self._execute(
                        session, semantic_statement
                    )
                    if explain:
                        semantic_buffers = await self._explain_buffers(session, semantic_statement)
                finally:
                    # Restore before either FTS lane; SET statements are not logical data queries.
                    await session.execute(text("SET LOCAL enable_indexscan = on"))
                    await session.execute(text("SET LOCAL enable_bitmapscan = on"))
                data_query_count += 1
                if explain:
                    explain_query_count += 1

                fts_params: dict[str, object] = {"question": question}
                if fts_query_mode is FTSQueryMode.BOUNDED_OR:
                    preparation_statement = select(
                        func.websearch_to_tsquery(
                            text("'pg_catalog.simple'::regconfig"), bindparam("question")
                        )
                        .cast(String)
                        .label("natural_tsquery_text")
                    )
                    preparation_rows, fts_preparation_elapsed = await self._execute(
                        session, preparation_statement, {"question": question}
                    )
                    natural_tsquery_text = preparation_rows[0][0]
                    if not isinstance(natural_tsquery_text, str):
                        raise RuntimeError("PostgreSQL did not return a natural tsquery text value")
                    (
                        or_tsquery,
                        bounded_or_source_lexeme_count,
                        bounded_or_truncated,
                    ) = build_or_tsquery(natural_tsquery_text)
                    bounded_or_selected_lexeme_count = min(
                        bounded_or_source_lexeme_count, 32
                    )
                    bounded_or_empty_query = bounded_or_source_lexeme_count == 0
                    fts_params = {"or_tsquery": or_tsquery}
                    data_query_count += 1
                    fts_preparation_query_count = 1

                content_statement = self._content_statement(
                    sources, diagnostic_limit, fts_query_mode
                )
                content_rows, content_elapsed = await self._execute(
                    session, content_statement, fts_params
                )
                data_query_count += 1
                content_buffers = BufferSummary()
                if explain:
                    content_buffers = await self._explain_buffers(
                        session, content_statement, fts_params
                    )
                    explain_query_count += 1

                title_statement = self._title_statement(sources, diagnostic_limit, fts_query_mode)
                title_rows, title_elapsed = await self._execute(
                    session, title_statement, fts_params
                )
                data_query_count += 1
                title_buffers = BufferSummary()
                if explain:
                    title_buffers = await self._explain_buffers(
                        session, title_statement, fts_params
                    )
                    explain_query_count += 1

                title_candidates: tuple[CandidateEvidence, ...] = ()
                title_query_count = 1 + int(explain)
                if title_rows:
                    title_scores = {
                        row[0]: (rank, float(row[1]))
                        for rank, row in enumerate(title_rows, start=1)
                    }
                    support_statement = self._title_support_statement(
                        sources, query_vector, tuple(title_scores), diagnostic_limit
                    )
                    await session.execute(text("SET LOCAL enable_indexscan = off"))
                    await session.execute(text("SET LOCAL enable_bitmapscan = off"))
                    support_buffers = BufferSummary()
                    try:
                        support_rows, support_elapsed = await self._execute(
                            session, support_statement
                        )
                        if explain:
                            support_buffers = await self._explain_buffers(
                                session, support_statement
                            )
                    finally:
                        await session.execute(text("SET LOCAL enable_indexscan = on"))
                        await session.execute(text("SET LOCAL enable_bitmapscan = on"))
                    title_elapsed += support_elapsed
                    data_query_count += 1
                    title_query_count += 1
                    if explain:
                        title_buffers = self._add_buffers(title_buffers, support_buffers)
                        explain_query_count += 1
                        title_query_count += 1
                    title_candidates = self._candidates(
                        support_rows,
                        RetrievalLane.TITLE_FTS,
                        title_query_count,
                        title_elapsed,
                        len(support_rows),
                        scores=title_scores,
                    )
                    missing_support = len(title_rows) - len(support_rows)
                    if missing_support:
                        rejections.append(
                            RejectionCount(code="TITLE_NO_SUPPORTING_CHUNK", count=missing_support)
                        )

        semantic_candidates = self._candidates(
            semantic_rows,
            RetrievalLane.SEMANTIC,
            1,
            semantic_elapsed,
            len(semantic_rows),
        )
        content_candidates = self._candidates(
            content_rows,
            RetrievalLane.CONTENT_FTS,
            1,
            content_elapsed,
            len(content_rows),
        )
        metrics = (
            LaneMetrics(
                lane=RetrievalLane.SEMANTIC,
                query_count=1 + int(explain),
                elapsed_ms=semantic_elapsed,
                sql_elapsed_ms=semantic_elapsed,
                rows_returned=len(semantic_rows),
                buffers=semantic_buffers,
            ),
            LaneMetrics(
                lane=RetrievalLane.CONTENT_FTS,
                query_count=1 + int(explain),
                elapsed_ms=content_elapsed,
                sql_elapsed_ms=content_elapsed,
                rows_returned=len(content_rows),
                buffers=content_buffers,
            ),
            LaneMetrics(
                lane=RetrievalLane.TITLE_FTS,
                query_count=title_query_count,
                elapsed_ms=title_elapsed,
                sql_elapsed_ms=title_elapsed,
                rows_returned=len(title_candidates),
                buffers=title_buffers,
            ),
        )
        return QualityCandidateReadResult(
            lane_candidates={
                RetrievalLane.SEMANTIC: semantic_candidates,
                RetrievalLane.CONTENT_FTS: content_candidates,
                RetrievalLane.TITLE_FTS: title_candidates,
            },
            lane_metrics=metrics,
            data_query_count=data_query_count,
            explain_query_count=explain_query_count,
            query_count=data_query_count + explain_query_count,
            transaction_elapsed_ms=(perf_counter() - started) * 1_000,
            requested_fts_query_mode=fts_query_mode,
            applied_fts_query_mode=fts_query_mode,
            fts_preparation_query_count=fts_preparation_query_count,
            fts_preparation_elapsed_ms=fts_preparation_elapsed,
            bounded_or_selected_lexeme_count=bounded_or_selected_lexeme_count,
            bounded_or_source_lexeme_count=bounded_or_source_lexeme_count,
            bounded_or_truncated=bounded_or_truncated,
            bounded_or_empty_query=bounded_or_empty_query,
            bounded_or_natural_fallback_used=False,
            rejections=tuple(rejections),
        )

    @staticmethod
    async def _execute(
        session: AsyncSession, statement: Any, params: dict[str, object] | None = None
    ) -> tuple[list[Any], float]:
        started = perf_counter()
        result = await session.execute(statement, params)
        return list(result.all()), (perf_counter() - started) * 1_000

    async def _explain_buffers(
        self, session: AsyncSession, statement: Any, params: dict[str, object] | None = None
    ) -> BufferSummary:
        """Run controlled JSON EXPLAIN without exposing SQL, parameters, or its plan."""

        dialect = session.bind.dialect if session.bind is not None else None
        if dialect is None:
            raise RuntimeError("PostgreSQL session is not bound")
        bound_statement = statement.params(**params) if params else statement
        compiled = bound_statement.compile(
            dialect=dialect, compile_kwargs={"render_postcompile": True}
        )
        bound_params = dict(compiled.params)
        values = []
        for name in compiled.positiontup or ():
            value = bound_params[name]
            processor = compiled._bind_processors.get(name)
            values.append(processor(value) if processor is not None else value)
        connection = await session.connection()
        result = await connection.exec_driver_sql(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}", tuple(values)
        )
        payload = result.scalar_one()
        return self._buffer_summary(payload)

    @staticmethod
    def _buffer_summary(payload: object) -> BufferSummary:
        """Extract only root plan block counters; child nodes would double-count totals."""

        root: object = payload
        if isinstance(payload, str):
            try:
                root = json.loads(payload)
            except json.JSONDecodeError:
                return BufferSummary()
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            root = payload[0].get("Plan", {})
        if not isinstance(root, dict):
            return BufferSummary()
        return BufferSummary(
            shared_hit=int(root.get("Shared Hit Blocks", 0) or 0),
            shared_read=int(root.get("Shared Read Blocks", 0) or 0),
            temp_read=int(root.get("Temp Read Blocks", 0) or 0),
            temp_written=int(root.get("Temp Written Blocks", 0) or 0),
        )

    @staticmethod
    def _add_buffers(first: BufferSummary, second: BufferSummary) -> BufferSummary:
        return BufferSummary(
            shared_hit=first.shared_hit + second.shared_hit,
            shared_read=first.shared_read + second.shared_read,
            temp_read=first.temp_read + second.temp_read,
            temp_written=first.temp_written + second.temp_written,
        )

    @staticmethod
    def _latest_version():
        return (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == LegalDocument.id)
            .correlate(LegalDocument)
            .scalar_subquery()
        )

    @staticmethod
    def _selected_provenance_id():
        return (
            select(SourceProvenanceRecord.id)
            .where(
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                SourceProvenanceRecord.source_id == LegalDocument.source_id,
                SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
                SourceProvenanceRecord.provenance_type.in_(_STRICT_PROVENANCE_TYPES),
            )
            .order_by(SourceProvenanceRecord.retrieved_at.asc(), SourceProvenanceRecord.id.asc())
            .limit(1)
            .correlate(DocumentVersion, LegalDocument)
            .scalar_subquery()
        )

    @classmethod
    def _eligible_statement(cls, sources: tuple[str, ...]):
        provenance_id = cls._selected_provenance_id()
        return provenance_id, (
            LegalDocument.source_id.in_(sources),
            DocumentVersion.version_number == cls._latest_version(),
            provenance_id.is_not(None),
        )

    @staticmethod
    def _identity_columns(score: Any):
        return (
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.ordinal.label("ordinal"),
            LegalDocument.id.label("document_id"),
            DocumentVersion.id.label("document_version_id"),
            LegalDocument.source_id.label("source_id"),
            LegalDocument.external_id.label("external_id"),
            DocumentVersion.document_number_normalized.label("document_number_normalized"),
            DocumentVersion.title.label("title"),
            DocumentVersion.version_number.label("version_number"),
            DocumentVersion.document_type.label("document_type"),
            DocumentVersion.issuing_authority.label("issuing_authority"),
            DocumentVersion.legal_status.label("legal_status"),
            SourceProvenanceRecord.id.label("provenance_record_id"),
            SourceProvenanceRecord.provenance_type.label("provenance_type"),
            SourceProvenanceRecord.transport_trust_mode.label("transport_trust_mode"),
            score.label("lane_score"),
        )

    @classmethod
    def _semantic_statement(
        cls, sources: tuple[str, ...], vector: tuple[float, ...], limit: int
    ) -> Any:
        provenance_id, predicates = cls._eligible_statement(sources)
        distance = ChunkEmbedding.embedding.cosine_distance(list(vector))
        return (
            select(*cls._identity_columns(1 - distance))
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(
                ChunkEmbedding,
                and_(
                    ChunkEmbedding.document_chunk_id == DocumentChunk.id,
                    ChunkEmbedding.embedding_model_id == _E5_PROFILE_ID,
                    ChunkEmbedding.embedding_kind == "semantic",
                    ChunkEmbedding.dimension == _E5_DIMENSION,
                ),
            )
            .join(SourceProvenanceRecord, SourceProvenanceRecord.id == provenance_id)
            .where(*predicates)
            .order_by(distance.asc(), DocumentChunk.id.asc())
            .limit(limit)
        )

    @staticmethod
    def _fts_query(fts_query_mode: FTSQueryMode) -> Any:
        if fts_query_mode is FTSQueryMode.NATURAL:
            return func.websearch_to_tsquery(
                text("'pg_catalog.simple'::regconfig"), bindparam("question")
            )
        if fts_query_mode is FTSQueryMode.BOUNDED_OR:
            return func.to_tsquery(
                text("'pg_catalog.simple'::regconfig"), bindparam("or_tsquery")
            )
        raise ValueError("fts_query_mode must be NATURAL or BOUNDED_OR")

    @classmethod
    def _content_statement(
        cls,
        sources: tuple[str, ...],
        limit: int,
        fts_query_mode: FTSQueryMode = FTSQueryMode.NATURAL,
    ) -> Any:
        provenance_id, predicates = cls._eligible_statement(sources)
        query = cls._fts_query(fts_query_mode)
        score = func.ts_rank_cd(DocumentChunk.search_vector, query)
        return (
            select(*cls._identity_columns(score))
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(SourceProvenanceRecord, SourceProvenanceRecord.id == provenance_id)
            .where(*predicates, DocumentChunk.search_vector.op("@@")(query))
            .order_by(score.desc(), DocumentChunk.id.asc())
            .limit(limit)
        )

    @classmethod
    def _title_statement(
        cls,
        sources: tuple[str, ...],
        limit: int,
        fts_query_mode: FTSQueryMode = FTSQueryMode.NATURAL,
    ) -> Any:
        provenance_id, predicates = cls._eligible_statement(sources)
        query = cls._fts_query(fts_query_mode)
        score = func.ts_rank_cd(DocumentVersion.title_search_vector, query)
        return (
            select(DocumentVersion.id, score.label("title_score"))
            .select_from(DocumentVersion)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(SourceProvenanceRecord, SourceProvenanceRecord.id == provenance_id)
            .where(*predicates, DocumentVersion.title_search_vector.op("@@")(query))
            .order_by(score.desc(), DocumentVersion.id.asc())
            .limit(limit)
        )

    @classmethod
    def _title_support_statement(
        cls,
        sources: tuple[str, ...],
        vector: tuple[float, ...],
        title_version_ids: tuple[object, ...],
        limit: int,
    ) -> Any:
        provenance_id, predicates = cls._eligible_statement(sources)
        distance = ChunkEmbedding.embedding.cosine_distance(list(vector))
        support_rank = (
            func.row_number()
            .over(
                partition_by=DocumentVersion.id, order_by=(distance.asc(), DocumentChunk.id.asc())
            )
            .label("support_rank")
        )
        ranked = (
            select(*cls._identity_columns(1 - distance), support_rank)
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(
                ChunkEmbedding,
                and_(
                    ChunkEmbedding.document_chunk_id == DocumentChunk.id,
                    ChunkEmbedding.embedding_model_id == _E5_PROFILE_ID,
                    ChunkEmbedding.embedding_kind == "semantic",
                    ChunkEmbedding.dimension == _E5_DIMENSION,
                ),
            )
            .join(SourceProvenanceRecord, SourceProvenanceRecord.id == provenance_id)
            .where(*predicates, DocumentVersion.id.in_(title_version_ids))
            .cte("title_support")
        )
        columns = [ranked.c[column.name] for column in ranked.c if column.name != "support_rank"]
        return (
            select(*columns)
            .where(ranked.c.support_rank == 1)
            .order_by(ranked.c.document_version_id.asc())
            .limit(limit)
        )

    @staticmethod
    def _candidates(
        rows: list[Any],
        lane: RetrievalLane,
        query_count: int,
        elapsed_ms: float,
        rows_returned: int,
        *,
        scores: dict[object, tuple[int, float]] | None = None,
    ) -> tuple[CandidateEvidence, ...]:
        candidates: list[CandidateEvidence] = []
        for rank, row in enumerate(rows, start=1):
            observation_rank, score = (
                scores[row[3]] if scores is not None else (rank, float(row[15]))
            )
            supporting_semantic_score = (
                float(row[15])
                if lane in (RetrievalLane.SEMANTIC, RetrievalLane.TITLE_FTS)
                else None
            )
            candidates.append(
                CandidateEvidence(
                    chunk_id=row[0],
                    identity=DocumentIdentity(
                        document_id=row[2],
                        document_version_id=row[3],
                        source_id=SourceId(row[4]),
                        external_id=row[5],
                        document_number_normalized=row[6],
                        title=row[7],
                        version_number=row[8],
                        document_type=row[9],
                        issuing_authority=row[10],
                        legal_status=row[11],
                        provenance_record_id=row[12],
                        provenance_type=ProvenanceType(row[13]),
                        transport_trust_mode=TransportTrustMode(row[14]),
                        latest_ingested=True,
                    ),
                    ordinal=row[1],
                    observations=(
                        LaneObservation(
                            lane=lane,
                            rank=observation_rank,
                            score=score,
                            query_count=query_count,
                            elapsed_ms=elapsed_ms,
                            rows_returned=rows_returned,
                        ),
                    ),
                    supporting_semantic_score=supporting_semantic_score,
                    source_scope=SourceScopeObservation.NONE,
                    eligible=True,
                )
            )
        return tuple(candidates)

    @staticmethod
    def _validate_question(question: str) -> None:
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question) > _MAX_QUESTION_CHARS
        ):
            raise ValueError("question must be nonblank and at most 4000 characters")

    @staticmethod
    def _validate_fts_query_mode(fts_query_mode: FTSQueryMode | str) -> FTSQueryMode:
        try:
            return FTSQueryMode(fts_query_mode)
        except (TypeError, ValueError) as error:
            raise ValueError("fts_query_mode must be NATURAL or BOUNDED_OR") from error

    @staticmethod
    def _validate_vector(vector: tuple[float, ...]) -> None:
        if (
            not isinstance(vector, tuple)
            or len(vector) != _E5_DIMENSION
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
                for value in vector
            )
        ):
            raise ValueError("query_vector must contain 384 finite numeric values")

    @staticmethod
    def _validate_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {source.value for source in SourceId}
        if (
            not isinstance(sources, tuple)
            or not 1 <= len(sources) <= 3
            or len(set(sources)) != len(sources)
            or any(not isinstance(source, str) or source not in allowed for source in sources)
        ):
            raise ValueError("active_source_ids must be a unique tuple of registry source IDs")
        return sources

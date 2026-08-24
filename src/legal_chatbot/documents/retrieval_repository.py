"""PostgreSQL lexical retrieval persistence adapter."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

from sqlalchemy import and_, bindparam, case, func, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.core.logging import get_logger
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.retrieval.errors import RetrievalError, RetrievalErrorCode
from legal_chatbot.retrieval.models import (
    LEXICAL_STRATEGY,
    LEXICAL_STRATEGY_VERSION,
    QUERY_MAX_CHARS,
    RetrievalCandidate,
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
    RetrievalScope,
    RetrievalTrustScope,
    eligible_transport_trust_modes,
    is_evidence_provenance_eligible,
)
from legal_chatbot.sources.models import ProvenanceType, TransportTrustMode

_PLANNED_LEXICAL_STRATEGY_VERSION = "v2_planned"
_REPAIR_LEXICAL_STRATEGY_VERSION = "v3_lexical_repair"
_REPAIR_PLANNED_LEXICAL_STRATEGY_VERSION = "v3_lexical_repair_planned"
_RRF_RANK_CONSTANT = 60
_MAX_ACTIVE_SOURCE_IDS = 3
_MAX_SOURCE_ID_CHARS = 32
_MAX_REPAIR_PHRASES = 2
_MIN_REPAIR_PHRASE_TOKENS = 2
_MAX_REPAIR_PHRASE_TOKENS = 5
_MAX_METADATA_DOCUMENT_IDS = 2
_LOW_SIGNAL_REPAIR_PHRASES = frozenset({"quy định", "văn bản"})
_REPAIR_FUNCTION_WORDS = frozenset(
    {
        "ai",
        "anh",
        "chị",
        "cho",
        "có",
        "của",
        "đã",
        "để",
        "được",
        "em",
        "gì",
        "giúp",
        "hỏi",
        "không",
        "là",
        "lòng",
        "mình",
        "nào",
        "như",
        "ở",
        "tôi",
        "thế",
        "theo",
        "và",
        "về",
        "với",
        "xin",
        "bạn",
        "hãy",
    }
)
_REPAIR_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_DOCUMENT_NUMBER_PATTERN = re.compile(
    r"(?<![\w/])\d{1,6}/(?:\d{2,4}/)?[A-Za-zÀ-ỹĐđ][\wÀ-ỹĐđ-]{1,31}(?![\w/])",
    re.UNICODE,
)
_REPAIR_CLAUSE_BOUNDARY_PATTERN = re.compile(r"[,;.!?—–-]+")
_UNSAFE_REPAIR_PATTERN = re.compile(r"(?:https?://|www\.|[&|!():*<>\\@])", re.IGNORECASE)


def compile_lexical_repair_query(question: str) -> str | None:
    """Compile at most two safe, user-derived phrase searches, or fail closed.

    This deliberately performs no expansion, synonym lookup, or metadata synthesis.
    """

    normalized = unicodedata.normalize("NFC", question)
    if not normalized or _UNSAFE_REPAIR_PATTERN.search(normalized):
        return None
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        return None

    # Document numbers and dates belong only to metadata identification; never make
    # their way into a content repair phrase.
    without_identifiers = _DOCUMENT_NUMBER_PATTERN.sub(" ", normalized)
    without_dates = re.sub(r"(?<!\d)\d{1,2}[/-]\d{1,2}[/-]\d{2,4}(?!\d)", " ", without_identifiers)
    candidates: list[tuple[str, int, int]] = []
    position = 0
    for clause in _REPAIR_CLAUSE_BOUNDARY_PATTERN.split(without_dates):
        current_run: list[str] = []
        run_position = position
        for token in _REPAIR_TOKEN_PATTERN.findall(clause):
            if token.casefold() in _REPAIR_FUNCTION_WORDS:
                if len(current_run) >= _MIN_REPAIR_PHRASE_TOKENS:
                    phrase_tokens = current_run[:_MAX_REPAIR_PHRASE_TOKENS]
                    candidates.append((" ".join(phrase_tokens), len(phrase_tokens), run_position))
                current_run = []
                run_position = position + 1
            else:
                if not current_run:
                    run_position = position
                current_run.append(token)
            position += 1
        if len(current_run) >= _MIN_REPAIR_PHRASE_TOKENS:
            phrase_tokens = current_run[:_MAX_REPAIR_PHRASE_TOKENS]
            candidates.append((" ".join(phrase_tokens), len(phrase_tokens), run_position))
        position += 1

    if any(phrase.casefold() not in _LOW_SIGNAL_REPAIR_PHRASES for phrase, _, _ in candidates):
        candidates = [
            candidate
            for candidate in candidates
            if candidate[0].casefold() not in _LOW_SIGNAL_REPAIR_PHRASES
        ]
    phrases = [
        phrase
        for phrase, _, _ in sorted(candidates, key=lambda candidate: (-candidate[1], candidate[2]))[
            :_MAX_REPAIR_PHRASES
        ]
    ]
    if not phrases:
        return None
    return " OR ".join(f'"{phrase}"' for phrase in phrases)


def _extract_document_numbers(question: str) -> tuple[str, ...]:
    """Extract at most two exact user-supplied identifiers for metadata scoping."""

    normalized = unicodedata.normalize("NFC", question)
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        return ()
    numbers: list[str] = []
    for match in _DOCUMENT_NUMBER_PATTERN.finditer(normalized):
        number = match.group(0).casefold()
        if number not in numbers:
            numbers.append(number)
        if len(numbers) == _MAX_METADATA_DOCUMENT_IDS:
            break
    return tuple(numbers)


@dataclass(frozen=True)
class _CandidateRow:
    """Private projection used to validate evidence before it is written."""

    document_chunk_id: UUID
    document_version_id: UUID
    source_provenance_record_id: UUID | None
    source_provenance_document_version_id: UUID | None
    lexical_score: float | None
    provenance_type: ProvenanceType = ProvenanceType.SOURCE_FETCH
    transport_trust_mode: TransportTrustMode = TransportTrustMode.STRICT_TLS
    semantic_score: float | None = None


class PostgresLexicalRetrievalRepository:
    """Retrieve current document chunks and persist their immutable citations."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        active_source_ids: tuple[str, ...],
        lexical_repair_enabled: bool = False,
    ) -> None:
        """Bind this repository to an explicit bounded server-owned source set."""

        self._session_factory = session_factory
        self._active_source_ids = self._validate_active_source_ids(active_source_ids)
        self._lexical_repair_enabled = lexical_repair_enabled
        self._logger = get_logger()

    async def retrieve_and_persist(self, request: RetrievalRequest) -> RetrievalResult:
        """Run the bounded lexical policy and commit its result as one unit of work."""

        strategy_version = LEXICAL_STRATEGY_VERSION
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    # This must remain the first SQL statement in this transaction.
                    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                    raw_candidates = await self._retrieve_candidates(session, request)
                    repair_candidates: tuple[_CandidateRow, ...] = ()
                    if self._lexical_repair_enabled:
                        strategy_version = _REPAIR_LEXICAL_STRATEGY_VERSION
                        repair_query = compile_lexical_repair_query(request.query)
                        metadata_document_ids = await self._identify_metadata_document_ids(
                            session, question=request.query, repair_query=repair_query,
                            trust_scope=request.trust_scope,
                        )
                        repair_candidates = await self._retrieve_repair_candidates(
                            session, request, repair_query, metadata_document_ids
                        )
                    expansion_candidates: tuple[_CandidateRow, ...] = ()
                    if request.expansion_query is not None:
                        try:
                            async with session.begin_nested():
                                expansion_candidates = await self._retrieve_expansion_candidates(
                                    session, request
                                )
                            strategy_version = (
                                _REPAIR_PLANNED_LEXICAL_STRATEGY_VERSION
                                if self._lexical_repair_enabled
                                else _PLANNED_LEXICAL_STRATEGY_VERSION
                            )
                        except Exception:
                            # The nested transaction has rolled back only the optional search.
                            # Do not log query or planner content while falling back to original.
                            expansion_candidates = ()
                    candidates = self._fuse_candidates(
                        raw_candidates, repair_candidates, expansion_candidates, request.top_k
                    )
                    if not candidates:
                        result = await self._persist_result(
                            session,
                            request,
                            (),
                            RetrievalDecision.NO_RESULTS,
                            RetrievalReason.NO_LEXICAL_MATCH,
                            strategy_version,
                        )
                    elif not self._has_valid_chain(candidates, request.trust_scope):
                        result = await self._persist_result(
                            session,
                            request,
                            (),
                            RetrievalDecision.INVALID_EVIDENCE_CHAIN,
                            RetrievalReason.INVALID_EVIDENCE_CHAIN,
                            strategy_version,
                        )
                    else:
                        result = await self._persist_result(
                            session,
                            request,
                            candidates,
                            RetrievalDecision.EVIDENCE_AVAILABLE,
                            RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE,
                            strategy_version,
                        )
        except RetrievalError as error:
            self._log_failure(request, error.code, strategy_version)
            raise
        except Exception:
            error = RetrievalError(RetrievalErrorCode.PERSISTENCE_FAILURE)
            self._log_failure(request, error.code, strategy_version)
            raise error from None

        self._log_complete(request, result, strategy_version)
        return result

    async def persist_zero_evidence_run(
        self,
        request: RetrievalRequest,
        decision: RetrievalDecision,
        reason: RetrievalReason,
    ) -> RetrievalResult:
        """Persist a caller-selected zero-evidence outcome without searching."""

        strategy_version = LEXICAL_STRATEGY_VERSION
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    result = await self._persist_result(
                        session, request, (), decision, reason, strategy_version
                    )
        except RetrievalError as error:
            self._log_failure(request, error.code, strategy_version)
            raise
        except Exception:
            error = RetrievalError(RetrievalErrorCode.PERSISTENCE_FAILURE)
            self._log_failure(request, error.code, strategy_version)
            raise error from None

        self._log_complete(request, result, strategy_version)
        return result

    async def _retrieve_candidates(
        self, session: AsyncSession, request: RetrievalRequest
    ) -> tuple[_CandidateRow, ...]:
        """Run the required original query first without any document restriction."""

        return await self._select_candidates(
            session,
            query=request.query,
            candidate_limit=self._candidate_limit(request.top_k),
            trust_scope=request.trust_scope,
        )

    async def _retrieve_expansion_candidates(
        self, session: AsyncSession, request: RetrievalRequest
    ) -> tuple[_CandidateRow, ...]:
        """Run at most one server-scoped optional expansion search."""

        expansion_query = request.expansion_query
        if expansion_query is None:
            return ()
        return await self._select_candidates(
            session,
            query=expansion_query,
            candidate_limit=self._candidate_limit(request.top_k),
            document_ids=request.expansion_document_ids or None,
            trust_scope=request.trust_scope,
        )

    async def _retrieve_repair_candidates(
        self,
        session: AsyncSession,
        request: RetrievalRequest,
        repair_query: str | None,
        metadata_document_ids: tuple[UUID, ...],
    ) -> tuple[_CandidateRow, ...]:
        """Search only user-derived repair phrases, optionally within metadata scope."""

        if repair_query is None:
            return ()
        return await self._select_candidates(
            session,
            query=repair_query,
            candidate_limit=self._candidate_limit(request.top_k),
            document_ids=metadata_document_ids or None,
            trust_scope=request.trust_scope,
        )

    @staticmethod
    def _candidate_limit(top_k: int) -> int:
        """Bound each lexical candidate lane independently."""

        return min(top_k + 2, 8)

    async def _identify_metadata_document_ids(
        self,
        session: AsyncSession,
        *,
        question: str,
        repair_query: str | None,
        trust_scope: RetrievalTrustScope,
    ) -> tuple[UUID, ...]:
        """Identify up to two eligible latest documents without selecting chunk content.

        Metadata is a scope only for exact user-supplied document numbers, never
        evidence, and never creates a citation by itself.
        """

        exact_numbers = _extract_document_numbers(question)
        if not exact_numbers:
            return ()
        del repair_query

        latest_version_number = (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == LegalDocument.id)
            .correlate(LegalDocument)
            .scalar_subquery()
        )
        eligible_trust_modes = eligible_transport_trust_modes(trust_scope)
        selected_provenance_id = (
            select(SourceProvenanceRecord.id)
            .where(
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                SourceProvenanceRecord.transport_trust_mode.in_(
                    tuple(mode.value for mode in eligible_trust_modes)
                ),
                or_(
                    SourceProvenanceRecord.provenance_type == ProvenanceType.SOURCE_FETCH.value,
                    and_(
                        SourceProvenanceRecord.provenance_type
                        == ProvenanceType.MANUAL_SNAPSHOT.value,
                        SourceProvenanceRecord.transport_trust_mode
                        == TransportTrustMode.STRICT_TLS.value,
                    ),
                ),
            )
            .order_by(
                case(
                    (
                        SourceProvenanceRecord.transport_trust_mode
                        == TransportTrustMode.STRICT_TLS.value,
                        0,
                    ),
                    else_=1,
                ),
                SourceProvenanceRecord.retrieved_at.asc(),
                SourceProvenanceRecord.id.asc(),
            )
            .limit(1)
            .correlate(DocumentVersion)
            .scalar_subquery()
        )
        statement = (
            select(LegalDocument.id)
            .select_from(DocumentVersion)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .where(
                LegalDocument.source_id.in_(self._active_source_ids),
                DocumentVersion.version_number == latest_version_number,
                selected_provenance_id.is_not(None),
                func.lower(DocumentVersion.document_number).in_(exact_numbers),
            )
            .order_by(LegalDocument.id.asc())
            .limit(_MAX_METADATA_DOCUMENT_IDS)
        )
        rows = (await session.execute(statement)).all()
        return tuple(row[0] for row in rows)

    async def _select_candidates(
        self,
        session: AsyncSession,
        *,
        query: str,
        candidate_limit: int,
        document_ids: tuple[UUID, ...] | None = None,
        trust_scope: RetrievalTrustScope = RetrievalTrustScope.STRICT_TLS_ONLY,
    ) -> tuple[_CandidateRow, ...]:
        """Select current chunks and deterministic provenance without content projection."""

        latest_version_number = (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == LegalDocument.id)
            .correlate(LegalDocument)
            .scalar_subquery()
        )
        eligible_trust_modes = eligible_transport_trust_modes(trust_scope)
        selected_provenance_id = (
            select(SourceProvenanceRecord.id)
            .where(
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                SourceProvenanceRecord.transport_trust_mode.in_(
                    tuple(mode.value for mode in eligible_trust_modes)
                ),
                or_(
                    SourceProvenanceRecord.provenance_type == ProvenanceType.SOURCE_FETCH.value,
                    and_(
                        SourceProvenanceRecord.provenance_type
                        == ProvenanceType.MANUAL_SNAPSHOT.value,
                        SourceProvenanceRecord.transport_trust_mode
                        == TransportTrustMode.STRICT_TLS.value,
                    ),
                ),
            )
            .order_by(
                case(
                    (
                        SourceProvenanceRecord.transport_trust_mode
                        == TransportTrustMode.STRICT_TLS.value,
                        0,
                    ),
                    else_=1,
                ),
                SourceProvenanceRecord.retrieved_at.asc(),
                SourceProvenanceRecord.id.asc(),
            )
            .limit(1)
            .correlate(DocumentVersion)
            .scalar_subquery()
        )
        parsed_query = select(
            func.websearch_to_tsquery(
                text("'pg_catalog.simple'::regconfig"), bindparam("query")
            ).label("parsed_query")
        ).cte("parsed_query")
        lexical_score = func.ts_rank_cd(DocumentChunk.search_vector, parsed_query.c.parsed_query)
        predicates = [
            LegalDocument.source_id.in_(self._active_source_ids),
            DocumentVersion.version_number == latest_version_number,
            func.numnode(parsed_query.c.parsed_query) > 0,
            DocumentChunk.search_vector.op("@@")(parsed_query.c.parsed_query),
            selected_provenance_id.is_not(None),
        ]
        if document_ids is not None:
            predicates.append(LegalDocument.id.in_(document_ids))
        statement = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_version_id,
                SourceProvenanceRecord.id,
                SourceProvenanceRecord.document_version_id,
                SourceProvenanceRecord.provenance_type,
                SourceProvenanceRecord.transport_trust_mode,
                lexical_score,
            )
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .outerjoin(SourceProvenanceRecord, SourceProvenanceRecord.id == selected_provenance_id)
            .join(parsed_query, true())
            .where(*predicates)
            .order_by(lexical_score.desc(), DocumentChunk.id.asc())
            .limit(candidate_limit)
        )
        rows = (await session.execute(statement, {"query": query})).all()
        return tuple(
            _CandidateRow(
                document_chunk_id=row[0],
                document_version_id=row[1],
                source_provenance_record_id=row[2],
                source_provenance_document_version_id=row[3],
                provenance_type=ProvenanceType(row[4]),
                transport_trust_mode=TransportTrustMode(row[5]),
                lexical_score=float(row[6]),
            )
            for row in rows
        )

    @staticmethod
    def _validate_active_source_ids(active_source_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Reject synthetic/default source scope and retain only an immutable bounded tuple."""

        if (
            not isinstance(active_source_ids, tuple)
            or not 1 <= len(active_source_ids) <= _MAX_ACTIVE_SOURCE_IDS
        ):
            raise ValueError("active_source_ids must be a nonempty bounded tuple")
        if any(
            not isinstance(source_id, str)
            or not source_id
            or source_id != source_id.strip()
            or len(source_id) > _MAX_SOURCE_ID_CHARS
            for source_id in active_source_ids
        ):
            raise ValueError("active_source_ids must contain bounded nonblank IDs")
        if len(set(active_source_ids)) != len(active_source_ids):
            raise ValueError("active_source_ids must be unique")
        return active_source_ids

    @staticmethod
    def _fuse_candidates(
        raw: tuple[_CandidateRow, ...],
        repair: tuple[_CandidateRow, ...],
        expansion: tuple[_CandidateRow, ...],
        top_k: int,
    ) -> tuple[_CandidateRow, ...]:
        """Fuse bounded lanes with weighted RRF and mandatory raw-top retention."""

        fused_scores: dict[UUID, float] = {}
        selected_rows: dict[UUID, _CandidateRow] = {}
        raw_ids = {candidate.document_chunk_id for candidate in raw}
        for weight, candidates in ((3, repair), (1, raw), (1, expansion)):
            for rank, candidate in enumerate(candidates, start=1):
                chunk_id = candidate.document_chunk_id
                fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + weight / (
                    _RRF_RANK_CONSTANT + rank
                )
                # Repair is intentionally preferred for a duplicate because its
                # phrase is the content predicate that established the evidence.
                existing = selected_rows.get(chunk_id)
                selected_rows[chunk_id] = (
                    candidate
                    if existing is None
                    else replace(
                        existing,
                        lexical_score=(
                            existing.lexical_score
                            if existing.lexical_score is not None
                            else candidate.lexical_score
                        ),
                        semantic_score=(
                            existing.semantic_score
                            if existing.semantic_score is not None
                            else candidate.semantic_score
                        ),
                    )
                )

        ordered_ids = sorted(
            fused_scores,
            key=lambda chunk_id: (
                -fused_scores[chunk_id],
                -(chunk_id in raw_ids),
                chunk_id,
            ),
        )
        retained_ids = ordered_ids[:top_k]
        if raw:
            raw_top_id = raw[0].document_chunk_id
            if raw_top_id not in retained_ids:
                retained_ids[-1] = raw_top_id
                retained_ids.sort(
                    key=lambda chunk_id: (
                        -fused_scores[chunk_id],
                        -(chunk_id in raw_ids),
                        chunk_id,
                    )
                )
        return tuple(selected_rows[chunk_id] for chunk_id in retained_ids)

    @staticmethod
    def _has_valid_chain(
        candidates: tuple[_CandidateRow, ...],
        trust_scope: RetrievalTrustScope = RetrievalTrustScope.STRICT_TLS_ONLY,
    ) -> bool:
        """Require each selected provenance to match both chunk version and run trust scope."""

        return all(
            candidate.source_provenance_record_id is not None
            and candidate.source_provenance_document_version_id == candidate.document_version_id
            and is_evidence_provenance_eligible(
                trust_scope,
                candidate.transport_trust_mode,
                candidate.provenance_type,
            )
            for candidate in candidates
        )

    async def _persist_result(
        self,
        session: AsyncSession,
        request: RetrievalRequest,
        candidates: tuple[_CandidateRow, ...],
        decision: RetrievalDecision,
        reason: RetrievalReason,
        strategy_version: str,
    ) -> RetrievalResult:
        """Write a run and, only after validation, its citation rows."""

        if candidates and not self._has_valid_chain(candidates, request.trust_scope):
            raise RetrievalError(RetrievalErrorCode.INVALID_EVIDENCE_CHAIN)
        if decision is not RetrievalDecision.EVIDENCE_AVAILABLE and candidates:
            raise RetrievalError(RetrievalErrorCode.INVALID_EVIDENCE_CHAIN)

        run = RetrievalRun(
            id=uuid4(),
            strategy=LEXICAL_STRATEGY,
            strategy_version=strategy_version,
            scope=RetrievalScope.LATEST_INGESTED.value,
            trust_scope=request.trust_scope.value,
            query_max_chars=QUERY_MAX_CHARS,
            top_k=request.top_k,
            candidate_count=len(candidates),
            citation_count=len(candidates),
            evidence_decision=decision.value,
            evidence_reason=reason.value,
        )
        session.add(run)
        await session.flush()

        output_candidates: list[RetrievalCandidate] = []
        for rank, candidate in enumerate(candidates, start=1):
            provenance_id = candidate.source_provenance_record_id
            if provenance_id is None:
                raise RetrievalError(RetrievalErrorCode.INVALID_EVIDENCE_CHAIN)
            citation_id = uuid4()
            session.add(
                CitationRecord(
                    id=citation_id,
                    retrieval_run_id=run.id,
                    document_chunk_id=candidate.document_chunk_id,
                    source_provenance_record_id=provenance_id,
                    rank=rank,
                    lexical_score=candidate.lexical_score,
                    semantic_score=candidate.semantic_score,
                )
            )
            output_candidates.append(
                RetrievalCandidate(
                    citation_id=citation_id,
                    document_chunk_id=candidate.document_chunk_id,
                    rank=rank,
                    lexical_score=candidate.lexical_score,
                    semantic_score=candidate.semantic_score,
                )
            )
        await session.flush()
        return RetrievalResult(
            retrieval_run_id=run.id,
            candidates=tuple(output_candidates),
            candidate_count=len(output_candidates),
            citation_count=len(output_candidates),
            decision=decision,
            reason=reason,
        )

    def _log_complete(
        self, request: RetrievalRequest, result: RetrievalResult, strategy_version: str
    ) -> None:
        self._logger.info(
            "retrieval_complete",
            extra={
                "retrieval_run_id": str(result.retrieval_run_id),
                "retrieval_strategy": LEXICAL_STRATEGY,
                "retrieval_strategy_version": strategy_version,
                "retrieval_scope": RetrievalScope.LATEST_INGESTED.value,
                "retrieval_trust_scope": request.trust_scope.value,
                "retrieval_decision": result.decision.value,
                "retrieval_reason": result.reason.value,
                "retrieval_candidate_count": result.candidate_count,
                "retrieval_citation_count": result.citation_count,
                "retrieval_top_k": request.top_k,
            },
        )

    def _log_failure(
        self, request: RetrievalRequest, code: RetrievalErrorCode, strategy_version: str
    ) -> None:
        self._logger.warning(
            "retrieval_failed",
            extra={
                "retrieval_strategy": LEXICAL_STRATEGY,
                "retrieval_strategy_version": strategy_version,
                "retrieval_scope": RetrievalScope.LATEST_INGESTED.value,
                "retrieval_trust_scope": request.trust_scope.value,
                "retrieval_top_k": request.top_k,
                "retrieval_error_code": code.value,
            },
        )

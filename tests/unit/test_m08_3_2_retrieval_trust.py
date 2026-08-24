"""Focused fail-closed trust-lane contracts for M08.3.2 Phase 1A."""

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.channels.formatter import ChannelFormatter
from legal_chatbot.chat.models import ChatOutcome, ChatReasonCode, GroundedChatResult
from legal_chatbot.chat.service import GroundedChatService
from legal_chatbot.documents.citation_resolver import (
    PostgresCitationResolver,
    _CitationRow,
)
from legal_chatbot.documents.grounding_evidence import _GroundingRow
from legal_chatbot.documents.orm import RetrievalRun
from legal_chatbot.documents.retrieval_repository import (
    PostgresLexicalRetrievalRepository,
    _CandidateRow,
)
from legal_chatbot.retrieval.models import (
    EvidenceTrustLabel,
    ResolvedCitation,
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalTrustScope,
    coerce_transport_trust_mode,
)
from legal_chatbot.sources.models import TransportTrustMode


def _citation(mode: TransportTrustMode = TransportTrustMode.STRICT_TLS) -> ResolvedCitation:
    labels = {
        TransportTrustMode.STRICT_TLS: EvidenceTrustLabel.OFFICIAL_LEGAL,
        TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION: (
            EvidenceTrustLabel.OFFICIAL_LEGAL_PINNED_EXCEPTION
        ),
    }
    return ResolvedCitation(
        citation_id=uuid4(),
        retrieval_run_id=uuid4(),
        document_chunk_id=uuid4(),
        document_version_id=uuid4(),
        document_id=uuid4(),
        source_provenance_record_id=uuid4(),
        transport_trust_mode=mode,
        evidence_trust_label=labels[mode],
        source_id="VBQPPL",
        external_id="official-document",
    )


def test_request_defaults_strict_and_citation_labels_are_exact_and_non_sensitive() -> None:
    assert RetrievalRequest(query="nghĩa vụ").trust_scope is RetrievalTrustScope.STRICT_TLS_ONLY
    assert coerce_transport_trust_mode("STRICT_TLS") is TransportTrustMode.STRICT_TLS
    with pytest.raises(ValueError):
        coerce_transport_trust_mode("LEGACY_UNKNOWN")
    pinned = _citation(TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION)
    assert pinned.evidence_trust_label is EvidenceTrustLabel.OFFICIAL_LEGAL_PINNED_EXCEPTION
    dumped = pinned.model_dump_json()
    assert "spki_sha256" not in dumped.casefold()
    assert "digest" not in dumped.casefold()
    assert "certificate" not in dumped.casefold()

    with pytest.raises(ValidationError, match="must match"):
        _citation(TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION).model_validate(
            {
                **_citation(TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION).model_dump(),
                "evidence_trust_label": EvidenceTrustLabel.OFFICIAL_LEGAL,
            }
        )
    with pytest.raises(ValidationError):
        ResolvedCitation.model_validate(
            {
                **_citation().model_dump(),
                "transport_trust_mode": TransportTrustMode.LEGACY_UNVERIFIED,
            }
        )


@pytest.mark.asyncio
async def test_original_and_expansion_searches_receive_the_same_server_trust_scope() -> None:
    class TrackingRepository(PostgresLexicalRetrievalRepository):
        def __init__(self) -> None:
            self.calls: list[tuple[str, RetrievalTrustScope]] = []

        async def _select_candidates(
            self,
            session: object,
            *,
            query: str,
            candidate_limit: int,
            document_ids: tuple | None = None,
            trust_scope: RetrievalTrustScope = RetrievalTrustScope.STRICT_TLS_ONLY,
        ) -> tuple:
            del session, candidate_limit, document_ids
            self.calls.append((query, trust_scope))
            return ()

    repository = TrackingRepository()
    request = RetrievalRequest(
        query="gốc",
        expansion_query="mở rộng",
        trust_scope=RetrievalTrustScope.ALLOW_USER_APPROVED_TOFU_PINNED_EXCEPTION,
    )
    assert await repository._retrieve_candidates(None, request) == ()  # type: ignore[arg-type]
    assert await repository._retrieve_expansion_candidates(None, request) == ()  # type: ignore[arg-type]
    assert repository.calls == [
        ("gốc", RetrievalTrustScope.ALLOW_USER_APPROVED_TOFU_PINNED_EXCEPTION),
        ("mở rộng", RetrievalTrustScope.ALLOW_USER_APPROVED_TOFU_PINNED_EXCEPTION),
    ]


@pytest.mark.asyncio
async def test_repository_sql_filters_provenance_and_persists_exactly_one_trust_scope() -> None:
    class Result:
        def all(self) -> tuple[()]:
            return ()

    class Session:
        def __init__(self) -> None:
            self.statements: list[Any] = []
            self.added: list[object] = []
            self.flush_count = 0

        async def execute(self, statement: object, _parameters: object) -> Result:
            self.statements.append(statement)
            return Result()

        def add(self, value: object) -> None:
            self.added.append(value)

        async def flush(self) -> None:
            self.flush_count += 1

    repository = object.__new__(PostgresLexicalRetrievalRepository)
    repository._active_source_ids = ("VBQPPL",)
    session = Session()
    await repository._select_candidates(
        session,  # type: ignore[arg-type]
        query="gốc",
        candidate_limit=2,
        trust_scope=RetrievalTrustScope.STRICT_TLS_ONLY,
    )
    await repository._select_candidates(
        session,  # type: ignore[arg-type]
        query="ngoại lệ",
        candidate_limit=2,
        trust_scope=RetrievalTrustScope.ALLOW_USER_APPROVED_TOFU_PINNED_EXCEPTION,
    )
    strict_sql = session.statements[0].compile(dialect=postgresql.dialect())
    exception_sql = session.statements[1].compile(dialect=postgresql.dialect())
    assert "transport_trust_mode" in str(strict_sql)
    assert TransportTrustMode.STRICT_TLS.value in str(strict_sql.params.values())
    assert TransportTrustMode.LEGACY_UNVERIFIED.value not in str(exception_sql.params.values())
    assert TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION.value in str(
        exception_sql.params.values()
    )
    assert "CASE WHEN" in str(exception_sql)

    request = RetrievalRequest(
        query="ngoại lệ", trust_scope=RetrievalTrustScope.ALLOW_USER_APPROVED_TOFU_PINNED_EXCEPTION
    )
    result = await repository._persist_result(
        session,  # type: ignore[arg-type]
        request,
        (),
        decision=RetrievalDecision.NO_RESULTS,
        reason=RetrievalReason.NO_LEXICAL_MATCH,
        strategy_version="v1",
    )
    runs = [value for value in session.added if isinstance(value, RetrievalRun)]
    assert len(runs) == 1
    assert runs[0].trust_scope == request.trust_scope.value
    assert result.retrieval_run_id == runs[0].id


def test_grounding_and_resolver_trust_checks_fail_closed_for_ineligible_provenance() -> None:
    strict_run_tofu = _GroundingRow(
        citation_id=uuid4(),
        retrieval_run_id=uuid4(),
        document_chunk_id=uuid4(),
        document_version_id=uuid4(),
        version_id=uuid4(),
        document_id=uuid4(),
        source_provenance_record_id=uuid4(),
        source_id="VBQPPL",
        external_id="id",
        document_number=None,
        title=None,
        canonical_url=None,
        locator=None,
        content_text="evidence",
        transport_trust_mode=TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION.value,
    )
    assert not strict_run_tofu.has_eligible_transport_trust()
    assert _GroundingRow(
        **{
            **strict_run_tofu.__dict__,
            "trust_scope": RetrievalTrustScope.ALLOW_USER_APPROVED_TOFU_PINNED_EXCEPTION.value,
        }
    ).has_eligible_transport_trust()

    row = _CitationRow(
        uuid4(),
        uuid4(),
        "LATEST_INGESTED",
        RetrievalTrustScope.STRICT_TLS_ONLY.value,
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "VBQPPL",
        TransportTrustMode.LEGACY_UNVERIFIED.value,
        "id",
        None,
        None,
        None,
        None,
    )
    assert not PostgresCitationResolver._has_valid_chain(row)
    legacy_candidate = _CandidateRow(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        0.5,
        TransportTrustMode.LEGACY_UNVERIFIED,
    )
    assert not PostgresLexicalRetrievalRepository._has_valid_chain((legacy_candidate,))


def test_chat_identity_includes_trust_and_channel_discloses_only_pinned_exception() -> None:
    strict = _citation()
    pinned = _citation(TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION)
    assert not GroundedChatService._same_citation_identity(
        strict, strict.model_copy(update={"evidence_trust_label": pinned.evidence_trust_label})
    )
    formatter = ChannelFormatter(
        ChannelSettings.model_validate(
            {
                "ZALO_OFFICIAL_BOT_TOKEN": "token-value-012345",
                "ZALO_OFFICIAL_BOT_WEBHOOK_SECRET": "webhook-secret-012345",
                "CHANNEL_IDENTITY_HMAC_KEY": "identity-key-012345678901234567890123",
            }
        )
    )
    strict_text = formatter.format(
        GroundedChatResult(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_GROUNDED,
            answer="Trả lời",
            retrieval_run_id=strict.retrieval_run_id,
            citations=(strict,),
            provider="test",
            model="test",
        )
    ).text
    pinned_text = formatter.format(
        GroundedChatResult(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_GROUNDED,
            answer="Trả lời",
            retrieval_run_id=pinned.retrieval_run_id,
            citations=(pinned,),
            provider="test",
            model="test",
        )
    ).text
    assert "TOFU/SPKI" not in strict_text
    assert "TOFU/SPKI" in pinned_text
    assert "pin=" not in pinned_text.casefold()

"""Read-only P3-to-P6 evidence-path forensic diagnostic for one controlled case."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.diagnostics.p1_p10_vertical_slice import _CASES, _active_source_ids
from legal_chatbot.documents.orm import (
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    SourceProvenanceRecord,
)
from legal_chatbot.legal_evidence import AuthorityRole, AuthorityState, create_legal_case
from legal_chatbot.legal_evidence.analyzer import (
    LegalQuestionAnalyzerSettings,
    LLMLegalQuestionAnalyzer,
)
from legal_chatbot.legal_evidence.authority import AuthorityReviewService, AuthorityReviewSettings
from legal_chatbot.legal_evidence.discovery import BroadDiscoveryService, DiscoverySettings
from legal_chatbot.legal_evidence.pinpoint import (
    PinpointEvidenceService,
    PinpointReadRequest,
    PinpointSettings,
)
from legal_chatbot.legal_evidence.postgres_adapters import (
    PostgresAuthorityMetadataReader,
    PostgresBroadDiscoveryReader,
    PostgresPinpointEvidenceReader,
)
from legal_chatbot.legal_evidence.relations import (
    RelationInvestigationService,
    RelationInvestigationSettings,
)
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.registry import create_provider
from legal_chatbot.semantic.config import SemanticSettings
from legal_chatbot.semantic.fastembed_adapter import FastEmbedSemanticAdapter

_ARTIFACT = Path("docs/evals/p5-p6-evidence-path-forensic-q10.json")
_STRICT_PROVENANCE_TYPES = ("source_fetch", "manual_snapshot")
_P5_DROP_REASONS = (
    "P5_FILTERED_AUTHORITY_STATE",
    "P5_ROLE_NOT_ELIGIBLE",
    "P5_FAMILY_MERGED",
    "P5_FAMILY_BUDGET_PRUNED",
    "P5_DUPLICATE_VERSION",
    "P5_SCOPE_CONFLICT",
    "P5_PROVENANCE_REJECTED",
    "P5_NOT_SELECTED_FOR_SUBINTENT",
    "P5_UNKNOWN_DROP",
)
_P6_NO_HIT_REASONS = (
    "P6_FAMILY_NOT_AVAILABLE",
    "P6_NO_SEARCHABLE_CHUNKS",
    "P6_QUERY_NO_MATCH",
    "P6_SCORE_BELOW_THRESHOLD",
    "P6_LOCATOR_INVALID",
    "P6_PROVENANCE_MISMATCH",
    "P6_CHUNK_FILTERED",
    "P6_EMPTY_CONTENT",
    "P6_UNKNOWN_NO_HIT",
)


@dataclass(frozen=True)
class _P6SearchRecord:
    request: PinpointReadRequest
    searchable_chunks: dict[UUID, int]
    candidate_chunks: dict[UUID, int]


class _TracingPinpointReader:
    """Decorate the real P6 reader with count-only, family-bounded forensic facts."""

    def __init__(
        self,
        reader: PostgresPinpointEvidenceReader,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._reader = reader
        self._session_factory = session_factory
        self.records: dict[UUID, _P6SearchRecord] = {}

    async def read(self, request: PinpointReadRequest):
        searchable = await self._searchable_chunk_counts(request)
        raw = await self._reader.read(request)
        candidates = Counter(item.evidence.document.document_version_id for item in raw)
        self.records[request.sub_intent_id] = _P6SearchRecord(
            request=request,
            searchable_chunks=searchable,
            candidate_chunks=dict(candidates),
        )
        return raw

    async def _searchable_chunk_counts(self, request: PinpointReadRequest) -> dict[UUID, int]:
        version_ids = tuple(item.document_version_id for item in request.documents)
        provenance_ids = tuple(item.provenance_record_id for item in request.documents)
        statement = (
            select(DocumentChunk.document_version_id, func.count(DocumentChunk.id))
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(
                SourceProvenanceRecord,
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
            )
            .where(
                DocumentVersion.id.in_(version_ids),
                SourceProvenanceRecord.id.in_(provenance_ids),
                SourceProvenanceRecord.source_id == LegalDocument.source_id,
                SourceProvenanceRecord.provenance_type.in_(_STRICT_PROVENANCE_TYPES),
                SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
            )
            .group_by(DocumentChunk.document_version_id)
        )
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION READ ONLY"))
                rows = tuple((await session.execute(statement)).all())
        return {row[0]: int(row[1]) for row in rows}


async def run_q10_forensic() -> dict[str, object]:
    """Trace the current P3-P6 path without changing P5/P6 behavior."""

    engine = create_engine(Settings())
    provider = None
    try:
        sessions = create_session_factory(engine)
        semantic = FastEmbedSemanticAdapter(SemanticSettings())
        p4_enabled = os.environ.get("P4_LLM_ENABLED", "false").strip().casefold() == "true"
        if p4_enabled:
            provider = create_provider(ProviderSettings())
        case = next(item for item in _CASES if item.case_id == "Q10")
        analyzed = await LLMLegalQuestionAnalyzer(
            None, settings=LegalQuestionAnalyzerSettings(enabled=False)
        ).analyze_context(create_legal_case(case.question))
        discovery = await BroadDiscoveryService(
            PostgresBroadDiscoveryReader(sessions, semantic, _active_source_ids()),
            DiscoverySettings(enabled=True),
        ).discover(analyzed)
        metadata = await PostgresAuthorityMetadataReader(sessions).load(
            discovery.context.candidate_documents
        )
        authority = await AuthorityReviewService(
            provider, AuthorityReviewSettings(enabled=p4_enabled)
        ).review_case(discovery.context, metadata)
        relations = await RelationInvestigationService(
            None, RelationInvestigationSettings(enabled=False)
        ).investigate_context(authority.context)
        tracing_reader = _TracingPinpointReader(PostgresPinpointEvidenceReader(sessions), sessions)
        pinpoint = await PinpointEvidenceService(
            tracing_reader, PinpointSettings(enabled=True)
        ).read_context(relations.context)
        trace = _evidence_path_trace(discovery, authority, relations, pinpoint, tracing_reader)
        classification = _root_cause(trace, relations.context)
        return {
            "schema_version": "P5-P6-EVIDENCE-PATH-FORENSIC-1",
            "case_id": "Q10",
            "p2_mode": "deterministic_fallback",
            "p4_outcome": authority.outcome.value,
            "p3_document_count": len(discovery.context.candidate_documents),
            "p5_family_count": len(relations.context.authority_families),
            "p6_evidence_count": len(pinpoint.result.evidence_units),
            "root_cause_classification": classification,
            "drop_reason_taxonomy": {
                "p5": list(_P5_DROP_REASONS),
                "p6": list(_P6_NO_HIT_REASONS),
            },
            "evidence_path_trace": trace,
        }
    finally:
        if provider is not None:
            await provider.aclose()
        await engine.dispose()


def write_artifact(report: dict[str, object]) -> None:
    _ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    temporary = _ARTIFACT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(_ARTIFACT)


def _evidence_path_trace(
    discovery, authority, relations, pinpoint, p6_reader
) -> list[dict[str, object]]:
    family_by_version: dict[UUID, tuple[str, tuple[UUID, ...]]] = {}
    for family_index, family in enumerate(relations.context.authority_families, start=1):
        family_id = f"family-{family_index:02d}"
        for version_id in family.document_version_ids:
            family_by_version[version_id] = (family_id, family.document_version_ids)
    assessment_by_key = {
        (item.document.document_version_id, item.sub_intent_id): item
        for item in authority.assessments
    }
    candidate_by_version = {
        item.document.document_version_id: item for item in authority.candidates
    }
    evidence_by_key = Counter(
        (item.evidence.document.document_version_id, sub_intent_id)
        for item in pinpoint.result.evidence_units
        for sub_intent_id in item.supported_sub_intent_ids
    )
    records: list[dict[str, object]] = []
    for document in discovery.workspace.documents:
        version_id = document.document.document_version_id
        family = family_by_version.get(version_id)
        candidate = candidate_by_version[version_id]
        for sub_intent in authority.context.sub_intents:
            assessment = assessment_by_key[(version_id, sub_intent.sub_intent_id)]
            p5_retained, p5_drop_reason = _p5_state(candidate, assessment, family)
            search = p6_reader.records.get(sub_intent.sub_intent_id)
            searched = bool(
                p5_retained
                and search is not None
                and version_id in search.request.document_version_ids
            )
            candidate_chunks = 0 if search is None else search.candidate_chunks.get(version_id, 0)
            evidence_count = evidence_by_key[(version_id, sub_intent.sub_intent_id)]
            records.append(
                {
                    "document_id": str(document.document.document_id),
                    "document_version_id": str(version_id),
                    "provenance_record_id": str(document.document.provenance_record_id),
                    "source_id": document.document.source_id,
                    "sub_intent_id": str(sub_intent.sub_intent_id),
                    "discovered_in_p3": True,
                    "p3_lanes": [item.lane.value for item in document.observations],
                    "p3_rank_or_scores": {
                        item.lane.value: {"rank": item.rank, "score": item.score}
                        for item in document.observations
                    },
                    "p4_proposed_role": assessment.proposed_role.value,
                    "p4_validated_role": assessment.role.value,
                    "p4_authority_state": assessment.state.value,
                    "p4_applicability": assessment.applicability.value,
                    "p4_filter_reason": None
                    if assessment.filter_reason is None
                    else assessment.filter_reason.value,
                    "p4_scope_conflict": assessment.scope_conflict,
                    "p5_family_id": None if family is None else family[0],
                    "p5_family_members": []
                    if family is None
                    else [str(item) for item in family[1]],
                    "p5_retained": p5_retained,
                    "p5_drop_reason": p5_drop_reason,
                    "p5_priority_score_components": {
                        "authority_role": assessment.role.value,
                        "applicability": assessment.applicability.value,
                        "provenance": "STRICT_VALID"
                        if candidate.state is AuthorityState.ELIGIBLE
                        else "REJECTED",
                        "sub_intent_relevant": assessment.role is not AuthorityRole.IRRELEVANT,
                        "policy": "pre-correction-p3-order-first-15",
                    },
                    "p6_searched": searched,
                    "p6_query_strategy": "dimension_aware_within_family_fts_or",
                    "p6_candidate_chunk_count": candidate_chunks,
                    "p6_evidence_count": evidence_count,
                    "p6_no_hit_reason": _p6_no_hit_reason(
                        p5_retained, searched, search, version_id, candidate_chunks, evidence_count
                    ),
                }
            )
    return records


def _p5_state(candidate, assessment, family) -> tuple[bool, str | None]:
    if assessment.state is not AuthorityState.ELIGIBLE:
        if assessment.scope_conflict:
            return False, "P5_SCOPE_CONFLICT"
        if assessment.state is AuthorityState.FILTERED_PROVENANCE:
            return False, "P5_PROVENANCE_REJECTED"
        return False, "P5_FILTERED_AUTHORITY_STATE"
    if assessment.role is AuthorityRole.IRRELEVANT or candidate.role is AuthorityRole.IRRELEVANT:
        return False, "P5_ROLE_NOT_ELIGIBLE"
    if family is None:
        return False, "P5_FAMILY_BUDGET_PRUNED"
    return True, None


def _p6_no_hit_reason(
    p5_retained: bool,
    searched: bool,
    search: _P6SearchRecord | None,
    version_id: UUID,
    candidate_chunks: int,
    evidence_count: int,
) -> str | None:
    if evidence_count:
        return None
    if not p5_retained or not searched:
        return "P6_FAMILY_NOT_AVAILABLE"
    if search is None or not search.searchable_chunks.get(version_id, 0):
        return "P6_NO_SEARCHABLE_CHUNKS"
    if not candidate_chunks:
        return "P6_QUERY_NO_MATCH"
    return "P6_CHUNK_FILTERED"


def _root_cause(trace: list[dict[str, object]], context) -> str:
    classifications: set[str] = set()
    for sub_intent in context.sub_intents:
        rows = [item for item in trace if item["sub_intent_id"] == str(sub_intent.sub_intent_id)]
        p4_relevant = [
            item
            for item in rows
            if item["p4_authority_state"] == AuthorityState.ELIGIBLE.value
            and item["p4_validated_role"] != AuthorityRole.IRRELEVANT.value
        ]
        p5_retained = [item for item in p4_relevant if item["p5_retained"]]
        p6_hits = [item for item in p5_retained if item["p6_evidence_count"]]
        if not rows:
            classifications.add("UPSTREAM_DISCOVERY_GAP")
        elif not p4_relevant:
            classifications.add("UPSTREAM_AUTHORITY_GAP")
        elif not p5_retained:
            classifications.add("P5_FAMILY_SELECTION_GAP")
        elif not p6_hits:
            classifications.add("P6_PINPOINT_RETRIEVAL_GAP")
    if not classifications:
        return "NO_EVIDENCE_PATH_GAP"
    if len(classifications) > 1:
        return "MULTIPLE_GAPS"
    return next(iter(classifications))


def main() -> None:
    report = asyncio.run(run_q10_forensic())
    write_artifact(report)
    print(report["root_cause_classification"])


if __name__ == "__main__":
    main()

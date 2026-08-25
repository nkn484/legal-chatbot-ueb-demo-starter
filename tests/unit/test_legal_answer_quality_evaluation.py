"""Contract coverage for quality prompt and controlled evaluation artifacts."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError

from legal_chatbot.chat import ChatRequest, ChatSettings
from legal_chatbot.chat.errors import ChatError
from legal_chatbot.chat.quality_prompt import build_quality_grounded_prompt
from legal_chatbot.diagnostics.evaluation import (
    AblationMeasurement,
    AblationProfile,
    AblationReport,
    EvaluationMeasurementState,
    QualityRunManifest,
    scan_production_for_benchmark_leakage,
)
from legal_chatbot.retrieval.models import ResolvedCitation
from legal_chatbot.retrieval.quality_repair.analyzer import (
    AnalyzerObservation,
    AnalyzerUnit,
    GenericIntent,
    QueryComplexity,
    SourceScope,
)
from legal_chatbot.retrieval.quality_repair.candidate_roles import AuthorityRole
from legal_chatbot.retrieval.quality_repair.coverage import (
    EvidenceCoverageEntry,
    EvidenceCoverageMatrix,
    EvidenceCoverageStatus,
)
from legal_chatbot.retrieval.quality_repair.evidence_pack import (
    SelectedLegalAuthority,
    StructuredEvidencePack,
)


def _uuid(value: str) -> UUID:
    return uuid5(UUID("12345678-1234-5678-1234-567812345678"), value)


def _pack(authority_count: int) -> StructuredEvidencePack:
    analysis = AnalyzerObservation(
        intent=GenericIntent.GENERAL,
        complexity=QueryComplexity.SIMPLE,
        source_scope=SourceScope.NONE,
        units=(AnalyzerUnit(unit_id="u01", source_scope=SourceScope.NONE),),
    )
    coverage = EvidenceCoverageMatrix(
        entries=(
            EvidenceCoverageEntry(
                unit_id="u01",
                status=EvidenceCoverageStatus.SUPPORTED,
                direct_authority_present=True,
                source_scope_appropriate=True,
                applicability_uncertain=True,
            ),
        )
    )
    authorities = tuple(
        SelectedLegalAuthority(
            citation=ResolvedCitation(
                citation_id=_uuid(f"citation-{index}"),
                retrieval_run_id=_uuid("run"),
                document_chunk_id=_uuid(f"chunk-{index}"),
                document_version_id=_uuid(f"version-{index}"),
                document_id=_uuid(f"document-{index}"),
                source_provenance_record_id=_uuid(f"provenance-{index}"),
                source_id="VBQPPL",
                external_id=f"external-{index}",
            ),
            excerpt=f"evidence {index}",
            role=AuthorityRole.DIRECT_AUTHORITY,
            supported_unit_ids=("u01",),
            applicability_uncertain=True,
        )
        for index in range(authority_count)
    )
    return StructuredEvidencePack(analysis=analysis, authorities=authorities, coverage=coverage)


def test_quality_prompt_accepts_six_evidence_items_only_when_settings_allow_it() -> None:
    pack = _pack(6)
    settings = ChatSettings(max_citations=6, total_evidence_max_chars=6_000)

    prompt = build_quality_grounded_prompt(ChatRequest(question="Câu hỏi"), pack, settings)

    assert "STRUCTURED_EVIDENCE_PACK" in prompt
    assert "current applicability and legal effect were not independently verified" in prompt
    assert '"authority_count"' not in prompt
    with pytest.raises(ChatError):
        build_quality_grounded_prompt(ChatRequest(question="Câu hỏi"), pack, ChatSettings())


def test_ablation_state_prevents_unmeasured_claims_and_requires_complete_measures() -> None:
    empty = AblationMeasurement(
        profile=AblationProfile.C01, state=EvaluationMeasurementState.NOT_MEASURED
    )
    assert AblationReport(measurements=(empty,)).measurements == (empty,)
    with pytest.raises(ValidationError, match="unmeasured"):
        AblationMeasurement(
            profile=AblationProfile.C01,
            state=EvaluationMeasurementState.NOT_MEASURED,
            set_a_average=8.5,
        )
    with pytest.raises(ValidationError, match="measured"):
        AblationMeasurement(profile=AblationProfile.C01, state=EvaluationMeasurementState.MEASURED)


def test_manifest_rejects_secret_like_values_and_leakage_scanner_reports_marker(
    tmp_path: Path,
) -> None:
    values = {
        "provider": "shineshop",
        "model": "legal-model",
        "prompt_version": "quality-v1",
        "strategy": "quality_retrieval_dynamic_evidence_v1",
        "corpus_snapshot_sha256": "a" * 64,
        "sampling_temperature": 0,
        "retry_limit": 1,
        "timing_protocol": "warmed-single-run",
        "run_count": 1,
    }
    assert QualityRunManifest.model_validate(values).provider == "shineshop"
    with pytest.raises(ValidationError, match="invalid"):
        QualityRunManifest.model_validate({**values, "model": "api_key=unsafe"})

    production = tmp_path / "production"
    production.mkdir()
    (production / "module.py").write_text("marker = 'ORACLE-ONLY'\n", encoding="utf-8")
    findings = scan_production_for_benchmark_leakage(production, ("ORACLE-ONLY",))
    assert [(item.path.name, item.line, item.marker) for item in findings] == [
        ("module.py", 1, "ORACLE-ONLY")
    ]

    diagnostics = production / "diagnostics"
    diagnostics.mkdir()
    (diagnostics / "oracle.py").write_text("marker = 'ORACLE-ONLY'\n", encoding="utf-8")
    assert scan_production_for_benchmark_leakage(
        production, ("ORACLE-ONLY",), excluded_relative_directories=("diagnostics",)
    ) == findings

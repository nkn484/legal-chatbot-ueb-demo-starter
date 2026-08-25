"""Controlled Q05/Q06/Q10 P1-P10 integration diagnostic.

The runner has no Oracle import and never passes expected document identities to
the vertical slice.  It records no raw question text in output artifacts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

from legal_chatbot.core.config import Settings
from legal_chatbot.db.readiness import DatabaseReadiness
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.demo_corpus.config import DemoCorpusSettings
from legal_chatbot.documents.orm import DocumentChunk, DocumentVersion
from legal_chatbot.legal_evidence.vertical_slice import build_p1_p10_vertical_slice
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.registry import create_provider
from legal_chatbot.semantic.config import SemanticSettings
from legal_chatbot.semantic.fastembed_adapter import FastEmbedSemanticAdapter
from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.registry import load_registry

_ARTIFACT_JSON = Path("docs/evals/p1-p10-vertical-slice-q05-q06-q10.json")
_ARTIFACT_MARKDOWN = Path("docs/evals/p1-p10-vertical-slice-q05-q06-q10.md")
_REVIEW_MARKDOWN = Path("docs/review/p1-p10-vertical-slice-review.md")
_PROFILE_VERSION = "p1-p10-vertical-slice-v1"


@dataclass(frozen=True)
class DiagnosticCase:
    """Controlled input only. It carries no expected documents or Oracle labels."""

    case_id: str
    question: str


_CASES = (
    DiagnosticCase(
        case_id="Q05",
        question=(
            "Một nhiệm vụ nghiên cứu và phát triển công nghệ chiến lược do UEB thực "
            "hiện ở cấp ĐHQGHN phải tuân thủ những quy định nào về quản lý và tài chính?"
        ),
    ),
    DiagnosticCase(
        case_id="Q06",
        question=(
            "UEB mua sắm một tài sản mới rồi đưa vào quản lý và kiểm kê thì thẩm quyền "
            "và quy trình thực hiện như thế nào?"
        ),
    ),
    DiagnosticCase(
        case_id="Q10",
        question=(
            "Sinh viên UEB bị cảnh báo học tập hoặc xem xét buộc thôi học thì căn cứ và "
            "quy trình áp dụng như thế nào?"
        ),
    ),
)


async def run_vertical_slice_diagnostic() -> dict[str, object]:
    """Run only the three controlled cases, sequentially, or record a real blocker."""

    settings = Settings()
    active_source_ids = _active_source_ids()
    p4_llm_enabled = _p4_llm_enabled()
    manifest = _manifest(active_source_ids, p4_llm_enabled)
    engine = create_engine(settings)
    provider = None
    try:
        try:
            ready = await DatabaseReadiness(
                engine, settings.database_readiness_timeout_seconds
            ).check()
        except TimeoutError:
            return _blocked_report(manifest, "DATABASE_READINESS_TIMEOUT")
        except Exception:
            return _blocked_report(manifest, "DATABASE_READINESS_UNAVAILABLE")
        if not ready:
            return _blocked_report(manifest, "DATABASE_READINESS_UNAVAILABLE")

        session_factory = create_session_factory(engine)
        try:
            snapshot = await _database_snapshot(session_factory)
            semantic = FastEmbedSemanticAdapter(SemanticSettings())
            if p4_llm_enabled:
                try:
                    provider = create_provider(ProviderSettings())
                except Exception:
                    manifest["p4_provider_model"] = "provider_construction_failed"
            investigator = build_p1_p10_vertical_slice(
                session_factory,
                semantic,
                active_source_ids,
                p4_provider=provider,
                p4_llm_enabled=p4_llm_enabled,
            )
        except Exception:
            return _blocked_report(manifest, "VERTICAL_SLICE_DEPENDENCY_UNAVAILABLE")

        case_results: list[dict[str, object]] = []
        for case in _CASES:
            try:
                trace = await investigator.investigate_with_trace(case.question)
            except Exception as error:
                case_results.append(_failed_case_artifact(case.case_id, error))
                continue
            case_results.append(_case_artifact(case.case_id, trace))
        report = {
            "schema_version": "P1-P10-VERTICAL-SLICE-1",
            "run_manifest": {**manifest, "database_snapshot": snapshot},
            "gate": _gate(case_results),
            "cases": case_results,
        }
        return report
    finally:
        if provider is not None:
            await provider.aclose()
        await engine.dispose()


def write_artifacts(report: dict[str, object]) -> None:
    """Atomically replace the three required diagnostic artifacts."""

    _atomic_write(_ARTIFACT_JSON, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    gate = report["gate"]
    manifest = report["run_manifest"]
    _atomic_write(
        _ARTIFACT_MARKDOWN,
        "\n".join(
            (
                "# P1-P10 Vertical Slice: Q05/Q06/Q10",
                "",
                f"Decision: `{gate['decision']}`",
                "",
                f"P2 mode: `{manifest['p2_mode']}`",
                f"P2 live quality: `{manifest['p2_live_quality']}`",
                f"P11: `{manifest['p11_enabled']}`",
                f"P3 PostgreSQL reader: `{manifest['p3_postgres_reader']}`",
                f"P6 PostgreSQL reader: `{manifest['p6_postgres_reader']}`",
                f"P8 repair reader: `{manifest['p8_postgres_reader']}`",
                "",
                "This is an engineering flow diagnostic only. It does not establish legal quality.",
            )
        )
        + "\n",
    )
    _atomic_write(
        _REVIEW_MARKDOWN,
        "\n".join(
            (
                "# P1-P10 Vertical Slice Review",
                "",
                f"Final decision: `{gate['decision']}`",
                "",
                "P2 live quality: NOT_ESTABLISHED",
                "P2 vertical-slice mode: DETERMINISTIC_FALLBACK",
                "P11: OFF",
                "P3 PostgreSQL reader: REAL",
                "P6 PostgreSQL reader: REAL",
                "P8 repair reader: REAL",
                "",
                *[f"- {reason}" for reason in gate["reasons"]],
                "",
                "No full Set A run or midpoint legal-review workbook was created.",
            )
        )
        + "\n",
    )


def _manifest(active_source_ids: tuple[str, ...], p4_llm_enabled: bool) -> dict[str, object]:
    return {
        "run_type": "P1_P10_VERTICAL_SLICE_Q05_Q06_Q10",
        "run_started_at": datetime.now(UTC).isoformat(),
        "p2_mode": "deterministic_fallback",
        "p2_live_quality": "not_established",
        "strategy_profile_version": _PROFILE_VERSION,
        "active_source_ids": list(active_source_ids),
        "corpus_input_hash": _file_sha256(Path("demo_data")),
        "p4_provider_model": "configured_diagnostic_profile"
        if p4_llm_enabled
        else "not_invoked_default_off",
        "p5_provider_model": "not_invoked_default_off",
        "p7_provider_model": "not_invoked_default_off",
        "p10_provider_model": "deterministic_evidence_bound",
        "prompt_versions": {"p2": "not_invoked", "p4": "not_invoked", "p10": "not_invoked"},
        "feature_flags": {
            "p2_llm": False,
            "p4_llm": p4_llm_enabled,
            "p5_llm": False,
            "p7_llm": False,
            "p11": False,
        },
        "max_repair_cycles": 1,
        "evidence_budget_policy": "3_to_6_eligible_units_no_padding",
        "p11_enabled": False,
        "p3_postgres_reader": "REAL",
        "p6_postgres_reader": "REAL",
        "p8_postgres_reader": "REAL",
    }


def _blocked_report(manifest: dict[str, object], code: str) -> dict[str, object]:
    cases = [
        {"case_id": case.case_id, "execution_status": "NOT_RUN_BLOCKED_RUNTIME"}
        for case in _CASES
    ]
    return {
        "schema_version": "P1-P10-VERTICAL-SLICE-1",
        "run_manifest": manifest,
        "gate": {"decision": "BLOCKED_RUNTIME", "reasons": [code]},
        "cases": cases,
    }


async def _database_snapshot(session_factory) -> dict[str, object]:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(text("SET TRANSACTION READ ONLY"))
            version = (await session.execute(text("SHOW server_version"))).scalar_one()
            document_versions = (
                await session.execute(select(func.count()).select_from(DocumentVersion))
            ).scalar_one()
            chunks = (
                await session.execute(select(func.count()).select_from(DocumentChunk))
            ).scalar_one()
    return {
        "server_version": str(version),
        "document_version_count": int(document_versions),
        "document_chunk_count": int(chunks),
    }


def _case_artifact(case_id: str, trace: Any) -> dict[str, object]:
    context = trace.context
    workspace = trace.discovery.workspace
    coverage_after = trace.coverage_after_repair or trace.coverage_before_repair
    selected_reasons = trace.selection.selection_reasons
    return {
        "case_id": case_id,
        "execution_status": "COMPLETED",
        "question_analysis": {
            "analyzer_mode": context.question_analysis.origin.value,
            "fallback_used": True,
            "sub_intents": [
                {
                    "id": str(item.sub_intent_id),
                    "code": item.code,
                    "description": item.description,
                    "actor_scope": item.actor_scope,
                    "object_scope": item.object_scope,
                    "decomposition_reason_codes": list(item.decomposition_reason_codes),
                }
                for item in context.sub_intents
            ],
        },
        "p3_broad_discovery": {
            "candidate_document_count": len(context.candidate_documents),
            "discovered_document_count": len(context.candidate_documents),
            "raw_candidate_count": workspace.raw_candidate_count,
            "collapsed_unique_versions": len(workspace.documents),
            "provenance_rejected_count": workspace.provenance_filtered_count,
            "quarantine_count": sum(
                item.state.value == "QUARANTINED" for item in context.candidate_documents
            ),
            "lane_counts": {
                "TITLE_METADATA": sum(
                    any(item.lane.value == "TITLE_METADATA" for item in document.observations)
                    for document in workspace.documents
                ),
                "CONTENT_FTS": sum(
                    any(item.lane.value == "CONTENT_FTS" for item in document.observations)
                    for document in workspace.documents
                ),
                "SEMANTIC_VECTOR": sum(
                    any(item.lane.value == "SEMANTIC_VECTOR" for item in document.observations)
                    for document in workspace.documents
                ),
            },
            "documents": [_document_artifact(item) for item in workspace.documents],
        },
        "p4_authority_review": {
            "outcome": trace.authority.outcome.value,
            "assessments": [
                {
                    **_identity_artifact(item.document),
                    "sub_intent_id": str(item.sub_intent_id),
                    "proposed_role": item.proposed_role.value,
                    "validated_role": item.role.value,
                    "authority_state": item.state.value,
                    "applicability": item.applicability.value,
                    "scope_conflict": item.scope_conflict,
                    "filter_reason": None
                    if item.filter_reason is None
                    else item.filter_reason.value,
                }
                for item in context.authority_assessments
            ],
        },
        "p5_authority_families": {
            "families": [
                [str(version_id) for version_id in family.document_version_ids]
                for family in context.authority_families
            ],
            "relation_hint_count": len(context.relation_hints),
            "verified_relation_count": len(context.verified_relations),
            "relation_hints": [
                {
                    "subject_document_version_id": str(item.subject_document_version_id),
                    "object_document_version_id": str(item.object_document_version_id),
                    "relation_type": item.relation_type.value,
                    "verification": item.verification.value,
                }
                for item in context.relation_hints
            ],
            "verified_relations": [
                {
                    "subject_document_version_id": str(item.subject_document_version_id),
                    "object_document_version_id": str(item.object_document_version_id),
                    "relation_type": item.relation_type.value,
                    "verification": item.verification.value,
                    "evidence_locator": item.evidence.locator,
                }
                for item in context.verified_relations
            ],
        },
        "p6_pinpoint_evidence": [
            _evidence_artifact(item) for item in trace.pinpoint.result.evidence_units
        ],
        "p7_coverage_before_repair": _coverage_artifact(trace.coverage_before_repair),
        "p8_repair": {
            **trace.repair.to_public_dict(),
            "target_sub_intent_id": None
            if trace.repair.target_sub_intent_id is None
            else str(trace.repair.target_sub_intent_id),
            "stop_reason": trace.repair.outcome.value,
        },
        "p7_coverage_after_repair": _coverage_artifact(coverage_after),
        "p9_final_evidence": [
            {
                **_evidence_artifact(item),
                "selection_reason": selected_reasons[index],
            }
            for index, item in enumerate(trace.selection.evidence_units)
        ],
        "p10_draft_answer": {
            "draft": context.answer_draft.text,
            "claim_to_evidence": [
                item.model_dump(mode="json") for item in trace.composition.claims
            ],
            "limitations": list(context.limitations),
        },
        "p11_enabled": False,
    }


def _failed_case_artifact(case_id: str, error: Exception) -> dict[str, object]:
    """Record only structural validation metadata, never exception text or request data."""

    failure: dict[str, object] = {"class": type(error).__name__}
    errors = getattr(error, "errors", None)
    if callable(errors):
        details = errors()
        if details:
            first = details[0]
            failure["code"] = str(first.get("type", "UNKNOWN"))
            failure["location"] = [str(part) for part in first.get("loc", ())]
    return {
        "case_id": case_id,
        "execution_status": "PIPELINE_EXECUTION_FAILED",
        "execution_failure": failure,
    }


def _coverage_artifact(result: Any) -> list[dict[str, object]]:
    return [
        {
            "sub_intent_id": str(entry.sub_intent_id),
            "state": entry.state.value,
            "governing_authority_present": entry.governing_authority_present,
            "missing_evidence_codes": [code.value for code in entry.missing_codes],
        }
        for entry in result.entries
    ]


def _document_artifact(document: Any) -> dict[str, object]:
    return {
        **_identity_artifact(document.document),
        "lanes": [item.lane.value for item in document.observations],
        "lane_ranks": {item.lane.value: item.rank for item in document.observations},
    }


def _identity_artifact(document: Any) -> dict[str, object]:
    return {
        "document_id": str(document.document_id),
        "document_version_id": str(document.document_version_id),
        "provenance_record_id": str(document.provenance_record_id),
        "source_id": document.source_id,
    }


def _evidence_artifact(unit: Any) -> dict[str, object]:
    return {
        "document_id": str(unit.evidence.document.document_id),
        "document_version_id": str(unit.evidence.document.document_version_id),
        "provenance_record_id": str(unit.evidence.document.provenance_record_id),
        "source_id": unit.evidence.document.source_id,
        "chunk_id": str(unit.evidence.chunk_id),
        "locator": unit.evidence.locator,
        "authority_role": unit.authority_role.value,
        "sub_intent_ids": [str(value) for value in unit.supported_sub_intent_ids],
    }


def _gate(cases: list[dict[str, object]]) -> dict[str, object]:
    incomplete = [case["case_id"] for case in cases if case["execution_status"] != "COMPLETED"]
    if incomplete:
        return {
            "decision": "FLOW_REWORK",
            "reasons": [f"PIPELINE_EXECUTION_FAILED:{case_id}" for case_id in incomplete],
        }
    missing = [
        case["case_id"]
        for case in cases
        if not case["p3_broad_discovery"]["candidate_document_count"]
        or not case["p6_pinpoint_evidence"]
    ]
    if missing:
        return {
            "decision": "FLOW_REWORK",
            "reasons": [f"NO_PINPOINT_EVIDENCE:{case_id}" for case_id in missing],
        }
    if any(case["p11_enabled"] for case in cases):
        return {"decision": "FLOW_REWORK", "reasons": ["P11_MUST_REMAIN_OFF"]}
    return {
        "decision": "FLOW_PASS",
        "reasons": [
            "All three cases reached P10 through the configured real PostgreSQL reader path.",
            "This decision validates engineering flow only, not legal quality.",
        ],
    }


def _active_source_ids() -> tuple[str, ...]:
    registry = load_registry(SourceSettings().registry_path)
    active = [source.id for source in registry.systems if source.lifecycle == "ACTIVE"]
    corpus = DemoCorpusSettings()
    if corpus.enabled:
        approved = set(corpus.retrieval_source_ids())
        active = [source.id for source in registry.systems if source.id in approved | set(active)]
    if not active:
        raise RuntimeError("VERTICAL_SLICE_ACTIVE_SOURCE_REQUIRED")
    return tuple(active)


def _p4_llm_enabled() -> bool:
    return os.environ.get("P4_LLM_ENABLED", "false").strip().casefold() == "true"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.is_file():
            digest.update(child.relative_to(path).as_posix().encode("utf-8"))
            digest.update(child.read_bytes())
    return digest.hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    report = asyncio.run(run_vertical_slice_diagnostic())
    write_artifacts(report)
    print(report["gate"]["decision"])


if __name__ == "__main__":
    main()

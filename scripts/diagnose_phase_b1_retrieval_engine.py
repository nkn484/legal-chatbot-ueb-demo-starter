"""Run the bounded, read-only Phase B.1 FTS and semantic root-cause diagnostic."""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from legal_chatbot.core.config import Settings  # noqa: E402
from legal_chatbot.db.session import create_engine, create_session_factory  # noqa: E402
from legal_chatbot.diagnostics.phase_b1_fts_probe import ProbeCase, probe_fts_cases  # noqa: E402
from legal_chatbot.diagnostics.phase_b1_latency_probe import (  # noqa: E402
    LatencyProbeCase,
    probe_latency_cases,
)
from legal_chatbot.diagnostics.phase_b1_retrieval_engine import (  # noqa: E402
    SOURCE_IDS,
    UnsafeReportFieldError,
    aggregate_root_cause,
    combine_fts_lane_rows,
    gate_b1,
    parse_expert_workbook,
    prior_phase_b_8425_breakdown,
    q6_trace,
    semantic_latency_root,
    write_reports,
)
from legal_chatbot.documents.orm import (  # noqa: E402
    CitationRecord,
    RetrievalRun,
    ReviewedLegalEffectAssertion,
    ReviewedLegalEffectEvent,
    ReviewedLegalEffectFamily,
    ReviewedLegalEffectImport,
)
from legal_chatbot.documents.quality_candidate_reader import (  # noqa: E402
    PostgresQualityCandidateReader,
)
from legal_chatbot.retrieval.config import RetrievalSettings  # noqa: E402
from legal_chatbot.retrieval.quality_repair.models import RetrievalLane  # noqa: E402
from legal_chatbot.retrieval.quality_repair.ranking import (  # noqa: E402
    build_lane_document_pool,
    fused_diagnostic_top50,
    merge_chunk_candidates,
)
from legal_chatbot.semantic.config import SemanticSettings  # noqa: E402
from legal_chatbot.semantic.fastembed_adapter import FastEmbedSemanticAdapter  # noqa: E402

DEFAULT_WORKBOOK = (
    ROOT / "docs" / "Ket_qua_cham_toan_van_Stress_test_Legal_Chatbot_UEB_2026-08-22.xlsx"
)
DEFAULT_PHASE_B = (
    ROOT / "docs" / "evals" / "quality-retrieval" / "phase-b-candidate-evaluation.json"
)
DEFAULT_MARKDOWN = ROOT / "docs" / "diagnostics" / "phase-b1-retrieval-engine-root-cause.md"


async def _counts(session_factory: Any) -> dict[str, int]:
    """Count only the reviewed registry tables and retrieval/citation write targets."""

    tables = {
        "reviewed_effect_imports": ReviewedLegalEffectImport,
        "reviewed_effect_families": ReviewedLegalEffectFamily,
        "reviewed_effect_assertions": ReviewedLegalEffectAssertion,
        "reviewed_effect_events": ReviewedLegalEffectEvent,
        "retrieval_runs": RetrievalRun,
        "citations": CitationRecord,
    }
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            return {
                name: int((await session.scalar(select(func.count()).select_from(table))) or 0)
                for name, table in tables.items()
            }


def _set_c_zero(path: Path) -> bool:
    """Read frozen Phase B outcome only; absence is intentionally inconclusive."""

    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("set_c", [])
        return bool(rows) and not any(row.get("invariant_failures") for row in rows)
    except (OSError, json.JSONDecodeError):
        return False


def _flags_off() -> dict[str, object]:
    """Inspect declared defaults and static runtime imports without activating a feature."""

    settings = RetrievalSettings()
    defaults = {
        "lexical_repair_enabled": settings.lexical_repair_enabled,
        "semantic_hybrid_enabled": settings.semantic_hybrid_enabled,
        "rerank_enabled": settings.rerank_enabled,
        "metadata_repair_enabled": settings.metadata_repair_enabled,
        "quality_repair_enabled": settings.quality_repair_enabled,
        "quality_title_search_enabled": settings.quality_title_search_enabled,
        "quality_hybrid_fusion_enabled": settings.quality_hybrid_fusion_enabled,
        "quality_query_planner_enabled": settings.quality_query_planner_enabled,
        "quality_dynamic_evidence_enabled": settings.quality_dynamic_evidence_enabled,
        "quality_repair_retrieval_enabled": settings.quality_repair_retrieval_enabled,
        "quality_strategy_disabled": settings.quality_strategy == "disabled",
    }
    service = ast.parse(
        (ROOT / "src" / "legal_chatbot" / "retrieval" / "service.py").read_text(encoding="utf-8")
    )
    imported_modules = {
        module
        for node in ast.walk(service)
        for module in (
            ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            or ([alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
        )
    }
    static = {
        "runtime_service_imports_reviewed_effects": any(
            module.startswith("legal_chatbot.legal_effects") for module in imported_modules
        ),
        "runtime_service_imports_quality_execution": any(
            module.startswith("legal_chatbot.retrieval.quality_repair")
            for module in imported_modules
        ),
    }
    quality_flags_off = all(
        not value for key, value in defaults.items() if key != "quality_strategy_disabled"
    ) and defaults["quality_strategy_disabled"]
    reviewed_effects_off = not any(static.values())
    return {
        "defaults": defaults,
        "static_runtime": static,
        "quality_flags_off": quality_flags_off,
        "reviewed_effects_off": reviewed_effects_off,
        "flags_off": quality_flags_off and reviewed_effects_off,
    }


async def _q6_diagnostic(reader: Any, case: Any, vector: tuple[float, ...]) -> dict[str, object]:
    """Run the explicitly labelled additional Q6 trace using the latency-run vector."""

    read = await reader.read_candidates(case.question, SOURCE_IDS, vector, 50, explain=False)
    merged = merge_chunk_candidates(
        candidate for candidates in read.lane_candidates.values() for candidate in candidates
    )
    pools50 = tuple(
        build_lane_document_pool(merged.candidates, lane, 50) for lane in RetrievalLane
    )
    pools20 = tuple(
        build_lane_document_pool(merged.candidates, lane, 20) for lane in RetrievalLane
    )
    diagnostic50 = fused_diagnostic_top50(pools50).candidates
    pool20 = fused_diagnostic_top50(pools20).candidates
    final3 = pool20[:3]
    expected = frozenset(case.expected_numbers)
    trace = q6_trace(
        expected_numbers=case.expected_numbers,
        diagnostic=diagnostic50,
        pool20=pool20,
        final3=final3,
    )
    wrong_final_numbers = tuple(
        item.identity.document_number_normalized
        for item in final3
        if item.identity.document_number_normalized not in expected
        and item.identity.document_number_normalized is not None
    )
    return {
        "label": "Q6_ADDITIONAL_TRACE_EXPLAIN_FALSE",
        "expected_numbers": list(case.expected_numbers),
        "reader_data_query_count": read.data_query_count,
        "reader_explain_query_count": read.explain_query_count,
        "diagnostic50_count": len(diagnostic50),
        "pool20_count": len(pool20),
        "final3_count": len(final3),
        "trace": list(trace),
        "wrong_final_numbers": list(wrong_final_numbers),
        "complete": (
            len(case.expected_numbers) == 4
            and len(set(case.expected_numbers)) == 4
            and len(trace) == 4
            and tuple(row["document_number"] for row in trace) == case.expected_numbers
            and read.explain_query_count == 0
            and all(row["rejection_reason"] for row in trace)
        ),
    }


def _complete_fields(
    fts_result: Any,
    latency_result: Any,
    lane_rows: tuple[dict[str, object], ...],
    prior: dict[str, object],
    q6: dict[str, object],
    semantic_root: dict[str, object],
) -> dict[str, bool]:
    fts_complete = (
        len(fts_result.cases) == 10
        and len(lane_rows) == 20
        and fts_result.inventory.config_matches_simple
        and fts_result.inventory.content_gin_valid
        and fts_result.inventory.title_gin_valid
        and all(
            lane.natural_filtered_plan.limit_above_scan and lane.or_filtered_plan.limit_above_scan
            for case in fts_result.cases
            for lane in (case.content, case.title)
        )
    )
    latency_complete = (
        len(latency_result.cases) == 10
        and latency_result.counts.embedding_call_count == 11
        and latency_result.counts.timed_embedding_call_count == 10
        and latency_result.counts.database_warmup_call_count == 3
        and latency_result.counts.database_warmup_data_query_count > 0
        and latency_result.counts.database_warmup_explain_query_count > 0
        and latency_result.counts.plan_query_count == 30
        and bool(latency_result.aggregates)
        and latency_result.aggregates["diagnostic_semantic_ms"]["p95_ms"] > 0
        and all(len(case.plans) == 3 for case in latency_result.cases)
    )
    return {
        "parsed_q01_q10": len(fts_result.cases) == 10 and len(latency_result.cases) == 10,
        "fts_probe_complete": fts_complete,
        "latency_probe_complete": latency_complete,
        "lane_rows_complete": len(lane_rows) == 20,
        "prior_phase_b_8425_available": bool(prior.get("available")),
        "semantic_plan_capability_complete": (
            semantic_root.get("code")
            == "SEMANTIC_EXACT_SCAN_FORCED_SEQSCAN_ANN_CAPABILITY_CONFIRMED"
            and semantic_root.get("exact_scans_disabled_plan_count") == 20
            and semantic_root.get("ann_control_plan_count") == 10
            and semantic_root.get("ann_control_hnsw_actual") is True
        ),
        "q6_complete": bool(q6.get("complete")),
    }


async def run(args: argparse.Namespace) -> int:
    engine: Any | None = None
    cases: tuple[Any, ...] = ()
    stage = "PARSE_WORKBOOK"
    try:
        cases = parse_expert_workbook(args.workbook)
        stage = "CREATE_DATABASE"
        engine = create_engine(Settings())  # type: ignore[call-arg]
        session_factory = create_session_factory(engine)
        stage = "COUNT_BEFORE"
        before = await _counts(session_factory)
        reader = PostgresQualityCandidateReader(session_factory)
        semantic = FastEmbedSemanticAdapter(
            SemanticSettings(model_path=args.model_path) if args.model_path else SemanticSettings()
        )
        stage = "FTS_PROBE"
        fts_result = await probe_fts_cases(
            session_factory,
            reader,
            tuple(ProbeCase(case.case_id, case.question, case.expected_numbers) for case in cases),
        )
        stage = "LATENCY_PROBE"
        latency_result = await probe_latency_cases(
            session_factory,
            reader,
            semantic,
            tuple(
                LatencyProbeCase(case.case_id, case.question, case.expected_numbers)
                for case in cases
            ),
            explain=not args.no_explain_analyze,
        )
        stage = "Q6_TRACE"
        q6_case = next(case for case in cases if case.case_id == "Q06")
        q6 = await _q6_diagnostic(reader, q6_case, latency_result.vectors_by_case["Q06"])
        lane_rows = combine_fts_lane_rows(fts_result, latency_result)
        aggregates = {
            lane: aggregate_root_cause(lane_rows, lane) for lane in ("CONTENT_FTS", "TITLE_FTS")
        }
        stage = "COUNT_AFTER"
        after = await _counts(session_factory)
        flags = _flags_off()
        prior = prior_phase_b_8425_breakdown(args.phase_b_json)
        set_c_zero = _set_c_zero(args.phase_b_json)
        semantic_root = semantic_latency_root(latency_result)
        complete_fields = _complete_fields(
            fts_result, latency_result, lane_rows, prior, q6, semantic_root
        )
        complete_fields.update(
            {
                "set_c_frozen_zero": set_c_zero,
                "counts_unchanged": before == after,
                "quality_flags_off": bool(flags["quality_flags_off"]),
                "reviewed_effects_off": bool(flags["reviewed_effects_off"]),
            }
        )
        gate = gate_b1(
            lane_rows=lane_rows,
            lane_aggregates=aggregates,
            complete_fields=complete_fields,
        )
        safe = {
            "report_schema_version": "PHASE-B1-RETRIEVAL-ENGINE-2",
            "gate": gate,
            "inventory": fts_result.inventory.safe(),
            "fts_cases": [case.safe() for case in fts_result.cases],
            "fts_aggregates": aggregates,
            "lane_rows": list(lane_rows),
            "latency": latency_result.to_public_dict(),
            "prior_phase_b_8425_breakdown": prior,
            "semantic_latency_root": semantic_root,
            "q6": q6,
            "invariants": {
                "case_count": len(cases),
                "counts_before": before,
                "counts_after": after,
                "counts_unchanged": before == after,
                "set_c_zero_from_phase_b": set_c_zero,
                "flags": flags,
                "complete_fields": complete_fields,
                "root_lanes_classified": all(
                    row["classification"] != "OTHER" for row in lane_rows
                ),
            },
            "recommendations": [
                "Separately approve an FTS query-construction experiment only if a lane proves it.",
                "Investigate exact semantic SQL/index capability and warm-cache behavior.",
                "Use a warmup-aware evaluation latency protocol.",
            ],
            "no_tuning_performed": True,
        }
        stage = "WRITE_REPORTS"
        write_reports(safe, args.markdown_output, args.json_output)
        print(json.dumps({"gate": gate, "cases": len(cases)}))
        return 0 if gate == "PASS_ROOT_CAUSE_PROVEN" else 2
    except Exception as exc:
        safe = {
            "report_schema_version": "PHASE-B1-RETRIEVAL-ENGINE-2",
            "gate": "NO_GO_B1_INCONCLUSIVE",
            "case_count": len(cases),
            "lane_rows": [],
            "partial_failure": f"SAFE_EXCEPTION_{stage}",
            "failure_type": type(exc).__name__,
        }
        if isinstance(exc, UnsafeReportFieldError):
            safe["failure_field"] = exc.field_name
        try:
            write_reports(safe, args.markdown_output, args.json_output)
        except Exception:
            pass
        print(json.dumps({"gate": "NO_GO_B1_INCONCLUSIVE", "cases": len(cases)}))
        return 2
    finally:
        if engine is not None:
            await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Phase B.1 retrieval-engine diagnostic")
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--phase-b-json", type=Path, default=DEFAULT_PHASE_B)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--no-explain-analyze", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.json_output = args.json_output or args.markdown_output.with_suffix(".json")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())

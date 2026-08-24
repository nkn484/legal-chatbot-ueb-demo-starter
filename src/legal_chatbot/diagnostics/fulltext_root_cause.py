"""Private, read-only evaluator for the controlled Prompt-01 workbook.

The evaluator deliberately keeps controlled text at the execution boundary.
Reports contain approved corpus metadata and controlled expected identities, but
exclude raw questions, queries, chunks, answers, URLs, UUIDs, hydrated text,
and model/prompt payloads.
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import openpyxl
from sqlalchemy import and_, bindparam, func, or_, select, text, true
from sqlalchemy import case as sql_case
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    CorpusCatalogEntry,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    SourceProvenanceRecord,
)
from legal_chatbot.reranking.models import RerankCandidate, RerankRequest, RerankResult
from legal_chatbot.semantic.constants import SEMANTIC_DIMENSION, SEMANTIC_PROFILE_ID
from legal_chatbot.semantic.models import SemanticEmbeddingBatch

SOURCE_IDS = ("VBQPPL", "VNU", "UEB")
RRF_K = 60
NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
CONTROLLED_INPUT_REFERENCE = "CONTROLLED_INPUT_REFERENCE"
NOT_EMITTED = "NOT_EMITTED_BY_PRIVACY_POLICY"
CONTROL_LABELS = {
    "A": "A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION",
    "B": "B_REVIEW_TOPIC_CONTROL",
    "C": "C_ORACLE_SOURCE_SCOPE_CONTROL",
    "D": "D_EXACT_NUMBER_CONTROL",
}


def _serialized_lane(arm: str, kind: str) -> str:
    return f"{CONTROL_LABELS[arm]}_{kind.upper()}"


_DOC_SEPARATORS = re.compile(r"\s*([/\-–—])\s*", re.UNICODE)
_DOCUMENT_NUMBER = re.compile(
    r"\d{1,6}(?:\s*/\s*[\wÀ-ỹĐđ]+(?:\s*[-–—]\s*[\wÀ-ỹĐđ]+)*){1,3}", re.UNICODE
)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_HEADER_SPACE = re.compile(r"\s+")


class QueryEmbedder(Protocol):
    async def embed_query(self, text: str) -> SemanticEmbeddingBatch: ...


class Reranker(Protocol):
    async def rerank(self, request: RerankRequest) -> RerankResult: ...


@dataclass(frozen=True)
class ControlledCase:
    case_id: str
    question: str = field(repr=False)
    topic: str = ""
    expected_documents: tuple[str, ...] = ()
    review_comment: str = field(default="", repr=False)
    review_direction: str = field(default="", repr=False)
    review_failure_class: str = field(default="", repr=False)
    review_priority: str = field(default="", repr=False)
    review_score: str = field(default="", repr=False)
    review_pass: str = field(default="", repr=False)


@dataclass(frozen=True)
class Candidate:
    """Internal metadata plus short-lived IDs; serialisation intentionally omits IDs."""

    chunk_id: object = field(repr=False)
    version_id: object = field(repr=False)
    source_id: str
    document_number: str | None
    title: str | None
    legal_status: str | None
    version_number: int
    ordinal: int
    lexical_score: float | None = None
    semantic_score: float | None = None
    title_score: float | None = None
    reranker_score: float | None = None
    lanes: tuple[str, ...] = ()

    def safe(self, rank: int, *, rejection_codes: tuple[str, ...] = ()) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "document_number": self.document_number,
            "title": self.title,
            "legal_status": self.legal_status,
            "version_number": self.version_number,
            "chunk_ordinal": self.ordinal,
            "lexical_score": self.lexical_score,
            "semantic_score": self.semantic_score,
            "title_score": self.title_score,
            "reranker_score": self.reranker_score,
            "rank": rank,
            "lanes": list(self.lanes),
            "rejection_codes": list(rejection_codes),
        }


def normalize_document_number(value: str) -> str:
    """Normalize only comparison form; callers retain the workbook display value."""

    normalized = unicodedata.normalize("NFC", value).casefold().strip()
    normalized = _DOC_SEPARATORS.sub(r"\1", normalized)
    return "".join(normalized.split())


def _header(value: object) -> str:
    value = unicodedata.normalize("NFC", str(value or "")).casefold().strip()
    return _HEADER_SPACE.sub(" ", value)


def _cell(row: tuple[object, ...], headers: dict[str, int], *names: str) -> str:
    for name in names:
        index = headers.get(_header(name))
        if index is not None and index < len(row) and row[index] is not None:
            return str(row[index]).strip()
    return ""


def _document_values(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    matches = tuple(
        dict.fromkeys(match.group(0).strip() for match in _DOCUMENT_NUMBER.finditer(value))
    )
    if matches:
        return matches
    parts = re.split(r"(?:\r?\n|;|,)", value)
    return tuple(
        dict.fromkeys(
            item.strip()
            for item in parts
            if "/" in item and item.strip() and item.strip()[0].isdigit()
        )
    )


def _sheet_rows(sheet: Any) -> tuple[dict[str, int], list[tuple[object, ...]]]:
    rows = list(sheet.iter_rows(values_only=True))
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if any("câu hỏi" in _header(value) or _header(value) in {"id", "q"} for value in row)
        ),
        -1,
    )
    if header_index < 0:
        raise ValueError("WORKBOOK_HEADER_NOT_FOUND")
    headers = {
        _header(value): index for index, value in enumerate(rows[header_index]) if value is not None
    }
    return headers, rows[header_index + 1 :]


def parse_controlled_workbook(path: Path) -> tuple[ControlledCase, ...]:
    """Parse Q01..Q10 while keeping scorer text separate from retrieval inputs."""

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        question_sheet = workbook["Kết quả 10 câu"]
        scoring_sheet = workbook["Chấm điểm"]
        question_headers, question_rows = _sheet_rows(question_sheet)
        score_headers, score_rows = _sheet_rows(scoring_sheet)
        question_values = [
            _cell(row, question_headers, "Câu hỏi", "Question") for row in question_rows
        ]
        question_values = [value for value in question_values if value]
        questions: dict[str, str] = {}
        has_question_id = any(
            _header(name) in question_headers for name in ("ID", "Q", "Mã câu hỏi")
        )
        if has_question_id:
            for row in question_rows:
                case_id = _cell(row, question_headers, "ID", "Q", "Mã câu hỏi").upper()
                question = _cell(row, question_headers, "Câu hỏi", "Question")
                if re.fullmatch(r"Q(?:0[1-9]|10)", case_id) and question:
                    questions[case_id] = question
        elif len(question_values) == 10:
            questions = {
                f"Q{index:02d}": question for index, question in enumerate(question_values, start=1)
            }
        score: dict[str, tuple[str, tuple[str, ...], str, str, str, str, str, str]] = {}
        for row in score_rows:
            case_id = _cell(row, score_headers, "ID", "Q", "Mã câu hỏi").upper()
            if not re.fullmatch(r"Q(?:0[1-9]|10)", case_id):
                continue
            expected = _document_values(
                _cell(
                    row,
                    score_headers,
                    "Văn bản kỳ vọng chính",
                    "Văn bản kỳ vọng",
                    "Văn bản đúng/kỳ vọng",
                    "Expected documents",
                )
            )
            score[case_id] = (
                _cell(row, score_headers, "Chủ đề", "Topic"),
                expected,
                _cell(
                    row,
                    score_headers,
                    "Nhận xét toàn văn",
                    "Nhận xét",
                    "Failure comments",
                    "Ghi chú",
                ),
                _cell(row, score_headers, "Hướng xử lý", "Direction"),
                _cell(row, score_headers, "Failure class", "Lớp lỗi"),
                _cell(row, score_headers, "Ưu tiên", "Priority"),
                _cell(row, score_headers, "Điểm /10", "Score"),
                _cell(row, score_headers, "PASS/FAIL", "Pass/Fail"),
            )
        required = tuple(f"Q{number:02d}" for number in range(1, 11))
        if tuple(sorted(questions)) != required or tuple(sorted(score)) != required:
            raise ValueError("WORKBOOK_MUST_CONTAIN_EXACTLY_Q01_Q10")
        return tuple(
            ControlledCase(case_id, questions[case_id], *score[case_id]) for case_id in required
        )
    finally:
        workbook.close()


def build_queries(case: ControlledCase, source_labels: tuple[str, ...] = ()) -> dict[str, str]:
    """Create deterministic A/B/C inputs without consulting document-number oracle values."""

    natural = unicodedata.normalize("NFC", case.question).strip()
    topic = unicodedata.normalize("NFC", case.topic).strip()
    terms = "quy định quy chế hướng dẫn"
    expanded = " ".join(part for part in (natural, topic, terms) if part).strip()
    source_terms = " ".join(label for label in source_labels if label in SOURCE_IDS)
    source_aware = " ".join(part for part in (expanded, source_terms) if part).strip()
    return {"A": natural, "B": expanded, "C": source_aware}


def assert_oracle_not_in_model_inputs(
    case: ControlledCase, queries: dict[str, str], inputs: tuple[str, ...]
) -> None:
    """Testable guard against accidental oracle leakage into A/B/C model lanes."""

    expected = {normalize_document_number(item) for item in case.expected_documents}
    leaked = [
        value
        for value in (*queries.values(), *inputs)
        if any(number and number in normalize_document_number(value) for number in expected)
    ]
    # A user can themselves provide a document number.  This evaluator never adds
    # oracle text, but cannot erase an immutable natural question.
    if any(value != case.question for value in leaked):
        raise AssertionError("ORACLE_DOCUMENT_NUMBER_LEAKED_TO_MODEL_INPUT")


def classify_root_cause(
    inventory_status: str,
    *,
    found_top50: bool,
    found_final: bool,
    rerank_demoted: bool = False,
    title_only: bool = False,
    candidate_present: bool = False,
    direct_control_found: bool = False,
    normalization_mismatch: bool = False,
) -> tuple[str, str]:
    """Return a bounded, evidence-led finding and confidence label."""

    if inventory_status in {"MISSING", "NOT_IN_CATALOG"}:
        return "CORPUS_MISSING", "HIGH"
    if inventory_status == "QUARANTINED":
        return "CORPUS_QUARANTINED", "HIGH"
    if found_final:
        return "EXPECTED_DOCUMENT_FOUND_FINAL", "HIGH"
    if rerank_demoted and found_top50:
        return "RERANK_DEMOTION", "HIGH"
    if title_only:
        return "TITLE_NOT_SEARCHED_PRODUCTION", "MEDIUM"
    if found_top50:
        return "CANDIDATE_WINDOW_MISS", "HIGH"
    if direct_control_found:
        return "DIRECT_DOCUMENT_MISS", "HIGH"
    if normalization_mismatch:
        return "NUMBER_NORMALIZATION_MISMATCH", "HIGH"
    if candidate_present:
        return "INSUFFICIENCY_RECHECK_REQUIRED_CANDIDATE_PRESENT", "MEDIUM"
    return "UNRESOLVED", "LOW"


class FulltextRootCauseEvaluator:
    """Read-only evaluator.  All SQL reads happen in repeatable-read, read-only UoWs."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: QueryEmbedder | None,
        reranker: Reranker | None,
        *,
        top_k: int = 50,
        rerank_timeout_seconds: float = 5.0,
    ) -> None:
        if not 1 <= top_k <= 50:
            raise ValueError("top_k must be 1..50")
        self._sessions = session_factory
        self._embedder = embedder
        self._reranker = reranker
        self._top_k = top_k
        self._rerank_timeout = rerank_timeout_seconds

    async def evaluate(self, cases: tuple[ControlledCase, ...]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        blockers: list[str] = []
        for case in cases:
            try:
                results.append(await self._evaluate_case(case))
            except Exception:
                blockers.append(f"{case.case_id}:INFRASTRUCTURE_OR_MODEL_BLOCKER")
                results.append(self._blocked_case(case))
        return {
            "diagnostic": "Prompt-01 fulltext retrieval root-cause (read-only)",
            "privacy": {
                "included": "APPROVED_CORPUS_METADATA_AND_CONTROLLED_EXPECTED_IDENTITIES",
                "excluded": [
                    "RAW_QUESTIONS",
                    "NORMALIZED_OR_GENERATED_QUERY_TEXT",
                    "CHUNKS",
                    "ANSWERS",
                    "URLS",
                    "UUIDS",
                    "HYDRATED_TEXT",
                    "PROMPTS_OR_MODEL_PAYLOADS",
                ],
            },
            "source_scope": list(SOURCE_IDS),
            "cases": results,
            "blockers": blockers,
        }

    async def _evaluate_case(self, case: ControlledCase) -> dict[str, Any]:
        inventory = await self._inventory(case.expected_documents)
        labels = tuple(
            sorted({item["source_id"] for item in inventory if item["source_id"] in SOURCE_IDS})
        )
        queries = build_queries(case, labels)
        assert_oracle_not_in_model_inputs(case, queries, ())
        lexical: dict[str, tuple[Candidate, ...]] = {}
        semantic: dict[str, tuple[Candidate, ...]] = {}
        for arm, query in queries.items():
            lexical[arm] = await self._lexical(query, arm)
            semantic[arm] = await self._semantic(query, arm)
        title = await self._title_metadata(queries["B"])
        exact_control = await self._exact_control(case.expected_documents)
        # Metadata discovery is explicitly not content evidence and cannot affect
        # merged rank, candidate presence, or final selection.
        merged = self._rrf_merge((*lexical.values(), *semantic.values()))
        final, rerank = await self._rerank(queries["A"], semantic["A"])
        documents = self._document_diagnostics(
            case, inventory, lexical, semantic, title, exact_control, merged, final, rerank
        )
        expected_indexed_count = sum(item["is_indexed"] for item in documents)
        production_a_semantic_top50_count = sum(
            item["is_indexed"] and item["lane_ranks"]["A_semantic"] is not None
            for item in documents
        )
        found_top50_count = sum(
            item["is_indexed"] and item["found_merged_top50"] for item in documents
        )
        found_final_count = sum(
            item["is_indexed"] and item["found_final_top3"] for item in documents
        )
        root_causes = sorted({code for item in documents for code in item["root_causes"]})
        rejected = [item for document in documents for item in document["rejected_evidence"]]
        failure_stages = sorted({item["failure_stage"] for item in documents})
        return {
            "case_id": case.case_id,
            "expected_documents": list(case.expected_documents),
            "documents": documents,
            "found_top50_count": found_top50_count,
            "production_a_semantic_top50_count": production_a_semantic_top50_count,
            "expected_indexed_count": expected_indexed_count,
            "found_final_count": found_final_count,
            "found_top50_ratio": f"{found_top50_count}/{expected_indexed_count}",
            "production_a_semantic_top50_ratio": (
                f"{production_a_semantic_top50_count}/{expected_indexed_count}"
            ),
            "found_final_ratio": f"{found_final_count}/{expected_indexed_count}",
            "found_top50": found_top50_count > 0,
            "found_final": found_final_count > 0,
            "root_causes": root_causes,
            "failure_stages": failure_stages,
            "rejected_count": sum(item["rejected_count"] for item in documents),
            "trace": self._trace(
                lexical,
                semantic,
                title,
                exact_control,
                merged,
                semantic["A"][:8],
                final,
                rerank,
                rejected,
                sum(item["rejected_count"] for item in documents),
            ),
        }

    def _blocked_case(self, case: ControlledCase) -> dict[str, Any]:
        return {
            "case_id": case.case_id,
            "expected_documents": list(case.expected_documents),
            "documents": [],
            "found_top50_count": 0,
            "production_a_semantic_top50_count": 0,
            "expected_indexed_count": 0,
            "found_final_count": 0,
            "found_top50_ratio": "0/0",
            "production_a_semantic_top50_ratio": "0/0",
            "found_final_ratio": "0/0",
            "found_top50": False,
            "found_final": False,
            "root_causes": ["UNRESOLVED"],
            "failure_stages": ["INFRASTRUCTURE_BLOCKER"],
            "rejected_count": 0,
            "trace": self._trace(
                {}, {}, (), (), (), (), (), {"fallback": True, "reason": "BLOCKED"}, [], 0
            ),
        }

    def _document_diagnostics(
        self,
        case: ControlledCase,
        inventory: list[dict[str, Any]],
        lexical: dict[str, tuple[Candidate, ...]],
        semantic: dict[str, tuple[Candidate, ...]],
        title: tuple[Candidate, ...],
        exact: tuple[Candidate, ...],
        merged: tuple[Candidate, ...],
        final: tuple[Candidate, ...],
        rerank: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Compare each oracle document after retrieval; never feed it into A/B/C."""

        output: list[dict[str, Any]] = []
        all_candidates = tuple(
            item for rows in (*lexical.values(), *semantic.values()) for item in rows
        )
        for display in case.expected_documents:
            number = normalize_document_number(display)
            inventory_rows = [
                item
                for item in inventory
                if normalize_document_number(item["expected_display_number"]) == number
            ]
            status = self._document_inventory_status(inventory_rows)
            lane_ranks = {
                f"{arm}_lexical": self._rank_for(rows, number) for arm, rows in lexical.items()
            }
            lane_ranks.update(
                {f"{arm}_semantic": self._rank_for(rows, number) for arm, rows in semantic.items()}
            )
            title_rank = self._rank_for(title, number)
            exact_rank = self._rank_for(exact, number)
            merged_rank = self._rank_for(merged, number)
            pre_rerank_rank = self._rank_for(semantic["A"][:8], number)
            final_rank = self._rank_for(final, number)
            found_top50 = merged_rank is not None
            found_final = final_rank is not None
            if found_top50 and not any(rank is not None for rank in lane_ranks.values()):
                raise AssertionError("MERGED_CANDIDATE_MUST_HAVE_CONTENT_LANE")
            rerank_demoted = (
                pre_rerank_rank is not None and not found_final and not rerank["fallback"]
            )
            content_ranks = tuple(lane_ranks.values())
            title_only = title_rank is not None and not any(
                rank is not None for rank in content_ranks
            )
            candidate_present = any(
                rank is not None for rank in (*content_ranks, title_rank, exact_rank, merged_rank)
            )
            primary, confidence = classify_root_cause(
                status,
                found_top50=found_top50,
                found_final=found_final,
                rerank_demoted=rerank_demoted,
                title_only=title_only,
                candidate_present=candidate_present,
                direct_control_found=exact_rank is not None,
                normalization_mismatch=any(item["raw_exact_mismatch"] for item in inventory_rows),
            )
            roots = [primary]
            if len(inventory_rows) > 1:
                roots.append("DUPLICATE_CATALOG_IDENTITY")
            if any(item["raw_exact_mismatch"] for item in inventory_rows):
                roots.append("NUMBER_NORMALIZATION_MISMATCH")
            capability_codes = self._capability_codes(case.review_failure_class)
            roots.extend(capability_codes)
            if capability_codes:
                confidence = "HIGH"
            if (
                self._review_requests_insufficiency(case)
                and status == "INDEXED"
                and candidate_present
                and not found_final
            ):
                roots.append("INSUFFICIENCY_RECHECK_REQUIRED_CANDIDATE_PRESENT")
            roots = list(dict.fromkeys(roots))
            rejected, rejected_count = self._rejected_for_document(
                number, all_candidates, title, merged, semantic["A"][:8], final, rerank
            )
            output.append(
                {
                    "expected_display_number": display,
                    "inventory": inventory_rows,
                    "inventory_classification": status,
                    "duplicates": len(inventory_rows) > 1,
                    "raw_normalization_mismatch": any(
                        item["raw_exact_mismatch"] for item in inventory_rows
                    ),
                    "is_indexed": any(item["retrievable_indexed"] for item in inventory_rows),
                    "lane_ranks": lane_ranks,
                    "title_metadata_rank": title_rank,
                    "d_exact_control_rank": exact_rank,
                    "merged_top50_rank": merged_rank,
                    "pre_rerank_semantic_top8_rank": pre_rerank_rank,
                    "post_rerank_final_top3_rank": final_rank,
                    "found_merged_diagnostic_top50": found_top50,
                    "found_merged_top50": found_top50,
                    "found_final_top3": found_final,
                    "failure_stage": self._failure_stage(
                        status, found_top50, found_final, rerank_demoted
                    ),
                    "root_causes": roots,
                    "confidence": confidence,
                    "rejected_evidence": rejected,
                    "rejected_count": rejected_count,
                }
            )
        return output

    @staticmethod
    def _rank_for(rows: tuple[Candidate, ...], number: str) -> int | None:
        return next(
            (
                rank
                for rank, item in enumerate(rows, 1)
                if normalize_document_number(item.document_number or "") == number
            ),
            None,
        )

    @staticmethod
    def _document_inventory_status(inventory_rows: list[dict[str, Any]]) -> str:
        if any(item["retrievable_indexed"] for item in inventory_rows):
            return "INDEXED"
        statuses = {item["classification"] for item in inventory_rows}
        for status in ("QUARANTINED", "MISSING", "NOT_IN_CATALOG"):
            if status in statuses:
                return status
        return "MISSING"

    @staticmethod
    def _capability_codes(failure_class: str) -> list[str]:
        code = failure_class.upper()
        output: list[str] = []
        if "NO_DECOMPOSITION" in code or "SUB_INTENT" in code:
            output.append("REVIEW_HYPOTHESIS_MULTI_INTENT_CAPABILITY_ABSENT")
        if "HIERARCHY" in code:
            output.append("REVIEW_HYPOTHESIS_LEGAL_HIERARCHY_CAPABILITY_ABSENT")
        if "VERSION" in code or "AMENDMENT" in code:
            output.append("REVIEW_HYPOTHESIS_VERSION_STATUS_CAPABILITY_ABSENT")
        return output

    @staticmethod
    def _review_requests_insufficiency(case: ControlledCase) -> bool:
        review = f"{case.review_failure_class} {case.review_comment}".casefold()
        return any(
            token in review
            for token in (
                "insufficient",
                "refusal",
                "không đủ",
                "từ chối",
                "tu choi",
                "thiếu bằng chứng",
            )
        )

    def _rejected_for_document(
        self,
        number: str,
        candidates: tuple[Candidate, ...],
        title: tuple[Candidate, ...],
        merged: tuple[Candidate, ...],
        pre_rerank: tuple[Candidate, ...],
        final: tuple[Candidate, ...],
        rerank: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        def matching(item: Candidate) -> bool:
            return normalize_document_number(item.document_number or "") == number

        output: list[dict[str, Any]] = []
        represented: set[tuple[str, str]] = set()
        rejected_count = 0

        def add(items: tuple[Candidate, ...], code: str) -> None:
            nonlocal rejected_count
            for rank, item in enumerate(items, 1):
                if not matching(item):
                    continue
                rejected_count += 1
                lane = ";".join(item.lanes) or "UNLABELED"
                key = (code, lane)
                if key not in represented:
                    represented.add(key)
                    output.append(item.safe(rank, rejection_codes=(code,)))

        if self._rank_for(title, number) is not None:
            add(title, "METADATA_ONLY_NOT_EVIDENCE")
        if (
            self._rank_for(candidates, number) is not None
            and self._rank_for(merged, number) is None
        ):
            add(candidates, "RANK_CUTOFF")
        if self._rank_for(pre_rerank, number) is not None and self._rank_for(final, number) is None:
            code = "RERANK_DEMOTION" if not rerank["fallback"] else "RANK_CUTOFF"
            add(pre_rerank, code)
        versions: set[object] = set()
        chunks: set[object] = set()
        for rank, item in enumerate(candidates, 1):
            if not matching(item):
                continue
            if item.chunk_id in chunks:
                continue
            chunks.add(item.chunk_id)
            if item.version_id in versions:
                rejected_count += 1
                lane = ";".join(item.lanes) or "UNLABELED"
                key = ("DOCUMENT_VERSION_COLLAPSE", lane)
                if key not in represented:
                    represented.add(key)
                    output.append(item.safe(rank, rejection_codes=("DOCUMENT_VERSION_COLLAPSE",)))
            versions.add(item.version_id)
        return output, rejected_count

    @staticmethod
    def _case_inventory_status(inventory: list[dict[str, Any]]) -> str:
        statuses = {item["classification"] for item in inventory}
        if "INDEXED" in statuses:
            return "INDEXED"
        if "QUARANTINED" in statuses:
            return "QUARANTINED"
        if "DUPLICATE_OR_AMBIGUOUS" in statuses:
            return "DUPLICATE_OR_AMBIGUOUS"
        if "NOT_IN_CATALOG" in statuses:
            return "NOT_IN_CATALOG"
        return "MISSING"

    @staticmethod
    def _failure_stage(status: str, top50: bool, final: bool, rerank_demoted: bool) -> str:
        if status != "INDEXED":
            return "CATALOG_INVENTORY"
        if final:
            return "FINAL_SELECTION"
        if rerank_demoted:
            return "RERANK"
        if top50:
            return "RANK_CUTOFF"
        return "CANDIDATE_SELECTION"

    @staticmethod
    def _trace(
        lexical: dict[str, tuple[Candidate, ...]],
        semantic: dict[str, tuple[Candidate, ...]],
        title: tuple[Candidate, ...],
        exact_control: tuple[Candidate, ...],
        merged: tuple[Candidate, ...],
        pre_rerank: tuple[Candidate, ...],
        final: tuple[Candidate, ...],
        rerank: dict[str, Any],
        rejected: list[dict[str, Any]],
        rejected_count: int,
    ) -> dict[str, Any]:
        safe_lanes = {
            f"{arm}_lexical": [item.safe(rank) for rank, item in enumerate(rows, 1)]
            for arm, rows in lexical.items()
        }
        safe_lanes.update(
            {
                f"{arm}_semantic": [item.safe(rank) for rank, item in enumerate(rows, 1)]
                for arm, rows in semantic.items()
            }
        )
        return {
            "raw_question": CONTROLLED_INPUT_REFERENCE,
            "normalized_question": NOT_EMITTED,
            "intent": NOT_IMPLEMENTED,
            "entities": NOT_IMPLEMENTED,
            "org": NOT_IMPLEMENTED,
            "legal_topics": NOT_IMPLEMENTED,
            "sub_intents": NOT_IMPLEMENTED,
            "query_plan": NOT_IMPLEMENTED,
            "expanded_queries": NOT_EMITTED,
            "corpus_insight_policy": NOT_IMPLEMENTED,
            "corpus_insight_decision": NOT_IMPLEMENTED,
            "source_scope": list(SOURCE_IDS),
            "metadata_filters": {
                "title": "BOUNDED_TOKEN_TITLE_MATCH_DIAGNOSTIC_ONLY",
                "exact_number": "D_CONTROL_ONLY",
            },
            "filter_descriptions": ["LATEST_INGESTED", "STRICT_TLS", "EXACT_E5_PROFILE"],
            "version_filters": "LATEST_INGESTED_ONLY",
            "effectivity_filters": {"legal_effect_resolver": NOT_IMPLEMENTED},
            "controls": {
                CONTROL_LABELS["A"]: NOT_EMITTED,
                CONTROL_LABELS["B"]: NOT_EMITTED,
                CONTROL_LABELS["C"]: NOT_EMITTED,
                CONTROL_LABELS["D"]: CONTROLLED_INPUT_REFERENCE,
            },
            "control_methodology": {
                CONTROL_LABELS["B"]: "REVIEW_SHEET_TOPIC_SENSITIVITY_TEST_NOT_GENERALIZATION",
                CONTROL_LABELS["C"]: (
                    "ORACLE_EXPECTED_INVENTORY_SOURCE_LABEL_SENSITIVITY_TEST_NOT_PRODUCTION_EVIDENCE"
                ),
            },
            "candidate_lanes": {
                _serialized_lane(arm, kind): safe_lanes.get(f"{arm}_{kind}", [])
                for arm in ("A", "B", "C")
                for kind in ("lexical", "semantic")
            },
            "lexical_candidates": {
                CONTROL_LABELS[arm]: safe_lanes.get(f"{arm}_lexical", []) for arm in ("A", "B", "C")
            },
            "semantic_candidates": {
                CONTROL_LABELS[arm]: safe_lanes.get(f"{arm}_semantic", [])
                for arm in ("A", "B", "C")
            },
            "title_metadata_only": [
                item.safe(rank, rejection_codes=("METADATA_ONLY_NOT_EVIDENCE",))
                for rank, item in enumerate(title, 1)
            ],
            "D_EXACT_NUMBER_CONTROL_candidates": [
                item.safe(rank) for rank, item in enumerate(exact_control, 1)
            ],
            "merged_diagnostic_top50": [item.safe(rank) for rank, item in enumerate(merged, 1)],
            "merged_diagnostic_top50_method": "RRF_ACROSS_A_B_C_CONTROLS_AVAILABILITY_ONLY",
            "pre_rerank": [item.safe(rank) for rank, item in enumerate(pre_rerank, 1)],
            "post_rerank": [item.safe(rank) for rank, item in enumerate(final, 1)],
            "selected_evidence_diagnostic_final_top3": [
                item.safe(rank) for rank, item in enumerate(final, 1)
            ],
            "selected_evidence": [item.safe(rank) for rank, item in enumerate(final, 1)],
            "rejected_evidence": rejected,
            "rejected_count": rejected_count,
            "rerank": rerank,
            "final_answer_state": "NOT_RUN_DIAGNOSTIC_ONLY",
        }

    async def _read(self, callback: Any) -> Any:
        async with self._sessions() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                await session.execute(text("SET TRANSACTION READ ONLY"))
                return await callback(session)

    @staticmethod
    def _latest():
        return (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == LegalDocument.id)
            .correlate(LegalDocument)
            .scalar_subquery()
        )

    @staticmethod
    def _strict() -> Any:
        return (
            select(SourceProvenanceRecord.id)
            .where(
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
                SourceProvenanceRecord.provenance_type.in_(("source_fetch", "manual_snapshot")),
            )
            .correlate(DocumentVersion)
            .exists()
        )

    def _base(self) -> Any:
        return (
            select(
                DocumentChunk.id,
                DocumentChunk.document_version_id,
                LegalDocument.source_id,
                DocumentVersion.document_number,
                DocumentVersion.title,
                DocumentVersion.legal_status,
                DocumentVersion.version_number,
                DocumentChunk.ordinal,
            )
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .where(
                LegalDocument.source_id.in_(SOURCE_IDS),
                DocumentVersion.version_number == self._latest(),
                self._strict(),
            )
        )

    @staticmethod
    def _candidate(row: Any, *, lane: str, score_name: str, score: float | None) -> Candidate:
        values: dict[str, float | None] = {
            "lexical_score": None,
            "semantic_score": None,
            "title_score": None,
        }
        values[score_name] = score
        return Candidate(*row[:8], **values, lanes=(lane,))

    async def _lexical(self, query: str, arm: str) -> tuple[Candidate, ...]:
        parsed = select(
            func.websearch_to_tsquery(
                text("'pg_catalog.simple'::regconfig"), bindparam("query")
            ).label("parsed_query")
        ).cte("parsed_query")
        score = func.ts_rank_cd(DocumentChunk.search_vector, parsed.c.parsed_query)
        statement = (
            self._base()
            .add_columns(score)
            .join(parsed, true())
            .where(
                func.numnode(parsed.c.parsed_query) > 0,
                DocumentChunk.search_vector.op("@@")(parsed.c.parsed_query),
            )
            .order_by(score.desc(), DocumentChunk.ordinal.asc(), DocumentChunk.id.asc())
            .limit(self._top_k)
        )

        async def execute(session: AsyncSession) -> tuple[Candidate, ...]:
            rows = (await session.execute(statement, {"query": query})).all()
            return tuple(
                self._candidate(
                    row, lane=f"{arm}_LEXICAL", score_name="lexical_score", score=float(row[8])
                )
                for row in rows
            )

        return await self._read(execute)

    async def _semantic(self, query: str, arm: str) -> tuple[Candidate, ...]:
        if self._embedder is None:
            return ()
        batch = await self._embedder.embed_query(query)
        if not isinstance(batch, SemanticEmbeddingBatch) or len(batch.vectors) != 1:
            return ()
        vector = batch.vectors[0]
        if len(vector) != SEMANTIC_DIMENSION:
            return ()
        distance = ChunkEmbedding.embedding.cosine_distance(list(vector))
        score = (1 - distance).label("semantic_score")
        statement = (
            self._base()
            .join(
                ChunkEmbedding,
                and_(
                    ChunkEmbedding.document_chunk_id == DocumentChunk.id,
                    ChunkEmbedding.embedding_model_id == SEMANTIC_PROFILE_ID,
                    ChunkEmbedding.embedding_kind == "semantic",
                    ChunkEmbedding.dimension == SEMANTIC_DIMENSION,
                ),
            )
            .add_columns(score)
            .order_by(distance.asc(), DocumentChunk.ordinal.asc(), DocumentChunk.id.asc())
            .limit(self._top_k)
        )

        async def execute(session: AsyncSession) -> tuple[Candidate, ...]:
            await session.execute(text("SET LOCAL enable_indexscan = off"))
            await session.execute(text("SET LOCAL enable_bitmapscan = off"))
            rows = (await session.execute(statement)).all()
            return tuple(
                self._candidate(
                    row, lane=f"{arm}_SEMANTIC", score_name="semantic_score", score=float(row[8])
                )
                for row in rows
            )

        return await self._read(execute)

    async def _title_metadata(self, query: str) -> tuple[Candidate, ...]:
        tokens = tuple(dict.fromkeys(token.casefold() for token in _TOKEN.findall(query)))[:8]
        if not tokens:
            return ()
        predicates = [func.lower(DocumentVersion.title).contains(token) for token in tokens]
        score = sql_case((predicates[0], 1), else_=0)
        for predicate in predicates[1:]:
            score = score + sql_case((predicate, 1), else_=0)
        statement = (
            self._base()
            .add_columns(score.label("title_score"))
            .where(or_(*predicates))
            .order_by(score.desc(), DocumentChunk.ordinal.asc(), DocumentChunk.id.asc())
            .limit(self._top_k)
        )

        async def execute(session: AsyncSession) -> tuple[Candidate, ...]:
            rows = (await session.execute(statement)).all()
            return tuple(
                self._candidate(
                    row, lane="TITLE_METADATA", score_name="title_score", score=float(row[8])
                )
                for row in rows
            )

        return await self._read(execute)

    async def _exact_control(self, display_numbers: tuple[str, ...]) -> tuple[Candidate, ...]:
        expected = tuple(
            dict.fromkeys(normalize_document_number(value) for value in display_numbers)
        )

        async def execute(session: AsyncSession) -> tuple[Candidate, ...]:
            statement = self._base().order_by(
                LegalDocument.source_id.asc(),
                DocumentVersion.document_number.asc(),
                DocumentVersion.version_number.desc(),
                DocumentChunk.ordinal.asc(),
                DocumentChunk.id.asc(),
            )
            rows = (await session.execute(statement)).all()
            by_number: dict[str, Any] = {}
            for row in rows:
                number = normalize_document_number(row[3] or "")
                if number in expected and number not in by_number:
                    by_number[number] = row
            return tuple(
                self._candidate(
                    by_number[number],
                    lane="D_EXACT_NUMBER_CONTROL",
                    score_name="title_score",
                    score=1.0,
                )
                for number in expected
                if number in by_number
            )

        return await self._read(execute)

    async def _inventory(self, display_numbers: tuple[str, ...]) -> list[dict[str, Any]]:
        expected = {normalize_document_number(value): value for value in display_numbers}

        async def execute(session: AsyncSession) -> list[dict[str, Any]]:
            entries = (await session.execute(select(CorpusCatalogEntry))).scalars().all()
            chunks = (
                select(DocumentChunk.document_version_id, func.count(DocumentChunk.id))
                .group_by(DocumentChunk.document_version_id)
                .subquery()
            )
            linked = (
                await session.execute(
                    select(
                        DocumentVersion.id, DocumentVersion.document_number, chunks.c.count
                    ).outerjoin(chunks, chunks.c.document_version_id == DocumentVersion.id)
                )
            ).all()
            chunk_counts = {row[0]: int(row[2] or 0) for row in linked}
            output: list[dict[str, Any]] = []
            for normalized, display in expected.items():
                matches = [
                    entry
                    for entry in entries
                    if normalize_document_number(entry.document_number or "") == normalized
                ]
                if not matches:
                    output.append(
                        {
                            "expected_display_number": display,
                            "classification": "NOT_IN_CATALOG",
                            "source_id": None,
                            "catalog_display_number": None,
                            "title": None,
                            "processing_status": None,
                            "reason_code": None,
                            "legal_status": None,
                            "linked_document": False,
                            "linked_version": False,
                            "chunk_count": 0,
                            "exact_normalized_match": False,
                            "raw_exact_mismatch": False,
                            "retrievable_indexed": False,
                            "duplicate_catalog_identity": False,
                        }
                    )
                    continue
                for entry in matches:
                    duplicate = len(matches) > 1
                    linked_version = entry.document_version_id is not None
                    retrievable_indexed = (
                        entry.processing_status == "INDEXED"
                        and entry.legal_document_id is not None
                        and linked_version
                        and chunk_counts.get(entry.document_version_id, 0) > 0
                    )
                    classification = (
                        "INDEXED"
                        if retrievable_indexed
                        else (
                            "QUARANTINED" if entry.processing_status == "QUARANTINED" else "MISSING"
                        )
                    )
                    output.append(
                        {
                            "expected_display_number": display,
                            "classification": classification,
                            "source_id": entry.source_id,
                            "catalog_display_number": entry.document_number,
                            "title": entry.title,
                            "processing_status": entry.processing_status,
                            "reason_code": entry.reason_code,
                            "legal_status": entry.legal_status,
                            "linked_document": entry.legal_document_id is not None,
                            "linked_version": linked_version,
                            "chunk_count": chunk_counts.get(entry.document_version_id, 0),
                            "exact_normalized_match": True,
                            "raw_exact_mismatch": entry.document_number != display,
                            "retrievable_indexed": retrievable_indexed,
                            "duplicate_catalog_identity": duplicate,
                        }
                    )
            return output

        return await self._read(execute)

    @staticmethod
    def _rrf_merge(lanes: tuple[tuple[Candidate, ...], ...]) -> tuple[Candidate, ...]:
        scores: dict[object, float] = defaultdict(float)
        rows: dict[object, Candidate] = {}
        for lane in lanes:
            for rank, candidate in enumerate(lane, 1):
                scores[candidate.chunk_id] += 1 / (RRF_K + rank)
                old = rows.get(candidate.chunk_id)
                if old is None:
                    rows[candidate.chunk_id] = candidate
                else:
                    rows[candidate.chunk_id] = Candidate(
                        **{
                            **old.__dict__,
                            "lanes": tuple(sorted(set((*old.lanes, *candidate.lanes)))),
                        }
                    )
        chunk_order = sorted(scores, key=lambda key: (-scores[key], str(key)))
        by_version: set[object] = set()
        selected: list[Candidate] = []
        for chunk_id in chunk_order:
            candidate = rows[chunk_id]
            if candidate.version_id in by_version:
                continue
            by_version.add(candidate.version_id)
            selected.append(candidate)
        return tuple(selected[:50])

    async def _rerank(
        self, query: str, semantic: tuple[Candidate, ...]
    ) -> tuple[tuple[Candidate, ...], dict[str, Any]]:
        # Production collapses an exact semantic top-eight window to document versions.
        window = semantic[:8]
        versions: list[Candidate] = []
        seen: set[object] = set()
        for candidate in window:
            if candidate.version_id not in seen:
                seen.add(candidate.version_id)
                versions.append(candidate)
        if self._reranker is None or not versions:
            return tuple(versions[:3]), {
                "fallback": True,
                "reason": "RERANKER_UNAVAILABLE",
                "pre_window_versions": len(versions),
                "hydration": NOT_EMITTED,
            }
        hydrated = await self._hydrate_for_rerank(versions)
        request = RerankRequest(
            query=query,
            candidates=tuple(
                RerankCandidate(chunk_id=str(item.chunk_id), text=text) for item, text in hydrated
            ),
        )
        try:
            result = await asyncio.wait_for(
                self._reranker.rerank(request), timeout=self._rerank_timeout
            )
            if result.candidate_ids != tuple(str(item.chunk_id) for item in versions) or len(
                result.scores
            ) != len(versions):
                raise ValueError("RERANK_ALIGNMENT_INVALID")
            ranked = sorted(
                zip(versions, result.scores, strict=True),
                key=lambda item: (-item[1], item[0].ordinal, str(item[0].chunk_id)),
            )
            selected = tuple(
                Candidate(**{**item.__dict__, "reranker_score": float(score)})
                for item, score in ranked[:3]
            )
            return selected, {
                "fallback": False,
                "reason": None,
                "pre_window_versions": len(versions),
                "hydration": NOT_EMITTED,
            }
        except Exception:
            return tuple(versions[:3]), {
                "fallback": True,
                "reason": "RERANKER_FAILURE",
                "pre_window_versions": len(versions),
                "hydration": NOT_EMITTED,
            }

    async def _hydrate_for_rerank(self, candidates: list[Candidate]) -> list[tuple[Candidate, str]]:
        needed: dict[object, set[int]] = {}
        for candidate in candidates:
            needed.setdefault(candidate.version_id, set()).update(
                (max(0, candidate.ordinal - 1), candidate.ordinal, candidate.ordinal + 1)
            )
        predicates = [
            and_(DocumentChunk.document_version_id == version, DocumentChunk.ordinal.in_(ordinals))
            for version, ordinals in needed.items()
        ]

        async def execute(session: AsyncSession) -> list[tuple[Candidate, str]]:
            rows = (
                await session.execute(
                    select(
                        DocumentChunk.document_version_id,
                        DocumentChunk.ordinal,
                        DocumentChunk.content_text,
                    ).where(or_(*predicates))
                )
            ).all()
            texts = {(row[0], row[1]): row[2] for row in rows}
            return [
                (
                    candidate,
                    "\n".join(
                        texts.get((candidate.version_id, ordinal), "")
                        for ordinal in (
                            candidate.ordinal - 1,
                            candidate.ordinal,
                            candidate.ordinal + 1,
                        )
                    )[:2000],
                )
                for candidate in candidates
            ]

        return await self._read(execute)


def write_reports(
    result: dict[str, Any],
    output_dir: Path,
    *,
    markdown_path: Path | None = None,
    json_path: Path | None = None,
    csv_path: Path | None = None,
) -> tuple[Path, Path, Path]:
    """Write safe JSON/CSV/Markdown reports; stdout remains content-free."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = json_path or output_dir / "stress-test-fulltext-root-cause.json"
    csv_path = csv_path or output_dir / "stress-test-fulltext-root-cause.csv"
    markdown_path = markdown_path or output_dir / "stress-test-fulltext-root-cause.md"
    for path in (markdown_path, json_path, csv_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    safe_cases = [_safe_case(case) for case in result["cases"]]
    aggregate = _aggregate_availability(safe_cases)
    safe_result = {
        "diagnostic": result.get("diagnostic", "Prompt-01 fulltext retrieval root-cause"),
        "privacy": result.get(
            "privacy",
            {
                "included": "APPROVED_CORPUS_METADATA_AND_CONTROLLED_EXPECTED_IDENTITIES",
                "excluded": [
                    "RAW_QUESTIONS",
                    "NORMALIZED_OR_GENERATED_QUERY_TEXT",
                    "CHUNKS",
                    "ANSWERS",
                    "URLS",
                    "UUIDS",
                    "HYDRATED_TEXT",
                    "PROMPTS_OR_MODEL_PAYLOADS",
                ],
            },
        ),
        "source_scope": result.get("source_scope", list(SOURCE_IDS)),
        "cases": safe_cases,
        "aggregate_availability": aggregate,
        "blockers": result["blockers"],
    }
    json_path.write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
    rows: list[dict[str, Any]] = []
    table_rows: list[str] = []
    case_sections: list[list[str]] = []
    for case in safe_cases:
        for document in case.get("documents", []):
            lane_ranks = document["lane_ranks"]
            rows.append(
                {
                    "case_id": case["case_id"],
                    "expected_document": document["expected_display_number"],
                    "inventory_classification": document["inventory_classification"],
                    "duplicates": document["duplicates"],
                    "raw_normalization_mismatch": document["raw_normalization_mismatch"],
                    "a_production_equivalent_natural_question_lexical_rank": lane_ranks.get(
                        _serialized_lane("A", "lexical")
                    ),
                    "b_review_topic_control_lexical_rank": lane_ranks.get(
                        _serialized_lane("B", "lexical")
                    ),
                    "c_oracle_source_scope_control_lexical_rank": lane_ranks.get(
                        _serialized_lane("C", "lexical")
                    ),
                    "a_production_equivalent_natural_question_semantic_rank": lane_ranks.get(
                        _serialized_lane("A", "semantic")
                    ),
                    "b_review_topic_control_semantic_rank": lane_ranks.get(
                        _serialized_lane("B", "semantic")
                    ),
                    "c_oracle_source_scope_control_semantic_rank": lane_ranks.get(
                        _serialized_lane("C", "semantic")
                    ),
                    "title_metadata_rank": document["title_metadata_rank"],
                    "d_exact_control_rank": document["d_exact_control_rank"],
                    "merged_diagnostic_top50_rank": document["merged_top50_rank"],
                    "pre_rerank_semantic_top8_rank": document["pre_rerank_semantic_top8_rank"],
                    "post_rerank_final_top3_rank": document["post_rerank_final_top3_rank"],
                    "failure_stage": document["failure_stage"],
                    "root_causes": ";".join(document["root_causes"]),
                    "confidence": document["confidence"],
                    "rejected_count": document.get("rejected_count", 0),
                }
            )
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["case_id"])
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Prompt-01 fulltext root-cause diagnostic",
        "",
        "## Methodology caveat",
        (
            f"{CONTROL_LABELS['B']} uses review-sheet topic and {CONTROL_LABELS['C']} uses oracle "
            "expected-inventory source labels. They are controlled diagnostic sensitivity tests, "
            "not independent generalization or production-design evidence. "
            "`merged_diagnostic_top50` is RRF across A/B/C controls and shows candidate "
            "availability "
            "only; it is not production recall."
        ),
        "",
        "## Aggregate availability",
        (
            "Production-equivalent A semantic top50 availability: "
            f"{aggregate['production_equivalent_natural_question_semantic_top50']['ratio']}."
        ),
        (
            "Controlled merged diagnostic top50 availability: "
            f"{aggregate['controlled_merged_diagnostic_top50']['ratio']}."
        ),
        (
            "Production-equivalent final top3 availability: "
            f"{aggregate['production_equivalent_final_top3']['ratio']}."
        ),
        "",
        (
            "| Q | Expected direct docs | Found top50? | Found final? | Wrong docs selected "
            "| Failure stage | Root cause | Confidence |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for case in safe_cases:
        expected = "; ".join(case["expected_documents"])
        final_numbers = {
            row["document_number"]
            for row in case["trace"].get("selected_evidence_diagnostic_final_top3", [])
        }
        wrong = (
            "; ".join(
                sorted(
                    number
                    for number in final_numbers
                    if number
                    and normalize_document_number(number)
                    not in {normalize_document_number(item) for item in case["expected_documents"]}
                )
            )
            or "NONE"
        )
        table_row = "| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            case["case_id"],
            expected,
            case.get("found_top50_ratio", "0/0"),
            case.get("found_final_ratio", "0/0"),
            wrong,
            ";".join(case.get("failure_stages", []))
            or ";".join(
                sorted(
                    item.get("failure_stage", "UNRESOLVED") for item in case.get("documents", [])
                )
            )
            or "INFRASTRUCTURE_BLOCKER",
            ";".join(case.get("root_causes", ["UNRESOLVED"])),
            ";".join(sorted({item["confidence"] for item in case.get("documents", [])})) or "LOW",
        )
        table_rows.append(table_row)
        trace_fields = (
            "intent",
            "entities",
            "org",
            "legal_topics",
            "sub_intents",
            "query_plan",
            "expanded_queries",
            "corpus_insight_policy",
        )
        trace_summary = {key: case["trace"].get(key, NOT_IMPLEMENTED) for key in trace_fields}
        documents = case.get("documents", [])
        lane_specs = tuple(
            (arm, kind) for arm in ("A", "B", "C") for kind in ("lexical", "semantic")
        )
        lane_hits = {
            _serialized_lane(arm, kind): sum(
                item.get("is_indexed", False)
                and item["lane_ranks"].get(_serialized_lane(arm, kind)) is not None
                for item in documents
            )
            for arm, kind in lane_specs
        }
        candidate_lanes = case["trace"].get("candidate_lanes", {})
        lane_counts = {lane: len(candidate_lanes.get(lane, [])) for lane in lane_hits}
        top50_ratio = case.get("found_top50_ratio", "0/0")
        final_ratio = case.get("found_final_ratio", "0/0")
        cause_summary = ";".join(case.get("root_causes", ["UNRESOLVED"]))
        measured_explanation = _measured_explanation(case)
        case_sections.append(
            [
                "",
                f"## {case['case_id']}",
                "### A-D evidence summaries",
                "A/B/C query text: NOT_EMITTED_BY_PRIVACY_POLICY; D: CONTROLLED_INPUT_REFERENCE.",
                (
                    f"{CONTROL_LABELS['A']} candidates: "
                    f"lexical={lane_counts[_serialized_lane('A', 'lexical')]}, "
                    f"semantic={lane_counts[_serialized_lane('A', 'semantic')]}, "
                    f"lexical expected hits={lane_hits[_serialized_lane('A', 'lexical')]}, "
                    f"semantic expected hits={lane_hits[_serialized_lane('A', 'semantic')]}, "
                    f"indexed expected identities={case.get('expected_indexed_count', 0)}."
                ),
                (
                    f"{CONTROL_LABELS['B']} candidates: "
                    f"lexical={lane_counts[_serialized_lane('B', 'lexical')]}, "
                    f"semantic={lane_counts[_serialized_lane('B', 'semantic')]}, "
                    f"lexical expected hits={lane_hits[_serialized_lane('B', 'lexical')]}, "
                    f"semantic expected hits={lane_hits[_serialized_lane('B', 'semantic')]}, "
                    f"indexed expected identities={case.get('expected_indexed_count', 0)}."
                ),
                (
                    f"{CONTROL_LABELS['C']} candidates: "
                    f"lexical={lane_counts[_serialized_lane('C', 'lexical')]}, "
                    f"semantic={lane_counts[_serialized_lane('C', 'semantic')]}, "
                    f"lexical expected hits={lane_hits[_serialized_lane('C', 'lexical')]}, "
                    f"semantic expected hits={lane_hits[_serialized_lane('C', 'semantic')]}, "
                    f"indexed expected identities={case.get('expected_indexed_count', 0)}."
                ),
                (
                    f"{CONTROL_LABELS['D']} candidates: "
                    f"{len(case['trace'].get('D_EXACT_NUMBER_CONTROL_candidates', []))}; "
                    "expected-doc hits="
                    f"{sum(item['d_exact_control_rank'] is not None for item in documents)}."
                ),
                "Selected evidence is diagnostic-only, not persisted citation evidence.",
                (
                    f"Measured explanation ({case['case_id']}): "
                    f"top50={top50_ratio}, final={final_ratio}, codes={cause_summary}. "
                    f"{measured_explanation}"
                ),
                (
                    "Code paths: `documents/retrieval_repository.py:_select_candidates`; "
                    "`documents/hybrid_retrieval_repository.py:_select_semantic`; "
                    "`documents/reranked_semantic_repository.py:_rerank`."
                ),
                "### Required prompt trace fields",
                f"Trace: `{json.dumps(trace_summary, ensure_ascii=False)}`",
            ]
        )
    lines.extend(table_rows)
    for section in case_sections:
        lines.extend(section)
    lines.extend(
        [
            "",
            "## Blockers",
            *(result["blockers"] or ["NONE"]),
            "",
            "## Code path references",
            (
                "`documents/retrieval_repository.py:_select_candidates`; "
                "`documents/hybrid_retrieval_repository.py:_select_semantic`; "
                "`documents/reranked_semantic_repository.py:_read_candidates/_rerank`; "
                "`diagnostics/fulltext_root_cause.py`."
            ),
            "",
            "## Limitations",
            (
                "Reports include approved corpus metadata and controlled expected identities, but "
                "exclude raw questions, normalized/generated query text, chunks, answers, URLs, "
                "UUIDs, hydrated text, and prompts/model payloads. Review classifications are "
                "hypothesis selectors only; "
                "Q1/Q2/Q5/Q6/Q8/Q10 receive no special claim unless measured above."
            ),
        ]
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return markdown_path, json_path, csv_path


def _measured_explanation(case: dict[str, Any]) -> str:
    """Translate measured codes into generic, content-free review wording."""

    codes = set(case.get("root_causes", []))
    messages: list[str] = []
    capability = {code for code in codes if code.startswith("REVIEW_HYPOTHESIS_")}
    if capability:
        messages.append(
            "Code inspection confirms capability absence; case applicability is review-guided and "
            "requires repair evaluation."
        )
    if "INSUFFICIENCY_RECHECK_REQUIRED_CANDIDATE_PRESENT" in codes:
        messages.append(
            "Diagnostic candidate availability requires insufficiency recheck; final answer was "
            "not run."
        )
    if "RERANK_DEMOTION" in codes:
        messages.append("A pre-rerank expected candidate was demoted before final selection.")
    if "CANDIDATE_WINDOW_MISS" in codes or "DIRECT_DOCUMENT_MISS" in codes:
        messages.append("An expected candidate was measured outside the final candidate window.")
    if "TITLE_NOT_SEARCHED_PRODUCTION" in codes:
        messages.append("The expected identity was observed only in diagnostic title metadata.")
    return " ".join(messages) or "No additional measured stage explanation."


def _aggregate_availability(cases: list[dict[str, Any]]) -> dict[str, dict[str, int | str]]:
    """Use serialized lane labels so Markdown and safe JSON cannot drift."""

    documents = [
        document
        for case in cases
        for document in case.get("documents", [])
        if document.get("is_indexed", False)
    ]
    denominator = len(documents)
    a_semantic_key = _serialized_lane("A", "semantic")
    measures = {
        "production_equivalent_natural_question_semantic_top50": sum(
            document.get("lane_ranks", {}).get(a_semantic_key) is not None for document in documents
        ),
        "controlled_merged_diagnostic_top50": sum(
            document.get("found_merged_diagnostic_top50", False) for document in documents
        ),
        "production_equivalent_final_top3": sum(
            document.get("found_final_top3", False) for document in documents
        ),
    }
    return {
        label: {"count": count, "denominator": denominator, "ratio": f"{count}/{denominator}"}
        for label, count in measures.items()
    }


def _safe_candidate(row: object) -> dict[str, Any]:
    data = row if isinstance(row, dict) else {}
    return {
        key: data.get(key)
        for key in (
            "source_id",
            "document_number",
            "title",
            "legal_status",
            "version_number",
            "chunk_ordinal",
            "lexical_score",
            "semantic_score",
            "title_score",
            "reranker_score",
            "rank",
            "lanes",
            "rejection_codes",
        )
    }


def _safe_lane_ranks(value: object) -> dict[str, int | None]:
    ranks = value if isinstance(value, dict) else {}
    return {
        _serialized_lane(arm, kind): ranks.get(
            _serialized_lane(arm, kind), ranks.get(f"{arm}_{kind}")
        )
        for arm in ("A", "B", "C")
        for kind in ("lexical", "semantic")
    }


def _safe_trace(trace: object) -> dict[str, Any]:
    data = trace if isinstance(trace, dict) else {}
    lanes = data.get("candidate_lanes", {})
    safe_lanes = (
        {
            str(name): [_safe_candidate(row) for row in values]
            for name, values in lanes.items()
            if isinstance(name, str) and isinstance(values, list)
        }
        if isinstance(lanes, dict)
        else {}
    )
    candidate_lists = {
        name: [_safe_candidate(row) for row in data.get(name, [])]
        for name in (
            "title_metadata_only",
            "D_EXACT_NUMBER_CONTROL_candidates",
            "merged_diagnostic_top50",
            "pre_rerank",
            "post_rerank",
            "selected_evidence_diagnostic_final_top3",
            "selected_evidence",
            "rejected_evidence",
        )
        if isinstance(data.get(name, []), list)
    }
    return {
        "raw_question": CONTROLLED_INPUT_REFERENCE,
        "normalized_question": NOT_EMITTED,
        "intent": NOT_IMPLEMENTED,
        "entities": NOT_IMPLEMENTED,
        "org": NOT_IMPLEMENTED,
        "legal_topics": NOT_IMPLEMENTED,
        "sub_intents": NOT_IMPLEMENTED,
        "query_plan": NOT_IMPLEMENTED,
        "expanded_queries": NOT_EMITTED,
        "corpus_insight_policy": NOT_IMPLEMENTED,
        "corpus_insight_decision": NOT_IMPLEMENTED,
        "source_scope": list(SOURCE_IDS),
        "metadata_filters": data.get("metadata_filters", NOT_IMPLEMENTED),
        "filter_descriptions": data.get("filter_descriptions", []),
        "version_filters": "LATEST_INGESTED_ONLY",
        "effectivity_filters": {"legal_effect_resolver": NOT_IMPLEMENTED},
        "controls": {
            CONTROL_LABELS["A"]: NOT_EMITTED,
            CONTROL_LABELS["B"]: NOT_EMITTED,
            CONTROL_LABELS["C"]: NOT_EMITTED,
            CONTROL_LABELS["D"]: CONTROLLED_INPUT_REFERENCE,
        },
        "control_methodology": {
            CONTROL_LABELS["B"]: "REVIEW_SHEET_TOPIC_SENSITIVITY_TEST_NOT_GENERALIZATION",
            CONTROL_LABELS["C"]: (
                "ORACLE_EXPECTED_INVENTORY_SOURCE_LABEL_SENSITIVITY_TEST_NOT_PRODUCTION_EVIDENCE"
            ),
        },
        "candidate_lanes": safe_lanes,
        "lexical_candidates": {
            CONTROL_LABELS[arm]: safe_lanes.get(_serialized_lane(arm, "lexical"), [])
            for arm in ("A", "B", "C")
        },
        "semantic_candidates": {
            CONTROL_LABELS[arm]: safe_lanes.get(_serialized_lane(arm, "semantic"), [])
            for arm in ("A", "B", "C")
        },
        **candidate_lists,
        "rejected_count": data.get("rejected_count", 0),
        "rerank": {
            "fallback": bool(data.get("rerank", {}).get("fallback", True))
            if isinstance(data.get("rerank"), dict)
            else True,
            "reason": data.get("rerank", {}).get("reason", "NOT_IMPLEMENTED")
            if isinstance(data.get("rerank"), dict)
            else "NOT_IMPLEMENTED",
            "pre_window_versions": data.get("rerank", {}).get("pre_window_versions", 0)
            if isinstance(data.get("rerank"), dict)
            else 0,
            "hydration": NOT_EMITTED,
        },
        "final_answer_state": "NOT_RUN_DIAGNOSTIC_ONLY",
    }


def _safe_case(case: object) -> dict[str, Any]:
    data = case if isinstance(case, dict) else {}
    documents: list[dict[str, Any]] = []
    for document in (
        data.get("documents", []) if isinstance(data.get("documents", []), list) else []
    ):
        if not isinstance(document, dict):
            continue
        inventory = document.get("inventory", [])
        safe_inventory = (
            [
                {
                    key: item.get(key)
                    for key in (
                        "expected_display_number",
                        "classification",
                        "source_id",
                        "catalog_display_number",
                        "title",
                        "processing_status",
                        "reason_code",
                        "legal_status",
                        "linked_document",
                        "linked_version",
                        "chunk_count",
                        "exact_normalized_match",
                        "raw_exact_mismatch",
                        "retrievable_indexed",
                        "duplicate_catalog_identity",
                    )
                }
                for item in inventory
                if isinstance(item, dict)
            ]
            if isinstance(inventory, list)
            else []
        )
        documents.append(
            {
                "expected_display_number": document.get("expected_display_number"),
                "inventory": safe_inventory,
                "inventory_classification": document.get("inventory_classification"),
                "duplicates": bool(document.get("duplicates", False)),
                "raw_normalization_mismatch": bool(
                    document.get("raw_normalization_mismatch", False)
                ),
                "is_indexed": bool(document.get("is_indexed", False)),
                "lane_ranks": _safe_lane_ranks(document.get("lane_ranks", {})),
                "title_metadata_rank": document.get("title_metadata_rank"),
                "d_exact_control_rank": document.get("d_exact_control_rank"),
                "merged_top50_rank": document.get("merged_top50_rank"),
                "merged_diagnostic_top50_rank": document.get("merged_top50_rank"),
                "pre_rerank_semantic_top8_rank": document.get("pre_rerank_semantic_top8_rank"),
                "post_rerank_final_top3_rank": document.get("post_rerank_final_top3_rank"),
                "found_merged_diagnostic_top50": bool(
                    document.get("found_merged_diagnostic_top50", False)
                ),
                "found_final_top3": bool(document.get("found_final_top3", False)),
                "failure_stage": document.get("failure_stage"),
                "root_causes": document.get("root_causes", []),
                "confidence": document.get("confidence"),
                "rejected_evidence": [
                    _safe_candidate(item)
                    for item in document.get("rejected_evidence", [])
                    if isinstance(item, dict)
                ],
                "rejected_count": document.get("rejected_count", 0),
            }
        )
    return {
        "case_id": data.get("case_id"),
        "expected_documents": data.get("expected_documents", []),
        "documents": documents,
        "found_top50_count": data.get("found_top50_count", 0),
        "expected_indexed_count": data.get("expected_indexed_count", 0),
        "found_final_count": data.get("found_final_count", 0),
        "found_top50_ratio": data.get("found_top50_ratio", "0/0"),
        "found_final_ratio": data.get("found_final_ratio", "0/0"),
        "found_top50": bool(data.get("found_top50", False)),
        "found_final": bool(data.get("found_final", False)),
        "root_causes": data.get("root_causes", []),
        "failure_stages": data.get("failure_stages", []),
        "rejected_count": data.get("rejected_count", 0),
        "trace": _safe_trace(data.get("trace")),
    }

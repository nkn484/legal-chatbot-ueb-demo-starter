"""Read-only, content-free Phase-B1 PostgreSQL full-text search probe."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import String, bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.diagnostics.phase_b1_retrieval_engine import PlanSummary, safe_plan_summary
from legal_chatbot.documents.fts_query import build_or_tsquery
from legal_chatbot.documents.orm import DocumentChunk, DocumentVersion, LegalDocument

_SOURCES = ("VBQPPL", "VNU", "UEB")
_LIMIT = 50
_MAX_LEXEMES = 32
_INDEXES = (
    "ix_document_chunks_search_vector_gin",
    "ix_document_versions_title_search_vector_gin",
)


class FTSProbeCase(Protocol):
    """Private controlled input; expected identities are used only after search."""

    @property
    def case_id(self) -> str: ...

    @property
    def question(self) -> str: ...

    @property
    def expected_numbers(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class ProbeCase:
    case_id: str
    question: str = field(repr=False)
    expected_numbers: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True)
class FTSConfigInventory:
    config_matches_simple: bool
    content_gin_valid: bool
    title_gin_valid: bool
    indexes: tuple[tuple[str, bool, bool, bool, bool], ...]

    def safe(self) -> dict[str, object]:
        return {
            "config_matches_simple": self.config_matches_simple,
            "content_gin_valid": self.content_gin_valid,
            "title_gin_valid": self.title_gin_valid,
            "indexes": [
                {
                    "name": name,
                    "exists": exists,
                    "valid": valid,
                    "ready": ready,
                    "gin": gin,
                }
                for name, exists, valid, ready, gin in self.indexes
            ],
        }


@dataclass(frozen=True)
class TsqueryShape:
    lexeme_count: int
    numnode: int
    and_operator_count: int
    phrase_operator_count: int
    token_alias_distribution: dict[str, int]
    token_count: int
    truncated: bool

    def safe(self) -> dict[str, object]:
        return {
            "lexeme_count": self.lexeme_count,
            "numnode": self.numnode,
            "and_operator_count": self.and_operator_count,
            "phrase_operator_count": self.phrase_operator_count,
            "token_alias_distribution": self.token_alias_distribution,
            "token_count": self.token_count,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class LaneProbe:
    natural_unfiltered_rows: int
    natural_filtered_rows: int
    or_filtered_rows: int
    natural_unfiltered_expected: bool
    natural_filtered_expected: bool
    or_filtered_expected: bool
    natural_filtered_plan: PlanSummary
    or_filtered_plan: PlanSummary
    index_capability_control: PlanSummary | None = None
    actual_index_used: bool = False
    natural_filtered_index_used: bool = False
    or_filtered_index_used: bool = False
    index_capability_used: bool | None = None

    def safe(self) -> dict[str, object]:
        return {
            "natural_unfiltered_rows": self.natural_unfiltered_rows,
            "natural_filtered_rows": self.natural_filtered_rows,
            "or_filtered_rows": self.or_filtered_rows,
            "natural_unfiltered_expected": self.natural_unfiltered_expected,
            "natural_filtered_expected": self.natural_filtered_expected,
            "or_filtered_expected": self.or_filtered_expected,
            "natural_filtered_plan_summary": self.natural_filtered_plan.safe(),
            "or_filtered_plan_summary": self.or_filtered_plan.safe(),
            "actual_index_used": self.actual_index_used,
            "natural_filtered_index_used": self.natural_filtered_index_used,
            "or_filtered_index_used": self.or_filtered_index_used,
            "index_capability_used": self.index_capability_used,
            "index_capability_control": (
                None
                if self.index_capability_control is None
                else self.index_capability_control.safe()
            ),
            "index_capability_note": (
                "seqscan-off is an index-capability control, not evidence that the planner "
                "normally chooses that index"
                if self.index_capability_control is not None
                else None
            ),
        }


@dataclass(frozen=True)
class FTSProbeCaseResult:
    case_id: str
    shape: TsqueryShape
    content: LaneProbe
    title: LaneProbe
    data_query_count: int
    explain_query_count: int

    @property
    def query_count(self) -> int:
        return self.data_query_count + self.explain_query_count

    def safe(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "shape": self.shape.safe(),
            "lanes": {
                "CONTENT_FTS": self.content.safe(),
                "TITLE_FTS": self.title.safe(),
            },
            "data_query_count": self.data_query_count,
            "explain_query_count": self.explain_query_count,
            "query_count": self.query_count,
        }


@dataclass(frozen=True)
class FTSProbeResult:
    inventory: FTSConfigInventory
    cases: tuple[FTSProbeCaseResult, ...]
    data_query_count: int
    explain_query_count: int

    @property
    def query_count(self) -> int:
        return self.data_query_count + self.explain_query_count

    def safe(self) -> dict[str, object]:
        return {
            "inventory": self.inventory.safe(),
            "cases": [case.safe() for case in self.cases],
            "data_query_count": self.data_query_count,
            "explain_query_count": self.explain_query_count,
            "query_count": self.query_count,
        }


@dataclass(frozen=True)
class FTSProbeConfig:
    """Fixed safety bounds plus an opt-in planner capability control."""

    top_k: int = _LIMIT
    max_or_lexemes: int = _MAX_LEXEMES
    enable_index_capability_control: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.top_k, int) or isinstance(self.top_k, bool) or self.top_k != _LIMIT:
            raise ValueError("Phase-B1 FTS probe top_k must be 50")
        if (
            not isinstance(self.max_or_lexemes, int)
            or isinstance(self.max_or_lexemes, bool)
            or not 1 <= self.max_or_lexemes <= _MAX_LEXEMES
        ):
            raise ValueError("max_or_lexemes must be between 1 and 32")
        if not isinstance(self.enable_index_capability_control, bool):
            raise ValueError("enable_index_capability_control must be a boolean")


async def probe_fts_cases(
    session_factory: async_sessionmaker[AsyncSession],
    reader: Any,
    cases: Iterable[FTSProbeCase],
    *,
    config: FTSProbeConfig | None = None,
) -> FTSProbeResult:
    """Probe natural and OR FTS behavior without writing retrieval or citation records."""

    config = config or FTSProbeConfig()
    inventory = await _inventory(session_factory)
    results = []
    for case in cases:
        results.append(await _probe_case(session_factory, reader, case, config))
    return FTSProbeResult(
        inventory=inventory,
        cases=tuple(results),
        data_query_count=2 + sum(case.data_query_count for case in results),
        explain_query_count=sum(case.explain_query_count for case in results),
    )


async def _inventory(session_factory: async_sessionmaker[AsyncSession]) -> FTSConfigInventory:
    generated = text(
        "SELECT c.relname, "
        "position('''simple''::regconfig' in pg_get_expr(d.adbin, d.adrelid)) > 0 "
        "FROM pg_attrdef d JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
        "JOIN pg_class c ON c.oid = d.adrelid "
        "WHERE c.relname IN ('document_chunks', 'document_versions') "
        "AND a.attname IN ('search_vector', 'title_search_vector')"
    )
    indexes = text(
        "SELECT c.relname, i.indisvalid, i.indisready, am.amname = 'gin' "
        "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid JOIN pg_am am ON am.oid = c.relam "
        "WHERE c.relname IN ('ix_document_chunks_search_vector_gin', "
        "'ix_document_versions_title_search_vector_gin')"
    )
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            expressions = (await session.execute(generated)).all()
            index_rows = (await session.execute(indexes)).all()
    simple = len(expressions) == 2 and all(bool(row[1]) for row in expressions)
    present: dict[str, tuple[bool, bool, bool, bool]] = {
        str(row[0]): (True, bool(row[1]), bool(row[2]), bool(row[3])) for row in index_rows
    }
    inventory: tuple[tuple[str, bool, bool, bool, bool], ...] = tuple(
        (name, state[0], state[1], state[2], state[3])
        for name in _INDEXES
        for state in (present.get(name, (False, False, False, False)),)
    )
    values = {
        name: exists and valid and ready and gin
        for name, exists, valid, ready, gin in inventory
    }
    return FTSConfigInventory(
        config_matches_simple=simple,
        content_gin_valid=values[_INDEXES[0]],
        title_gin_valid=values[_INDEXES[1]],
        indexes=inventory,
    )


async def _probe_case(
    session_factory: async_sessionmaker[AsyncSession],
    reader: Any,
    case: FTSProbeCase,
    config: FTSProbeConfig,
) -> FTSProbeCaseResult:
    if not case.question.strip():
        raise ValueError("question must be nonblank")
    expected = frozenset(case.expected_numbers)
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            parsed = await session.execute(
                select(
                    func.websearch_to_tsquery(
                        text("'pg_catalog.simple'::regconfig"), bindparam("question")
                    ).cast(String).label("query_text"),
                    func.numnode(
                        func.websearch_to_tsquery(
                            text("'pg_catalog.simple'::regconfig"), bindparam("question")
                        )
                    ).label("numnode"),
                ),
                {"question": case.question},
            )
            tsquery_text, numnode = parsed.one()
            debug_rows = (
                await session.execute(
                    text("SELECT alias, token FROM ts_debug('pg_catalog.simple', :question)"),
                    {"question": case.question},
                )
            ).all()
            or_query, lexeme_count, truncated = build_or_tsquery(
                str(tsquery_text), max_lexemes=config.max_or_lexemes
            )
            shape = _shape(str(tsquery_text), int(numnode), debug_rows, lexeme_count, truncated)
            content, content_data, content_explain = await _probe_lane(
                session,
                reader,
                DocumentChunk.search_vector,
                expected,
                case.question,
                or_query,
                _INDEXES[0],
                config,
            )
            title, title_data, title_explain = await _probe_lane(
                session,
                reader,
                DocumentVersion.title_search_vector,
                expected,
                case.question,
                or_query,
                _INDEXES[1],
                config,
            )
    return FTSProbeCaseResult(
        case_id=case.case_id,
        shape=shape,
        content=content,
        title=title,
        data_query_count=2 + content_data + title_data,
        explain_query_count=content_explain + title_explain,
    )


def _shape(
    tsquery_text: str,
    numnode: int,
    debug_rows: Sequence[Any],
    lexeme_count: int,
    truncated: bool,
) -> TsqueryShape:
    aliases = Counter(str(row[0]) for row in debug_rows if row[1])
    return TsqueryShape(
        lexeme_count=lexeme_count,
        numnode=numnode,
        and_operator_count=tsquery_text.count("&"),
        phrase_operator_count=tsquery_text.count("<->"),
        token_alias_distribution=dict(sorted(aliases.items())),
        token_count=sum(1 for row in debug_rows if row[1]),
        truncated=truncated,
    )


async def _probe_lane(
    session: AsyncSession,
    reader: Any,
    vector: Any,
    expected: frozenset[str],
    question: str,
    or_query: str,
    index_name: str,
    config: FTSProbeConfig,
) -> tuple[LaneProbe, int, int]:
    natural = func.websearch_to_tsquery(
        text("'pg_catalog.simple'::regconfig"), bindparam("question")
    )
    control = func.to_tsquery(text("'pg_catalog.simple'::regconfig"), bindparam("or_query"))
    unfiltered = _statement(vector, natural, None)
    filtered = _reader_natural_statement(reader, vector)
    or_filtered = _statement(vector, control, reader._eligible_statement(_SOURCES)[1])
    params = {"question": question, "or_query": or_query}
    natural_unfiltered = (await session.execute(unfiltered, params)).all()
    natural_filtered = (await session.execute(filtered, params)).all()
    or_rows = (await session.execute(or_filtered, params)).all()
    natural_plan = await _explain(session, filtered, params)
    or_plan = await _explain(session, or_filtered, params)
    capability: PlanSummary | None = None
    capability_used: bool | None = None
    explain_count = 2
    if config.enable_index_capability_control and index_name not in natural_plan.index_names:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        try:
            capability = await _explain(session, filtered, params)
        finally:
            await session.execute(text("SET LOCAL enable_seqscan = on"))
        capability_used = index_name in capability.index_names
        explain_count += 1
    return (
        LaneProbe(
            natural_unfiltered_rows=len(natural_unfiltered),
            natural_filtered_rows=len(natural_filtered),
            or_filtered_rows=len(or_rows),
            natural_unfiltered_expected=_has_expected(natural_unfiltered, expected),
            natural_filtered_expected=_has_expected(natural_filtered, expected),
            or_filtered_expected=_has_expected(or_rows, expected),
            natural_filtered_plan=natural_plan,
            or_filtered_plan=or_plan,
            index_capability_control=capability,
            actual_index_used=index_name in natural_plan.index_names,
            natural_filtered_index_used=index_name in natural_plan.index_names,
            or_filtered_index_used=index_name in or_plan.index_names,
            index_capability_used=capability_used,
        ),
        3,
        explain_count,
    )


def _statement(vector: Any, query: Any, predicates: tuple[Any, ...] | None) -> Any:
    score = func.ts_rank_cd(vector, query)
    statement = (
        select(DocumentVersion.document_number_normalized)
        .select_from(DocumentVersion)
        .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
        .where(vector.op("@@")(query))
        .order_by(score.desc(), DocumentVersion.id.asc())
        .limit(_LIMIT)
    )
    if vector is DocumentChunk.search_vector:
        statement = statement.join(
            DocumentChunk, DocumentChunk.document_version_id == DocumentVersion.id
        )
    if predicates is not None:
        statement = statement.where(*predicates)
    return statement


def _has_expected(rows: Sequence[Any], expected: frozenset[str]) -> bool:
    return any(str(row[0]) in expected for row in rows if row[0] is not None)


def _reader_natural_statement(reader: Any, vector: Any) -> Any:
    """Keep production eligibility joins/predicates while returning only post-score identity."""

    if vector is DocumentChunk.search_vector:
        statement = reader._content_statement(_SOURCES, _LIMIT)  # noqa: SLF001
    else:
        statement = reader._title_statement(_SOURCES, _LIMIT)  # noqa: SLF001
    return statement.with_only_columns(DocumentVersion.document_number_normalized)


async def _explain(
    session: AsyncSession, statement: Any, params: Mapping[str, object]
) -> PlanSummary:
    dialect = session.bind.dialect if session.bind is not None else None
    if dialect is None:
        raise RuntimeError("PostgreSQL session is not bound")
    compiled = statement.params(**params).compile(
        dialect=dialect, compile_kwargs={"render_postcompile": True}
    )
    values = []
    for name in compiled.positiontup or ():
        value = compiled.params[name]
        processor = compiled._bind_processors.get(name)
        values.append(processor(value) if processor is not None else value)
    connection = await session.connection()
    payload = (
        await connection.exec_driver_sql(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}", tuple(values)
        )
    ).scalar_one()
    return safe_plan_summary(payload)

"""Run the controlled, read-only Prompt-01 fulltext diagnostic."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.diagnostics.fulltext_root_cause import (
    FulltextRootCauseEvaluator,
    parse_controlled_workbook,
    write_reports,
)
from legal_chatbot.reranking.config import RerankerSettings
from legal_chatbot.reranking.fastembed_adapter import FastEmbedRerankerAdapter
from legal_chatbot.semantic.config import SemanticSettings
from legal_chatbot.semantic.fastembed_adapter import FastEmbedSemanticAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Prompt-01 retrieval diagnostic")
    parser.add_argument(
        "--workbook",
        type=Path,
        default=Path("docs/Ket_qua_cham_toan_van_Stress_test_Legal_Chatbot_UEB_2026-08-22.xlsx"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("docs/diagnostics"))
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--semantic-model-path", type=Path)
    parser.add_argument("--reranker-model-path", type=Path)
    return parser


async def run(args: argparse.Namespace, *, settings: Settings | None = None) -> int:
    cases = parse_controlled_workbook(args.workbook)
    settings = settings or Settings()  # type: ignore[call-arg]
    semantic = (
        SemanticSettings(model_path=args.semantic_model_path)
        if args.semantic_model_path
        else SemanticSettings()
    )
    reranker = (
        RerankerSettings(model_path=args.reranker_model_path)
        if args.reranker_model_path
        else RerankerSettings()
    )
    engine = create_engine(settings)
    try:
        evaluator = FulltextRootCauseEvaluator(
            create_session_factory(engine),
            FastEmbedSemanticAdapter(semantic),
            FastEmbedRerankerAdapter(reranker),
            top_k=args.top_k,
            rerank_timeout_seconds=reranker.timeout_seconds,
        )
        result = await evaluator.evaluate(cases)
        write_reports(
            result,
            args.output_dir,
            markdown_path=args.markdown_output,
            json_path=args.json_output,
            csv_path=args.csv_output,
        )
        print(f"diagnostic_cases={len(cases)} blockers={len(result['blockers'])}")
        return 1 if result["blockers"] else 0
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

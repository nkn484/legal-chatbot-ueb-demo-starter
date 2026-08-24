"""Create the content-free Phase-B2A NATURAL versus BOUNDED_OR comparison report."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from legal_chatbot.diagnostics.phase_b2a_fts_query_comparison import (  # noqa: E402
    ComparisonError,
    compare_phase_b2a_reports,
)

DEFAULT_DIRECTORY = ROOT / "docs" / "evals" / "quality-retrieval"
DEFAULT_NATURAL = DEFAULT_DIRECTORY / "phase-b2a-natural.json"
DEFAULT_BOUNDED_OR = DEFAULT_DIRECTORY / "phase-b2a-bounded-or.json"
DEFAULT_STEM = DEFAULT_DIRECTORY / "phase-b2a-fts-query-repair"


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComparisonError(f"cannot load report: {path.name}") from error
    if not isinstance(payload, dict):
        raise ComparisonError(f"report root must be an object: {path.name}")
    return payload


def _rows(report: dict[str, Any]) -> tuple[tuple[str, object, object, object], ...]:
    baseline, candidate, deltas = report["baseline"], report["candidate"], report["deltas"]
    rows = []
    for key in (
        "content_expected_hits",
        "title_expected_hits",
        "content_rescue",
        "title_rescue",
        "fused_diagnostic_expected_hits",
    ):
        rows.append(
            (
                f"top50.{key}",
                baseline["top50"][key],
                candidate["top50"][key],
                deltas["top50"][key],
            )
        )
    for pool in ("8", "12", "16", "20"):
        for key in ("expected_hits", "noise_count", "noise_rate", "final_top3_expected_hits"):
            rows.append(
                (
                    f"pool_{pool}.{key}",
                    baseline["pools"][pool][key],
                    candidate["pools"][pool][key],
                    deltas["pools"][pool][key],
                )
            )
    for key in (
        "data_query_count_total",
        "max_data_query_count",
        "max_explain_query_count",
        "max_query_count",
        "preparation_query_count_total",
        "preparation_total_ms",
        "preparation_p95_ms",
        "reader_p95_ms",
        "retrieval_eval_p95_ms",
    ):
        rows.append(
            (
                f"cost.{key}",
                baseline["cost"][key],
                candidate["cost"][key],
                deltas["cost"][key],
            )
        )
    return tuple(rows)


def write_reports(
    report: dict[str, Any], *, json_path: Path, markdown_path: Path, csv_path: Path
) -> None:
    for path in (json_path, markdown_path, csv_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = _rows(report)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("metric", "natural", "bounded_or", "delta"))
        writer.writerows(rows)
    markdown_path.write_text(
        "# Phase B2A FTS Query Repair Comparison\n\n"
        f"Mechanical gate: **{report['mechanical_gate']['status']}**. "
        f"Conclusion: **{report['conclusion']}**.\n\n"
        "| Metric | NATURAL | BOUNDED_OR | Delta |\n|---|---:|---:|---:|\n"
        + "\n".join(
            f"| {metric} | {base} | {candidate} | {delta} |"
            for metric, base, candidate, delta in rows
        )
        + "\n\nThis is evaluation evidence only and does not approve runtime activation.\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare paired Phase-B2A FTS evaluator reports.")
    parser.add_argument("--natural-json", type=Path, default=DEFAULT_NATURAL)
    parser.add_argument("--bounded-or-json", type=Path, default=DEFAULT_BOUNDED_OR)
    parser.add_argument("--output-stem", type=Path, default=DEFAULT_STEM)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.output_stem.suffix:
        raise SystemExit("--output-stem must not include a suffix")
    try:
        report = compare_phase_b2a_reports(_load(args.natural_json), _load(args.bounded_or_json))
        write_reports(
            report,
            json_path=args.output_stem.with_suffix(".json"),
            markdown_path=args.output_stem.with_suffix(".md"),
            csv_path=args.output_stem.with_suffix(".csv"),
        )
    except ComparisonError as error:
        print(json.dumps({"status": "failed", "reason": type(error).__name__}))
        return 2
    print(json.dumps({"status": "ok", "gate": report["mechanical_gate"]["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

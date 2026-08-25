"""Create the focused P2/P4 corrective report from the controlled vertical-slice run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SOURCE = Path("docs/evals/p1-p10-vertical-slice-q05-q06-q10.json")
_JSON = Path("docs/evals/p2-p4-corrective-q05-q06-q10.json")
_MARKDOWN = Path("docs/evals/p2-p4-corrective-q05-q06-q10.md")
_REVIEW = Path("docs/review/p2-p4-corrective-review.md")
_GENERIC_SINGLE_CODES = {"AUTHORITY", "VALIDITY_APPLICABILITY", "GENERAL_LEGAL_ISSUE"}


def create_artifacts() -> dict[str, object]:
    """Write privacy-safe P2/P4 evidence from the latest controlled three-case run."""

    source = json.loads(_SOURCE.read_text(encoding="utf-8"))
    cases = [_case_artifact(case) for case in source["cases"]]
    decision, reasons = _decision(source, cases)
    report = {
        "schema_version": "P2-P4-CORRECTIVE-1",
        "source_run_timestamp": source["run_manifest"]["run_started_at"],
        "run_manifest": source["run_manifest"],
        "gate": {"decision": decision, "reasons": reasons},
        "cases": cases,
    }
    _atomic_write(_JSON, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(_MARKDOWN, _markdown(report))
    _atomic_write(_REVIEW, _review(report))
    return report


def _case_artifact(case: dict[str, Any]) -> dict[str, object]:
    if case["execution_status"] != "COMPLETED":
        return {
            "case_id": case["case_id"],
            "execution_status": case["execution_status"],
            "execution_failure": case.get("execution_failure"),
        }
    p6_counts = {
        sub_intent["id"]: 0 for sub_intent in case["question_analysis"]["sub_intents"]
    }
    for evidence in case["p6_pinpoint_evidence"]:
        for sub_intent_id in evidence["sub_intent_ids"]:
            p6_counts[sub_intent_id] = p6_counts.get(sub_intent_id, 0) + 1
    return {
        "case_id": case["case_id"],
        "execution_status": "COMPLETED",
        "p2": case["question_analysis"],
        "p3": {
            "discovered_document_count": case["p3_broad_discovery"][
                "discovered_document_count"
            ],
            "lane_counts": case["p3_broad_discovery"]["lane_counts"],
        },
        "p4": case["p4_authority_review"],
        "p6_evidence_count_by_sub_intent": p6_counts,
        "p7_coverage": case["p7_coverage_before_repair"],
    }


def _decision(source: dict[str, Any], cases: list[dict[str, object]]) -> tuple[str, list[str]]:
    if source["gate"]["decision"] == "BLOCKED_RUNTIME":
        return "BLOCKED_RUNTIME", list(source["gate"]["reasons"])
    incomplete = [case["case_id"] for case in cases if case["execution_status"] != "COMPLETED"]
    p2_failure = bool(incomplete)
    p4_failure = bool(incomplete)
    reasons: list[str] = [f"INCOMPLETE_DIAGNOSTIC:{case_id}" for case_id in incomplete]
    assessment_roles: set[str] = set()
    for case in cases:
        if case["execution_status"] != "COMPLETED":
            continue
        sub_intents = case["p2"]["sub_intents"]
        codes = [item["code"] for item in sub_intents]
        if len(codes) > 4 or not codes:
            p2_failure = True
            reasons.append(f"P2_SUB_INTENT_BOUND:{case['case_id']}")
        if len(codes) == 1 and codes[0] in _GENERIC_SINGLE_CODES:
            p2_failure = True
            reasons.append(f"P2_GENERIC_SINGLE_LABEL:{case['case_id']}")
        assessments = case["p4"]["assessments"]
        assessment_roles.update(item["validated_role"] for item in assessments)
        if not assessments:
            p4_failure = True
            reasons.append(f"P4_ASSESSMENTS_MISSING:{case['case_id']}")
    meaningful_roles = assessment_roles - {"BACKGROUND", "IRRELEVANT"}
    if not meaningful_roles:
        p4_failure = True
        reasons.append("P4_NO_RELEVANT_AUTHORITY_ROLE")
    if p2_failure and p4_failure:
        return "P2_P4_REWORK", reasons
    if p2_failure:
        return "P2_REWORK", reasons
    if p4_failure:
        return "P4_REWORK", reasons
    return (
        "P2_P4_PASS",
        [
            "Material decomposition is bounded and avoids generic single-label collapse.",
            "P4 produced sub-intent-aware validated roles beyond BACKGROUND/IRRELEVANT.",
            "This validates only the P2/P4 corrective objective, not legal quality or P1-P10 flow.",
        ],
    )


def _markdown(report: dict[str, Any]) -> str:
    rows = [
        "| Case | P2 codes | P4 outcome | P6 evidence | P7 states |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        if case["execution_status"] != "COMPLETED":
            rows.append(f"| {case['case_id']} | not completed | n/a | n/a | n/a |")
            continue
        codes = ", ".join(item["code"] for item in case["p2"]["sub_intents"])
        p6 = sum(case["p6_evidence_count_by_sub_intent"].values())
        states = ", ".join(item["state"] for item in case["p7_coverage"])
        rows.append(
            f"| {case['case_id']} | {codes} | {case['p4']['outcome']} | {p6} | {states} |"
        )
    return "\n".join(
        (
            "# P2/P4 Corrective Diagnostic",
            "",
            f"Source run: `{report['source_run_timestamp']}`",
            f"Decision: `{report['gate']['decision']}`",
            "",
            *rows,
            "",
            "P2 remains deterministic fallback; P11 remains OFF. This report contains no "
            "Oracle data, expected document IDs, or provider chain-of-thought.",
            "",
        )
    )


def _review(report: dict[str, Any]) -> str:
    reasons = "\n".join(f"- {reason}" for reason in report["gate"]["reasons"])
    return "\n".join(
        (
            "# P2/P4 Corrective Review",
            "",
            f"Final decision: `{report['gate']['decision']}`",
            "",
            "P2 live quality: `NOT_ESTABLISHED`",
            "P2 diagnostic mode: `DETERMINISTIC_FALLBACK`",
            "P4 LLM feature flag: `ON` for this diagnostic; provider failure falls back to "
            "the deterministic classifier.",
            "P11: `OFF`",
            "P3/P6/P8 PostgreSQL readers: `REAL`",
            "",
            reasons,
            "",
            "This gate does not establish legal quality, P12 success, release readiness, "
            "or P1-P10 FLOW_PASS.",
            "",
        )
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    print(create_artifacts()["gate"]["decision"])


if __name__ == "__main__":
    main()

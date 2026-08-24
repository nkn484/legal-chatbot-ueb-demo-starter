"""Safe-output tests for the standalone Gate-3 evaluation command."""

from __future__ import annotations

import json
from collections import Counter

from scripts import evaluate_prompt03_shadow

from legal_chatbot.legal_effects.shadow_evaluation import Prompt03ShadowEvaluationSummary


def test_evaluation_script_emits_harness_summary_without_identifiers(monkeypatch, capsys) -> None:
    summary = Prompt03ShadowEvaluationSummary(
        scenario_count=1,
        outcome_counts=Counter({"SHADOW_DISABLED": 1}),
        privilege_checks_pass=True,
        retrieval_citation_unchanged=True,
    )
    monkeypatch.setattr(
        evaluate_prompt03_shadow.shadow_evaluation,
        "run_prompt03_shadow_evaluation",
        lambda _: summary,
    )
    # Replace Settings directly with a minimal safe test double rather than accessing a real DSN.
    class _Settings:
        class database_url:
            @staticmethod
            def get_secret_value() -> str:
                return "synthetic-dsn"

    monkeypatch.setattr(evaluate_prompt03_shadow, "Settings", _Settings)
    assert evaluate_prompt03_shadow.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == summary.to_public_dict()
    assert "synthetic-dsn" not in json.dumps(payload)


def test_evaluation_script_emits_safe_failure_summary(monkeypatch, capsys) -> None:
    class _Settings:
        class database_url:
            @staticmethod
            def get_secret_value() -> str:
                return "synthetic-dsn"

    monkeypatch.setattr(evaluate_prompt03_shadow, "Settings", _Settings)
    monkeypatch.setattr(
        evaluate_prompt03_shadow.shadow_evaluation,
        "run_prompt03_shadow_evaluation",
        lambda _: (_ for _ in ()).throw(RuntimeError("sensitive")),
    )
    assert evaluate_prompt03_shadow.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == evaluate_prompt03_shadow._failure_summary()
    assert "sensitive" not in json.dumps(payload)

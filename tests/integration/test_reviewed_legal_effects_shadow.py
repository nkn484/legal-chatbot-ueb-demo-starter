"""Exact disposable PostgreSQL verification for the Gate-3 shadow harness."""

from __future__ import annotations

import os

import pytest

from legal_chatbot.core.config import Settings
from legal_chatbot.legal_effects.shadow_evaluation import run_prompt03_shadow_evaluation

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]


def test_reviewed_legal_effects_shadow_harness_reports_actual_synthetic_outcomes() -> None:
    summary = run_prompt03_shadow_evaluation(
        Settings().database_url.get_secret_value()  # type: ignore[call-arg]
    )
    assert summary.scenario_count == 7
    assert summary.outcome_counts == {
        "SHADOW_DISABLED": 1,
        "SHADOW_ELIGIBLE": 2,
        "SHADOW_SUPPRESSED_EVENT": 1,
        "SHADOW_UNRESOLVED": 1,
        "SHADOW_CONFLICT": 1,
        "SHADOW_INPUT_REJECTED": 1,
    }
    assert summary.privilege_checks_pass is True
    assert summary.retrieval_citation_unchanged is True
    assert summary.main_db_touched is False
    assert summary.temporary_diagnostics is True

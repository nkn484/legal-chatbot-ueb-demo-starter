"""Run the disposable synthetic Prompt-03 Gate-3 shadow evaluation checks."""

from __future__ import annotations

import json

from legal_chatbot.core.config import Settings
from legal_chatbot.legal_effects import shadow_evaluation


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _failure_summary() -> dict[str, object]:
    return {
        "scenario_count": 0,
        "outcome_counts": {},
        "privilege_checks_pass": False,
        "retrieval_citation_unchanged": False,
        "main_db_touched": False,
        "temporary_diagnostics": True,
    }


def main() -> int:
    """Run the harness directly and emit one safe aggregate summary."""

    try:
        settings = Settings()  # type: ignore[call-arg]
        summary = shadow_evaluation.run_prompt03_shadow_evaluation(
            settings.database_url.get_secret_value()
        )
    except Exception:
        _emit(_failure_summary())
        return 1
    _emit(summary.to_public_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

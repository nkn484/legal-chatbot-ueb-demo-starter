"""Content-free unit coverage for the standalone Phase-B1 FTS probe."""

from __future__ import annotations

import json

import pytest

from legal_chatbot.diagnostics.phase_b1_fts_probe import (
    FTSProbeConfig,
    ProbeCase,
    build_or_tsquery,
    safe_plan_summary,
)


def test_private_case_and_safe_plan_never_expose_input_or_plan_detail() -> None:
    case = ProbeCase("Q01", "private question token", ("private-document-number",))
    plan = safe_plan_summary(
        [
            {
                "Plan": {
                    "Node Type": "Limit",
                    "Filter": "private question token",
                    "Plans": [{"Node Type": "Seq Scan", "Output": ["private-document-number"]}],
                }
            }
        ]
    )

    assert "private" not in repr(case)
    public = json.dumps(plan.safe())
    assert "private question token" not in public
    assert "private-document-number" not in public
    assert "Filter" not in public and "Output" not in public


def test_or_control_quotes_lexemes_and_caps_to_32() -> None:
    control, count, truncated = build_or_tsquery("'it''s' & 'second'")

    assert control == "'it''s' | 'second'"
    assert count == 2
    assert truncated is False

    many = " & ".join(f"'term{number}'" for number in range(33))
    control, count, truncated = build_or_tsquery(many)
    assert count == 33 and truncated is True
    assert control.count("|") == 31


@pytest.mark.parametrize("value", (0, 33))
def test_or_control_rejects_unsafe_lexeme_bound(value: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 32"):
        build_or_tsquery("'term'", max_lexemes=value)


def test_config_enforces_fixed_top50_and_or_bound() -> None:
    assert FTSProbeConfig().top_k == 50
    no_capability_control = FTSProbeConfig(enable_index_capability_control=False)
    assert no_capability_control.enable_index_capability_control is False
    with pytest.raises(ValueError, match="top_k"):
        FTSProbeConfig(top_k=49)
    with pytest.raises(ValueError, match="top_k"):
        FTSProbeConfig(top_k=50.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="between 1 and 32"):
        FTSProbeConfig(max_or_lexemes=33)
    with pytest.raises(ValueError, match="between 1 and 32"):
        FTSProbeConfig(max_or_lexemes=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be a boolean"):
        FTSProbeConfig(enable_index_capability_control=1)  # type: ignore[arg-type]

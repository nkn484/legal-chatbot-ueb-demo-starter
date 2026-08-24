"""Synthetic unit coverage for the isolated reviewed-effects shadow profile."""

from __future__ import annotations

import pytest

from legal_chatbot.legal_effects.shadow import (
    ReviewedLegalEffectsManualPolicy,
    ReviewedLegalEffectsShadowDiagnostic,
    ReviewedLegalEffectsShadowEvaluator,
    ReviewedLegalEffectsShadowOutcome,
    ReviewedLegalEffectsShadowSettings,
    ShadowFamilyRef,
)


@pytest.mark.asyncio
async def test_disabled_shadow_does_not_open_a_database_session() -> None:
    def unopened_session():
        raise AssertionError("disabled shadow must not open a session")

    evaluator = ReviewedLegalEffectsShadowEvaluator(
        unopened_session, ReviewedLegalEffectsShadowSettings()  # type: ignore[arg-type]
    )
    result = await evaluator.evaluate(ShadowFamilyRef("synthetic-import", "synthetic-family"))
    assert result.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_DISABLED
    assert result.to_public_dict()["assertion_count"] == 0


@pytest.mark.asyncio
async def test_enabled_shadow_rejects_invalid_server_owned_reference_before_session_open() -> None:
    def unopened_session():
        raise AssertionError("invalid input must not open a session")

    evaluator = ReviewedLegalEffectsShadowEvaluator(
        unopened_session, ReviewedLegalEffectsShadowSettings(enabled=True)  # type: ignore[arg-type]
    )
    result = await evaluator.evaluate(ShadowFamilyRef("invalid input", "synthetic-family"))
    assert result.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_INPUT_REJECTED


def test_shadow_settings_and_diagnostic_are_frozen_content_free() -> None:
    settings = ReviewedLegalEffectsShadowSettings()
    assert settings.enabled is False
    assert settings.manual_policy is ReviewedLegalEffectsManualPolicy.HASH_PINNED_PILOT_ALLOWED

    diagnostic = ReviewedLegalEffectsShadowDiagnostic(
        outcome=ReviewedLegalEffectsShadowOutcome.SHADOW_ELIGIBLE,
        import_id="synthetic-import",
        family_id="synthetic-family",
        assertion_count=1,
        manual_snapshot_basis_count=1,
        manual_snapshot_caveat=True,
    )
    assert "synthetic-import" not in repr(diagnostic)
    assert "synthetic-family" not in repr(diagnostic)
    assert "import_id" not in diagnostic.to_public_dict()
    assert "family_id" not in diagnostic.to_public_dict()
    with pytest.raises(AttributeError):
        settings.enabled = True  # type: ignore[misc]

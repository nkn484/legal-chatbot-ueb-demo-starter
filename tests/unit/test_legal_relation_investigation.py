from uuid import uuid4

import pytest

from legal_chatbot.legal_evidence import (
    AuthorityCandidate,
    AuthorityRole,
    AuthorityState,
    DocumentVersionReference,
    EvidenceReference,
    RelationHint,
    RelationType,
)
from legal_chatbot.legal_evidence.relations import (
    RelationEvidence,
    RelationEvidenceMarker,
    RelationInvestigationOutcome,
    RelationInvestigationService,
    RelationInvestigationSettings,
    build_families,
)
from legal_chatbot.legal_evidence.transitions import verify_relation


def _candidate(label: str) -> AuthorityCandidate:
    return AuthorityCandidate(
        document=DocumentVersionReference(
            document_id=uuid4(),
            document_version_id=uuid4(),
            provenance_record_id=uuid4(),
            source_id=label,
        ),
        role=AuthorityRole.BACKGROUND,
        state=AuthorityState.ELIGIBLE,
        proposal_only=False,
    )


@pytest.mark.asyncio
async def test_default_relation_investigation_creates_singleton_families_without_hints() -> None:
    candidates = (_candidate("one"), _candidate("two"))
    result = await RelationInvestigationService(None).investigate(candidates)

    assert result.outcome is RelationInvestigationOutcome.DISABLED_FALLBACK
    assert result.hints == ()
    assert result.verified == ()
    assert len(result.families) == 2


@pytest.mark.asyncio
async def test_relation_investigation_respects_the_existing_fifteen_family_boundary() -> None:
    candidates = tuple(_candidate(f"source-{index}") for index in range(16))

    result = await RelationInvestigationService(None).investigate(candidates)

    assert len(result.families) == 15


@pytest.mark.asyncio
async def test_only_matching_explicit_evidence_marker_verifies_and_joins_family() -> None:
    candidates = (_candidate("one"), _candidate("two"))
    hint = RelationHint(
        subject_document_version_id=candidates[0].document.document_version_id,
        object_document_version_id=candidates[1].document.document_version_id,
        relation_type=RelationType.AMENDS,
    )
    evidence = EvidenceReference(
        document=candidates[0].document,
        chunk_id=uuid4(),
        locator="Article 1",
    )
    service = RelationInvestigationService(None, RelationInvestigationSettings(enabled=False))
    result = await service.investigate(candidates, ())
    matching = RelationEvidence(
        hint_id=hint.relation_id,
        marker=RelationEvidenceMarker.AMENDS,
        evidence=evidence,
    )

    verified = (verify_relation(hint, matching.evidence),)
    assert result.verified == ()
    assert len(verified) == 1
    assert len(build_families(candidates, verified)) == 1
    assert matching.marker.value == hint.relation_type.value


def test_relation_package_has_no_registry_import_or_mutation_path() -> None:
    from pathlib import Path

    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/legal_chatbot/legal_evidence/relations").glob("*.py")
    )
    assert "legal_effects.importer" not in content
    assert "ReviewedLegalEffectsImporter" not in content

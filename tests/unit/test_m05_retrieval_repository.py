"""Focused contract checks for retrieval persistence helper behavior."""

from uuid import uuid4

from legal_chatbot.documents.retrieval_repository import (
    PostgresLexicalRetrievalRepository,
    _CandidateRow,
)


def test_candidate_chain_validation_requires_matching_versions_and_provenance() -> None:
    version_id = uuid4()
    valid = _CandidateRow(uuid4(), version_id, uuid4(), version_id, 0.25)
    missing = _CandidateRow(uuid4(), version_id, None, None, 0.25)
    mismatched = _CandidateRow(uuid4(), version_id, uuid4(), uuid4(), 0.25)

    assert PostgresLexicalRetrievalRepository._has_valid_chain((valid,))
    assert not PostgresLexicalRetrievalRepository._has_valid_chain((missing,))
    assert not PostgresLexicalRetrievalRepository._has_valid_chain((mismatched,))

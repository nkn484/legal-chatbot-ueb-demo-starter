"""Construction-only source-isolation checks with no database or content inputs."""

import pytest

from legal_chatbot.documents.canonical_anchor_resolver import PostgresCanonicalAnchorResolver
from legal_chatbot.documents.retrieval_repository import PostgresLexicalRetrievalRepository


@pytest.mark.parametrize(
    "source_ids",
    (
        (),
        ("",),
        ("VBQPPL", "VBQPPL"),
        ("source-id-with-leading-space ",),
        ("x" * 33,),
        ("A", "B", "C", "D"),
    ),
)
def test_retrieval_and_canonical_resolver_reject_invalid_active_source_sets(
    source_ids: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="active_source_ids"):
        PostgresLexicalRetrievalRepository(object(), source_ids)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="active_source_ids"):
        PostgresCanonicalAnchorResolver(object(), source_ids)  # type: ignore[arg-type]


def test_explicit_test_source_injection_is_retained_without_a_production_default() -> None:
    repository = PostgresLexicalRetrievalRepository(object(), ("TESTM05",))  # type: ignore[arg-type]
    resolver = PostgresCanonicalAnchorResolver(object(), ("TESTM05",))  # type: ignore[arg-type]

    assert repository._active_source_ids == ("TESTM05",)
    assert resolver._active_source_ids == ("TESTM05",)

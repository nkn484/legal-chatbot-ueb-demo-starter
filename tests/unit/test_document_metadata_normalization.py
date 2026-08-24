"""Source-neutral canonical document metadata normalization checks."""

import pytest

from legal_chatbot.documents.metadata_normalization import normalize_document_number


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (" \u2003\t", None),
        (" 2725 / QĐ- ĐHKT ", "2725/qđ-đhkt"),
        ("2725/QĐ–ĐHKT", "2725/qđ-đhkt"),
        ("2725/QĐ—ĐHKT", "2725/qđ-đhkt"),
        ("Số  12 / 2025 / QH15", "số12/2025/qh15"),
        ("QUYẾT ĐỊNH  ĐẠI HỌC", "quyếtđịnhđạihọc"),
    ],
)
def test_normalize_document_number_is_unicode_canonical_and_source_neutral(
    value: str | None, expected: str | None
) -> None:
    assert normalize_document_number(value) == expected


def test_normalize_document_number_bounds_canonical_key() -> None:
    assert len(normalize_document_number("A" * 256) or "") == 256
    with pytest.raises(ValueError, match="256"):
        normalize_document_number("A" * 257)

import pytest
from fastapi import HTTPException

from app.projects.service import DEFAULT_OUTLINE, _document_text, _validate_document, _word_count


def test_default_outline_contains_the_academic_structure() -> None:
    assert len(DEFAULT_OUTLINE) == 13
    assert DEFAULT_OUTLINE[0] == "Introduction"
    assert DEFAULT_OUTLINE[-1] == "Annexes"


def test_document_text_and_word_count_are_derived_server_side() -> None:
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Bonjour le monde"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Deuxième section"}]},
            {"type": "paragraph", "content": [{"type": "equation", "attrs": {"value": "E=mc2"}}]},
        ],
    }

    assert _document_text(document) == "Bonjour le mondeDeuxième sectionE=mc2"
    assert _word_count(_document_text(document)) == 5


def test_invalid_or_oversized_documents_are_rejected() -> None:
    with pytest.raises(HTTPException):
        _validate_document({"type": "paragraph", "content": []})
    with pytest.raises(HTTPException):
        _validate_document({"type": "doc", "content": "not-a-list"})
    with pytest.raises(HTTPException):
        _validate_document({"type": "doc", "content": [{"type": "script"}]})

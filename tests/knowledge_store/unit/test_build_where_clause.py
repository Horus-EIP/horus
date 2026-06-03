"""Unit tests for ``build_where_clause`` (hermetic).

``build_where_clause`` lives in ``app.chroma_db.services.file_service``.
The conftest mocks chromadb / sentence-transformers / spaCy at import
time, and ``file_service`` imports from the ``app.chroma_db.setup`` and
``app.chroma_db.models`` submodules directly, so the function imports
cleanly with no real vector store, no model download, and no circular
import through ``app.chroma_db.__init__``.
"""

from __future__ import annotations

from app.chroma_db.models import SmartSearchRequest
from app.chroma_db.services.file_service import build_where_clause


def _req(**kwargs) -> SmartSearchRequest:
    """SmartSearchRequest with the required ``query`` filled in."""
    return SmartSearchRequest(query="anything", **kwargs)


class TestBuildWhereClause:
    def test_no_filters_returns_none(self):
        assert build_where_clause(_req()) is None

    def test_single_category_uses_eq(self):
        assert build_where_clause(_req(categories=["finance"])) == {
            "auto_category": {"$eq": "finance"}
        }

    def test_multiple_categories_use_or(self):
        assert build_where_clause(_req(categories=["finance", "legal"])) == {
            "$or": [
                {"auto_category": {"$eq": "finance"}},
                {"auto_category": {"$eq": "legal"}},
            ]
        }

    def test_min_confidence_uses_gte(self):
        assert build_where_clause(_req(min_confidence=0.5)) == {
            "confidence_score": {"$gte": 0.5}
        }

    def test_entity_type_uses_eq(self):
        assert build_where_clause(_req(entity_type="person")) == {
            "entity_type": {"$eq": "person"}
        }

    def test_single_entity_uses_contains(self):
        assert build_where_clause(_req(entities=["Alice"])) == {
            "entities_people": {"$contains": "Alice"}
        }

    def test_multiple_entities_combined_with_and(self):
        assert build_where_clause(_req(entities=["Alice", "Bob"])) == {
            "$and": [
                {"entities_people": {"$contains": "Alice"}},
                {"entities_people": {"$contains": "Bob"}},
            ]
        }

    def test_mixed_filters_combined_with_and(self):
        assert build_where_clause(_req(categories=["finance"], min_confidence=0.8)) == {
            "$and": [
                {"auto_category": {"$eq": "finance"}},
                {"confidence_score": {"$gte": 0.8}},
            ]
        }

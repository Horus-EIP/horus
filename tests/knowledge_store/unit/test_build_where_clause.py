from chroma_db.models.search import SmartSearchRequest
from app.chroma_db.services import build_where_clause


def test_build_where_clause_single_category():
    request = SmartSearchRequest(
        query="test query",
        categories=["category1"]
    )
    where_clause = build_where_clause(request)
    assert where_clause == {
        "auto_category": {"$eq": "category1"}
    }

def test_build_where_clause_multi_category():
    request = SmartSearchRequest(
        query="test query",
        categories=["category1", "category2"]
    )
    where_clause = build_where_clause(request)
    assert where_clause == {
        "$or": [
            {"auto_category": {"$eq": "category1"}},
            {"auto_category": {"$eq": "category2"}}
        ]
    }

def test_build_where_clause_combined():
    request = SmartSearchRequest(
        query="test query",
        categories=["category1"],
        entities=["John"],
        min_confidence=0.8
    )
    where_clause = build_where_clause(request)
    assert where_clause == {
        "$and": [
            {"auto_category": {"$eq": "category1"}},
            {"entities_people": {"$contains": "John"}},
            {"confidence_score": {"$gte": 0.8}}
        ]
    }

def test_build_where_clause_empty():
    request = SmartSearchRequest(
        query="test query"
    )
    where_clause = build_where_clause(request)
    assert where_clause is None

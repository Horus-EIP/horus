import datetime
import json
from typing import Any

from app.chroma_db.models import DocumentModel, SmartSearchRequest

from .. import get_embedding, knowledge_collection


async def store_file(doc: DocumentModel, auto_analysis: dict[str, Any] | None = None):
    """
    Store a document in the ChromaDB knowledge collection.

    Args:
        doc: DocumentModel with id, title, content, size.
        auto_analysis: Optional dict from ContentAnalyzer.analyze() with keys:
            auto_category, auto_type, auto_summary, entities, topics, confidence_score.
    """
    embedding = get_embedding(doc.content, is_query=False)

    metadata = {
        "title": doc.title,
        "date": str(datetime.datetime.now(datetime.UTC)),
        "size": doc.size,
    }

    if auto_analysis:
        metadata["auto_category"] = auto_analysis.get("auto_category", "general")
        metadata["auto_type"] = auto_analysis.get("auto_type", "unknown")
        metadata["auto_summary"] = auto_analysis.get("auto_summary", "")
        metadata["confidence_score"] = float(auto_analysis.get("confidence_score", 0.0))

        entities = auto_analysis.get("entities", {})
        metadata["entities"] = json.dumps(entities)
        metadata["topics"] = json.dumps(auto_analysis.get("topics", []))

        if entities.get("people"):
            metadata["entities_people"] = json.dumps(entities["people"])
        if entities.get("companies"):
            metadata["entities_companies"] = json.dumps(entities["companies"])
        if entities.get("amounts"):
            metadata["entities_amounts"] = json.dumps(entities["amounts"])
        if entities.get("dates"):
            metadata["entities_dates"] = json.dumps(entities["dates"])

    knowledge_collection.add(
        ids=[doc.id],
        documents=[doc.content],
        metadatas=[metadata],
        embeddings=[embedding],
    )


async def query_knowledge(query: str, n_results: int) -> dict:
    """
    Query the knowledge store for documents relevant to the search string.

    Args:
        query: The search query text.
        n_results: The maximum number of results to return.

    Returns:
        dict with 'ids', 'documents', 'metadatas', and 'distances'.
    """
    query_embedding = get_embedding(query, is_query=True)

    return knowledge_collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )


async def query_with_filters(query: str, filters: dict, n_results: int) -> dict:
    """
    Query the knowledge store with a query string and metadata filters.

    Args:
        query: The search query text.
        filters: ChromaDB where-clause filters.
        n_results: The number of results to return.

    Returns:
        dict with query results.
    """
    query_embedding = get_embedding(query, is_query=True)

    return knowledge_collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
        where=filters,
    )


async def delete_document(id: str) -> dict:
    """
    Delete a document from the knowledge store by its ID.

    Args:
        id: The ID of the document to delete.

    Returns:
        dict with status message.
    """
    knowledge_collection.delete(ids=[id])
    return {"status": "document deleted"}


def build_where_clause(request: SmartSearchRequest) -> dict | None:
    """
    Build a ChromaDB metadata where-clause filter from a SmartSearchRequest.

    Args:
        request: SmartSearchRequest with optional categories, entities,
                 min_confidence, entity_type.

    Returns:
        A ChromaDB where filter dict, or None if no filters apply.
    """
    where = []

    if request.categories:
        if len(request.categories) == 1:
            where.append({"auto_category": {"$eq": request.categories[0]}})
        else:
            where.append({"$or": [{"auto_category": {"$eq": cat}} for cat in request.categories]})

    if request.entities:
        for entity in request.entities:
            where.append({"entities_people": {"$contains": entity}})

    if request.min_confidence is not None:
        where.append({"confidence_score": {"$gte": request.min_confidence}})

    if request.entity_type:
        where.append({"entity_type": {"$eq": request.entity_type}})

    if not where:
        return None
    if len(where) == 1:
        return where[0]
    return {"$and": where}

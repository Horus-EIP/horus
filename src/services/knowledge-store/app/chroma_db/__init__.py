from app.chroma_db.setup import chroma_client, model, knowledge_collection, COLLECTION_NAME, get_embedding
from app.chroma_db.models import DocumentModel, SmartSearchRequest
from app.chroma_db.services import store_file, query_knowledge, delete_document, query_with_filters, build_where_clause

__all__ = [
    "chroma_client",
    "model",
    "knowledge_collection",
    "DocumentModel",
    "SmartSearchRequest",
    "get_embedding",
    "store_file",
    "query_knowledge",
    "query_with_filters",
    "delete_document",
    "build_where_clause",
    "COLLECTION_NAME",
]

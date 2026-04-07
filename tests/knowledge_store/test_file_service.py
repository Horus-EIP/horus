import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.chroma_db.services.file_service import store_file, query_knowledge, query_with_filters, delete_document
from app.chroma_db.models.document import DocumentModel

@pytest.mark.asyncio
async def test_store_file():
    doc = DocumentModel(
        id="test_id",
        title="Test Title",
        content="Test content",
        size=100
    )

    with patch("app.chroma_db.services.file_service.get_embedding") as mock_embedding, \
            patch("app.chroma_db.services.file_service.knowledge_collection") as mock_collection:
        mock_embedding.return_value = [0.1, 0.2, 0.3]
        await store_file(doc)
        mock_embedding.assert_called_once_with(doc.content, is_query=False)
        mock_collection.add.assert_called_once()

@pytest.mark.asyncio
async def test_store_file_with_analysis():
    doc = DocumentModel(
        id="test_id",
        title="Test Title",
        content="Test content",
        size=100
    )
    auto_analysis = {
        "auto_category": "accounting",
        "auto_type": "invoice",
        "auto_summary": "A test summary",
        "confidence_score": 0.85,
        "entities": {"people": ["Alice"], "companies": [], "amounts": ["$100"], "dates": []},
        "topics": ["accounting", "invoice"],
    }

    with patch("app.chroma_db.services.file_service.get_embedding") as mock_embedding, \
            patch("app.chroma_db.services.file_service.knowledge_collection") as mock_collection:
        mock_embedding.return_value = [0.1, 0.2, 0.3]
        await store_file(doc, auto_analysis=auto_analysis)
        mock_embedding.assert_called_once_with(doc.content, is_query=False)
        mock_collection.add.assert_called_once()

        call_args = mock_collection.add.call_args
        metadata = call_args[1]["metadatas"][0] if "metadatas" in call_args[1] else call_args[0][0]
        assert metadata["auto_category"] == "accounting"

@pytest.mark.asyncio
async def test_query_knowledge():
    fake_result = {"documents": [["doc1"]]}

    with patch("app.chroma_db.services.file_service.get_embedding") as mock_embedding, \
            patch("app.chroma_db.services.file_service.knowledge_collection") as mock_collection:

        mock_embedding.return_value = [0.1]
        mock_collection.query.return_value = fake_result

        result = await query_knowledge("test", 1)

        assert result == fake_result
        mock_collection.query.assert_called_once()

@pytest.mark.asyncio
async def test_query_with_filters():
    fake_result = {"documents": [["doc1"]]}

    with patch("app.chroma_db.services.file_service.get_embedding") as mock_embedding, \
            patch("app.chroma_db.services.file_service.knowledge_collection") as mock_collection:

        mock_embedding.return_value = [0.1]
        mock_collection.query.return_value = fake_result

        filters = {"title": "Test"}

        result = await query_with_filters("test", filters, 1)

        assert result == fake_result
        mock_collection.query.assert_called_once()

@pytest.mark.asyncio
async def test_delete_document():
    with patch("app.chroma_db.services.file_service.knowledge_collection") as mock_collection:
        result = await delete_document("1")

        mock_collection.delete.assert_called_once_with(ids=["1"])
        assert result["status"] == "document deleted"

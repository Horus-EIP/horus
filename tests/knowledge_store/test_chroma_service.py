import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.chroma_db.models import DocumentModel
from app.chroma_db.services.file_service import store_file, query_knowledge, delete_document

@pytest.fixture
def mock_chroma_components():
    with patch("app.chroma_db.services.file_service.knowledge_collection") as mock_collection, \
         patch("app.chroma_db.services.file_service.get_embedding") as mock_get_embedding:
        
        mock_get_embedding.return_value = [0.1, 0.2, 0.3]
        
        yield mock_collection, mock_get_embedding

@pytest.mark.asyncio
async def test_store_file(mock_chroma_components):
    mock_collection, mock_get_embedding = mock_chroma_components
    
    doc = DocumentModel(id="123", title="Test", content="Content", size=100)
    
    await store_file(doc)
    
    mock_get_embedding.assert_called_with("Content", is_query=False)
    mock_collection.add.assert_called_once()
    
    call_args = mock_collection.add.call_args[1]
    assert call_args["ids"] == ["123"]
    assert call_args["documents"] == ["Content"]
    assert "embeddings" in call_args

@pytest.mark.asyncio
async def test_query_knowledge(mock_chroma_components):
    mock_collection, mock_get_embedding = mock_chroma_components
    
    mock_collection.query.return_value = {"documents": [["Res"]]}
    
    results = await query_knowledge("query string", 5)
    
    mock_get_embedding.assert_called_with("query string", is_query=True)
    mock_collection.query.assert_called_once()
    assert results == {"documents": [["Res"]]}

@pytest.mark.asyncio
async def test_delete_document(mock_chroma_components):
    mock_collection, _ = mock_chroma_components
    
    res = await delete_document("123")
    
    mock_collection.delete.assert_called_once_with(ids=["123"])
    assert res["status"] == "document deleted"

import sys
import pytest
from unittest.mock import MagicMock, patch
import importlib

def test_chroma_init_create_collection():
    mock_chroma = sys.modules.get("chromadb")
    if not mock_chroma:
        mock_chroma = MagicMock()
        sys.modules["chromadb"] = mock_chroma

    mock_client = MagicMock()
    mock_chroma.PersistentClient.return_value = mock_client
    
    mock_client.get_collection.side_effect = Exception("Not found")
    
    import app.chroma_db.setup
    importlib.reload(app.chroma_db.setup)
    
    # Check if create_collection was called
    # Note: If knowledge_collection was assigned the result of create_collection
    mock_client.create_collection.assert_called_with(
        name="knowledge_collection",
        metadata={"embedding_model": "BAAI/bge-base-en-v1.5", "dimensions": 768}
    )
    
    mock_client.get_collection.side_effect = None

def test_posthog_setup_coverage():
    mock_posthog = MagicMock()
    original_capture = MagicMock()
    mock_posthog.capture = original_capture
    
    with patch.dict(sys.modules, {"posthog": mock_posthog}):
        import app.chroma_db.setup
        importlib.reload(app.chroma_db.setup)
        
        wrapper = mock_posthog.capture
        
        # 1. Normal call
        wrapper("event", prop="val")
        original_capture.assert_called_with("event", prop="val")
        
        # 2. Exception handling
        # We need side_effect to raise first time then succeed
        original_capture.side_effect = [TypeError("oops"), "Success"]
        wrapper("event", prop="val")
        
        # It should retry with args[0]
        # Check the LAST call
        original_capture.assert_called_with("event")
        
        # 3. Exception in retry
        original_capture.side_effect = [TypeError("oops"), Exception("fail")]
        ret = wrapper("event", prop="val")
        assert ret is None

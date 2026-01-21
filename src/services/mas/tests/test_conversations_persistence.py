"""
Tests for conversation tool functions - database-based implementation
"""

from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

import conversations.conversation_tool_functions as conv


@patch("conversations.conversation_tool_functions.SessionLocal")
def test_get_history_queries_database_correctly(mock_session_local):
    """Test that get_history queries the database with correct parameters"""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    # Setup for conversation existence check
    mock_query_conv = MagicMock()
    mock_filter_conv = MagicMock()
    mock_conversation = Mock(id=123)

    mock_query_msg = MagicMock()
    mock_filter_msg = MagicMock()
    mock_order_msg = MagicMock()

    # Create mock messages with proper datetime objects
    now = datetime.now()
    mock_messages = [
        Mock(id=1, role="user", content="Hello", created_at=now),
        Mock(id=2, role="assistant", content="Hi there!", created_at=now),
    ]

    # Configure mock_db.query to return different mocks for different calls
    mock_db.query.side_effect = [mock_query_conv, mock_query_msg]
    mock_query_conv.filter.return_value = mock_filter_conv
    mock_filter_conv.first.return_value = mock_conversation

    mock_query_msg.filter.return_value = mock_filter_msg
    mock_filter_msg.order_by.return_value = mock_order_msg
    mock_order_msg.all.return_value = mock_messages

    # Pass mock_db explicitly to avoid Depends(get_db)
    result = conv.get_history(123, db=mock_db)

    # Verify result is List[Dict] format
    assert isinstance(result, list)
    assert len(result) == 2
    assert all(isinstance(msg, dict) for msg in result)
    assert result[0]["role"] == "user"
    assert result[1]["role"] == "assistant"
    assert "created_at" in result[0]
    assert "id" in result[0]
    assert "content" in result[0]


@patch("conversations.conversation_tool_functions.SessionLocal")
def test_get_history_handles_empty_result(mock_session_local):
    """Test get_history when no messages exist for conversation"""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    # Setup query chain to return empty list
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_filter = MagicMock()
    mock_query.filter.return_value = mock_filter
    mock_order = MagicMock()
    mock_filter.order_by.return_value = mock_order
    mock_order.all.return_value = []

    result = conv.get_history(999, db=mock_db)
    assert result == []


@patch("conversations.conversation_tool_functions.SessionLocal")
@patch("conversations.conversation_tool_functions.Messages")
def test_add_messages_creates_and_saves_message(
    mock_messages_model, mock_session_local
):
    """Test that add_messages creates a message and saves it to database"""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    mock_message_instance = MagicMock()
    mock_messages_model.return_value = mock_message_instance

    conv.add_messages("user", "Test message", 456, db=mock_db)

    # Verify message was created with correct parameters
    mock_messages_model.assert_called_once_with(
        role="user", content="Test message", conversation_id=456
    )

    # Verify database operations
    mock_db.add.assert_called_once_with(mock_message_instance)
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once_with(mock_message_instance)


@patch("conversations.conversation_tool_functions.SessionLocal")
def test_get_conversations_queries_database_correctly(mock_session_local):
    """Test that get_conversations queries the database with correct parameters"""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_filter = MagicMock()
    mock_query.filter.return_value = mock_filter
    mock_order = MagicMock()
    mock_filter.order_by.return_value = mock_order

    # Create mock conversations with proper datetime objects
    now = datetime.now()
    mock_conversations = [
        Mock(
            id=1,
            owner_username="testuser",
            name="Conv 1",
            created_at=now,
            modified_at=now,
        ),
        Mock(
            id=2,
            owner_username="testuser",
            name="Conv 2",
            created_at=now,
            modified_at=now,
        ),
    ]
    mock_order.all.return_value = mock_conversations

    # Pass mock_db explicitly to avoid Depends(get_db)
    result = conv.get_conversations("testuser", db=mock_db)

    # Verify result is List[Dict] format
    assert isinstance(result, list)
    assert len(result) == 2
    assert all(isinstance(conv, dict) for conv in result)
    assert result[0]["id"] == 1
    assert result[0]["owner_username"] == "testuser"
    assert result[1]["id"] == 2
    assert "created_at" in result[0]
    assert "modified_at" in result[0]
    assert "name" in result[0]


# ---------- Tests: Error Handling and Session Management ----------


@patch("conversations.conversation_tool_functions.SessionLocal")
def test_get_history_with_no_db_session(mock_session_local):
    """Test get_history creates its own session when none provided."""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    # Setup minimal return values to avoid errors
    mock_db.query.return_value.filter.return_value.first.return_value = (
        None  # Conversation not found
    )

    conv.get_history(123, db=None)

    mock_session_local.assert_called_once()
    mock_db.close.assert_called_once()


@patch("conversations.conversation_tool_functions.SessionLocal")
def test_get_history_db_error(mock_session_local):
    """Test get_history handles database errors gracefully."""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db
    mock_db.query.side_effect = Exception("DB Error")

    result = conv.get_history(123, db=mock_db)
    assert result == []


@patch("conversations.conversation_tool_functions.SessionLocal")
def test_get_conversations_with_no_db_session(mock_session_local):
    """Test get_conversations creates its own session when none provided."""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
        []
    )

    conv.get_conversations("user", db=None)

    mock_session_local.assert_called_once()
    mock_db.close.assert_called_once()


@patch("conversations.conversation_tool_functions.SessionLocal")
def test_get_conversations_db_error(mock_session_local):
    """Test get_conversations handles database errors gracefully."""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db
    mock_db.query.side_effect = Exception("DB Error")

    result = conv.get_conversations("user", db=mock_db)
    assert result == []


@patch("conversations.conversation_tool_functions.SessionLocal")
def test_add_messages_with_no_db_session(mock_session_local):
    """Test add_messages creates its own session when none provided."""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    # Setup conversation found
    mock_db.query.return_value.filter.return_value.first.return_value = Mock(id=1)

    conv.add_messages("user", "msg", 1, db=None)

    mock_session_local.assert_called_once()
    mock_db.close.assert_called_once()


@patch("conversations.conversation_tool_functions.SessionLocal")
def test_add_messages_conversation_not_found(mock_session_local):
    """Test add_messages returns None if conversation not found."""
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    result = conv.add_messages("user", "msg", 999, db=mock_db)
    assert result is None


@patch("conversations.conversation_tool_functions.SessionLocal")
def test_add_messages_db_error(mock_session_local):
    """Test add_messages handles DB errors and performs rollback."""
    mock_db = MagicMock()
    # Setup conversation found
    mock_db.query.return_value.filter.return_value.first.return_value = Mock(id=1)
    # Fail on commit
    mock_db.commit.side_effect = Exception("Commit Error")

    result = conv.add_messages("user", "msg", 1, db=mock_db)

    assert result is None
    mock_db.rollback.assert_called()


@patch("conversations.conversation_tool_functions.SessionLocal")
def test_get_full_history(mock_session_local):
    """Test get_full_history wrapper."""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    # Setup minimal return
    mock_db.query.return_value.filter.return_value.first.return_value = None

    conv.get_full_history(123, db=None)

    mock_session_local.assert_called()
